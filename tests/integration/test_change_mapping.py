from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from arkui_agent.context import Change, ChangeKind, DiffLine, FileChange, Hunk, LineKind, LineRange, Origin, Provenance, Revision, Side
from arkui_agent.knowledge import SnapshotReadError
from arkui_agent.retrieval.candidates import Channel
from arkui_agent.retrieval.change_mapping import (
    ChangedRangeMapper, MappingBounds, MappingReason, MappingStatus, MappingUnsupportedError, MatchKind, PublicSymbolRangeReader,
)
from tests.fixtures.change_mapping import DualRevisionFixture, REPOSITORY, symbol


class ChangedRangeIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = DualRevisionFixture(Path(temporary.name))
        self.provenance = Provenance("structured-change", Origin.EXPLICIT)

    def bind(self, side, **kwargs):
        session = self.fixture.bind(side, **kwargs)
        self.addCleanup(session.close)
        return session

    def change(self, old=2, new=3, old_count=1, new_count=1, old_path="code.cpp", new_path="code.cpp", kind=ChangeKind.MODIFY):
        # These explicitly structured ranges test mapping, not diff text validation.
        hunk = Hunk(LineRange(Side.OLD, old, old + old_count), LineRange(Side.NEW, new, new + new_count), "",
                    (DiffLine(LineKind.DELETE, "old"),) * old_count + (DiffLine(LineKind.ADD, "new"),) * new_count,
                    self.provenance)
        return Change(REPOSITORY, Revision(self.fixture.base_revision), Revision(self.fixture.head_revision),
                      (FileChange(old_path, new_path, kind, (hunk,), (), self.provenance),), None, self.provenance)

    def test_connected_revisions_map_moved_function_with_separate_identities(self):
        base, head = self.bind("base"), self.bind("head")
        result = ChangedRangeMapper().map(self.change(), base=base, head=head)
        old, new = result.ranges
        self.assertEqual(old.symbols[0].seed.identity.value, "f:base")
        self.assertEqual(new.symbols[0].seed.identity.value, "f:head")
        self.assertNotEqual(old.symbols[0].seed.snapshot, new.symbols[0].seed.snapshot)
        self.assertEqual(old.symbols[0].evidence[0].relation, MatchKind.ENCLOSING)
        self.assertEqual(old.anchor.changed_range.side, Side.OLD)
        self.assertEqual(new.anchor.changed_range.side, Side.NEW)

    def test_missing_base_does_not_replace_old_ranges_with_head(self):
        result = ChangedRangeMapper().map(self.change(), base=None, head=self.bind("head"))
        self.assertEqual(result.ranges[0].status, MappingStatus.UNRESOLVED)
        self.assertEqual(result.ranges[0].diagnostics[0].reason, MappingReason.SESSION_ABSENT)
        self.assertTrue(result.ranges[1].symbols)

    def test_wrong_revision_or_repository_and_missing_revision_are_explicit(self):
        head = self.bind("head")
        result = ChangedRangeMapper().map(self.change(), base=head, head=head)
        self.assertEqual(result.ranges[0].diagnostics[0].reason, MappingReason.BINDING_MISMATCH)
        self.assertFalse(result.ranges[0].symbols)
        change = replace(self.change(), head_revision=Revision(None))
        result = ChangedRangeMapper().map(change, base=None, head=head)
        self.assertEqual(result.ranges[1].diagnostics[0].reason, MappingReason.REVISION_ABSENT)
        result = ChangedRangeMapper().map(replace(self.change(), repository="other"), base=None, head=head)
        self.assertEqual(result.ranges[1].diagnostics[0].reason, MappingReason.BINDING_MISMATCH)

    def test_add_and_delete_absent_side_not_applicable_and_existing_side_maps(self):
        base, head = self.bind("base"), self.bind("head")
        added = self.change(old=1, new=1, old_count=0, new_count=4, old_path=None, new_path="added.cpp", kind=ChangeKind.ADD)
        result = ChangedRangeMapper().map(added, base=base, head=head)
        self.assertEqual(result.ranges[0].status, MappingStatus.NOT_APPLICABLE)
        self.assertEqual(result.ranges[1].symbols[0].seed.identity.value, "added")
        deleted = self.change(old=1, new=1, old_count=4, new_count=0, old_path="gone.cpp", new_path=None, kind=ChangeKind.DELETE)
        result = ChangedRangeMapper().map(deleted, base=base, head=head)
        self.assertEqual(result.ranges[0].symbols[0].seed.identity.value, "deleted")
        self.assertEqual(result.ranges[1].status, MappingStatus.NOT_APPLICABLE)

    def test_rename_preserves_old_new_paths_even_for_same_opaque_identity(self):
        result = ChangedRangeMapper().map(self.change(old=2, new=2, old_path="old.cpp", new_path="new.cpp", kind=ChangeKind.RENAME),
                                           base=self.bind("base"), head=self.bind("head"))
        self.assertEqual([r.anchor.path for r in result.ranges], ["old.cpp", "new.cpp"])
        self.assertEqual([r.symbols[0].seed.identity.value for r in result.ranges], ["renamed", "renamed"])
        self.assertNotEqual(result.ranges[0].symbols[0].seed, result.ranges[1].symbols[0].seed)

    def test_hunk_crossing_functions_keeps_ambiguity_and_all_matches(self):
        result = ChangedRangeMapper().map(self.change(old=3, new=4, old_count=4, new_count=4),
                                           base=self.bind("base"), head=self.bind("head"))
        self.assertTrue(all(r.ambiguous and len(r.symbols) == 2 for r in result.ranges))
        self.assertTrue(all(e.relation is MatchKind.INTERSECTING for r in result.ranges for m in r.symbols for e in m.evidence))

    def test_nested_extents_are_not_reduced_to_first_or_smallest_symbol(self):
        records = self.fixture.records["base"] + (symbol("outer", "code.cpp", (1, 1), (8, 2)),)
        result = ChangedRangeMapper().map(self.change(), base=self.bind("base", records=records), head=None)
        self.assertEqual({m.seed.identity.value for m in result.ranges[0].symbols}, {"outer", "f:base"})
        self.assertTrue(result.ranges[0].ambiguous)

    def test_token_only_extent_does_not_invent_function_body_or_macro_symbol(self):
        base = self.bind("base", records=(symbol("f:token", "code.cpp", (1, 5), (1, 6)),))
        result = ChangedRangeMapper().map(self.change(old=2), base=base, head=None)
        self.assertEqual(result.ranges[0].status, MappingStatus.UNRESOLVED)
        self.assertEqual(result.ranges[0].symbols, ())
        macro = self.change(old=1, new=1, old_path="macro.h", new_path="macro.h")
        result = ChangedRangeMapper().map(macro, base=base, head=None)
        self.assertEqual(result.ranges[0].diagnostics[0].reason, MappingReason.NO_MATCH)

    def test_declaration_and_definition_ranges_both_retained_as_evidence(self):
        extent = symbol("f:base", "code.cpp", (1, 1), (4, 2)).definition
        record = symbol("f:base", "code.cpp", (1, 1), (4, 2), declaration=extent)
        result = ChangedRangeMapper().map(self.change(), base=self.bind("base", records=(record,)), head=None)
        self.assertEqual([p.field for p in result.ranges[0].symbols[0].evidence], ["declaration", "definition"])
        self.assertFalse(result.ranges[0].ambiguous)

    def test_insertion_point_inside_and_on_boundary(self):
        base = self.bind("base")
        result = ChangedRangeMapper().map(self.change(old=2, old_count=0), base=base, head=None)
        self.assertEqual(result.ranges[0].symbols[0].evidence[0].relation, MatchKind.POINT_INTERIOR)
        result = ChangedRangeMapper().map(self.change(old=1, old_count=0), base=base, head=None)
        self.assertEqual(result.ranges[0].status, MappingStatus.UNRESOLVED)

    def test_scope_and_unsupported_language_are_not_empty_mapping(self):
        base = self.bind("base", excluded=("code.cpp",))
        result = ChangedRangeMapper().map(self.change(), base=base, head=None)
        self.assertEqual(result.ranges[0].diagnostics[0].reason, MappingReason.SCOPE_INSUFFICIENT)
        script = self.change(old=1, new=1, old_path="script.py", new_path="script.py")
        result = ChangedRangeMapper().map(script, base=base, head=None)
        self.assertEqual(result.ranges[0].status, MappingStatus.UNSUPPORTED)

    def test_explicit_unsupported_adapter_and_real_closed_public_index_failure(self):
        class UnsupportedReader(PublicSymbolRangeReader):
            def read(self, file):
                raise MappingUnsupportedError("explicit unsupported backend capability")
        base = self.bind("base")
        result = ChangedRangeMapper(reader_factory=UnsupportedReader).map(self.change(), base=base, head=None)
        self.assertEqual(result.ranges[0].status, MappingStatus.UNSUPPORTED)
        class ClosedReader(PublicSymbolRangeReader):
            def read(self, file):
                self.view.index.close()
                return super().read(file)
        result = ChangedRangeMapper(reader_factory=ClosedReader).map(self.change(), base=base, head=None)
        self.assertEqual(result.ranges[0].status, MappingStatus.FAILURE)

    def test_bounds_preserve_range_fallbacks_and_detect_incomplete_matching(self):
        base, head = self.bind("base"), self.bind("head")
        for bounds in (MappingBounds(max_ranges=1), MappingBounds(max_symbols_per_file=1), MappingBounds(max_candidates_per_range=1)):
            result = ChangedRangeMapper(bounds).map(self.change(old=3, new=4, old_count=4, new_count=4), base=base, head=head)
            self.assertTrue(any(r.status is MappingStatus.TRUNCATED for r in result.ranges))
            self.assertEqual(len(result.ranges), 2)

    def test_integration_reuses_c1_preserving_hunk_origins_and_side_ids(self):
        base, head = self.bind("base"), self.bind("head")
        result = ChangedRangeMapper().retrieve(self.change(), base=base, head=head, channels=(Channel.SYMBOL, Channel.DEFINITION))
        self.assertTrue(result.old.candidates and result.new.candidates)
        self.assertTrue({c.candidate_id for c in result.old.candidates}.isdisjoint(c.candidate_id for c in result.new.candidates))
        self.assertTrue(all(any("c2:file=0:hunk=0:block=0" in o.label for q in c.provenance for o in q.origins) for c in result.old.candidates))
        payload = json.loads(result.to_json())
        self.assertEqual(payload["result"]["mapping"]["ranges"][0]["anchor"]["side"], "old")
        self.assertEqual(result.to_json(), ChangedRangeMapper().retrieve(self.change(), base=base, head=head, channels=(Channel.SYMBOL, Channel.DEFINITION)).to_json())

    def test_drift_during_mapping_aborts_entire_two_side_result(self):
        class DriftingReader(PublicSymbolRangeReader):
            def read(inner, file):
                records = super().read(file)
                (self.fixture.base / "code.cpp").write_text("drift\n", encoding="utf-8")
                return records
        with self.assertRaises(SnapshotReadError):
            ChangedRangeMapper(reader_factory=DriftingReader).map(self.change(), base=self.bind("base"), head=self.bind("head"))

    def test_declaration_in_different_file_cannot_prove_changed_body(self):
        foreign = symbol("f", "macro.h", (1, 1), (4, 2)).definition
        record = symbol("f:base", "code.cpp", (1, 5), (1, 6), declaration=foreign)
        result = ChangedRangeMapper().map(self.change(), base=self.bind("base", records=(record,)), head=None)
        self.assertEqual(result.ranges[0].symbols, ())

    def test_multifile_limit_and_metadata_only_fallback_survive_c1_integration(self):
        base, head = self.bind("base"), self.bind("head")
        first = self.change()
        rename = self.change(old=2, new=2, old_path="old.cpp", new_path="new.cpp", kind=ChangeKind.RENAME)
        change = replace(first, files=first.files + rename.files)
        result = ChangedRangeMapper(MappingBounds(max_files_per_side=1)).map(change, base=base, head=head)
        self.assertEqual(len(result.ranges), 4)
        self.assertTrue(all(r.status is MappingStatus.TRUNCATED for r in result.ranges[2:]))
        metadata = replace(rename, files=(replace(rename.files[0], hunks=()),))
        envelope = ChangedRangeMapper().retrieve(metadata, base=base, head=head, channels=(Channel.SYMBOL,))
        self.assertEqual([r.anchor.path for r in envelope.mapping.ranges], ["old.cpp", "new.cpp"])
        self.assertTrue(all(r.status is MappingStatus.UNRESOLVED for r in envelope.mapping.ranges))
        self.assertEqual(envelope.old.candidates, ())
        self.assertEqual(envelope.new.candidates, ())

    def test_out_of_source_change_and_stored_extent_cannot_create_seed(self):
        base = self.bind("base", records=(symbol("invalid", "code.cpp", (1, 1), (999, 1)),))
        for change in (self.change(), self.change(old=900)):
            result = ChangedRangeMapper().map(change, base=base, head=None)
            self.assertEqual(result.ranges[0].symbols, ())
            self.assertIn(MappingReason.INVALID_RANGE, [d.reason for d in result.ranges[0].diagnostics])


if __name__ == "__main__":
    unittest.main()
