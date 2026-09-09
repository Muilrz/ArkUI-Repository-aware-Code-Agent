from __future__ import annotations

import unittest

from arkui_agent.context import LineRange, Side, parse_unified_diff
from arkui_agent.repository import RepositoryFile, SourceLocation, SourceRange
from arkui_agent.retrieval.candidates import CandidateInputError
from arkui_agent.retrieval.change_mapping import ChangedRangeMapper, MappingBounds, MatchKind, changed_anchors, extent_relation


class ChangedRangeContractTests(unittest.TestCase):
    def parse(self, text):
        return parse_unified_diff(text, repository="repo", base_revision="a" * 40, head_revision="b" * 40, source_id="diff").value

    def extent(self, start, end):
        file = RepositoryFile.from_path("code.cpp")
        return SourceRange(SourceLocation(file, *start), SourceLocation(file, *end))

    def test_edit_blocks_exclude_context_and_preserve_empty_side_position(self):
        change = self.parse("--- code.cpp\n+++ code.cpp\n@@ -1,5 +1,6 @@\n first\n-old\n+new\n middle\n+insert\n last\n tail\n")
        anchors = changed_anchors(change)
        self.assertEqual([(a.side.value, a.changed_range.start_line, a.changed_range.end_line) for a in anchors],
                         [("old", 2, 3), ("new", 2, 3), ("old", 4, 4), ("new", 4, 5)])
        self.assertTrue(all(a.hunk_provenance == change.files[0].hunks[0].provenance for a in anchors))

    def test_no_newline_markers_do_not_consume_range_coordinates(self):
        change = self.parse("--- code.cpp\n+++ code.cpp\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n")
        self.assertEqual([a.changed_range.count for a in changed_anchors(change)], [1, 1])

    def test_half_open_intersection_and_token_only_extent(self):
        changed = LineRange(Side.OLD, 3, 4)
        self.assertEqual(extent_relation(changed, self.extent((1, 1), (5, 2))), MatchKind.ENCLOSING)
        self.assertEqual(extent_relation(changed, self.extent((3, 8), (3, 9))), MatchKind.INTERSECTING)
        self.assertIsNone(extent_relation(changed, self.extent((4, 1), (6, 1))))
        self.assertIsNone(extent_relation(changed, self.extent((1, 1), (3, 1))))

    def test_zero_length_point_needs_strict_interior_no_boundary_snapping(self):
        point = LineRange(Side.NEW, 3, 3)
        self.assertEqual(extent_relation(point, self.extent((2, 1), (4, 1))), MatchKind.POINT_INTERIOR)
        for extent in (self.extent((3, 1), (4, 1)), self.extent((1, 1), (3, 1)), self.extent((3, 1), (3, 1))):
            self.assertIsNone(extent_relation(point, extent))

    def test_rename_without_hunks_retains_two_file_candidates(self):
        change = self.parse("diff --git a/old.cpp b/new.cpp\nsimilarity index 100%\nrename from old.cpp\nrename to new.cpp\n")
        anchors = changed_anchors(change)
        self.assertEqual([a.path for a in anchors], ["old.cpp", "new.cpp"])
        self.assertTrue(all(a.changed_range is None for a in anchors))

    def test_invalid_bounds_and_rejected_parser_results_are_not_empty_success(self):
        for value in (0, -1, True, 2.5):
            with self.assertRaises(CandidateInputError):
                MappingBounds(max_ranges=value)
        rejected = parse_unified_diff("diff --cc code.cpp\n", repository="repo", base_revision=None, head_revision=None, source_id="diff")
        with self.assertRaises(CandidateInputError):
            ChangedRangeMapper().map(rejected, base=None, head=None)


if __name__ == "__main__":
    unittest.main()
