import unittest
from dataclasses import replace

from arkui_agent.context.materialization import (
    CandidateLimitations, CandidateOrigin, ContextKind, MaterializationError, SnippetBounds, _Extractor,
)
from arkui_agent.context.snippets import _offset
from arkui_agent.graph.creation import PatternArgument
from arkui_agent.graph.layout import LayoutDependency
from arkui_agent.graph.model import EdgeIdentity, GraphEdge, NodeIdentity, NodeKind, RelationEvidence, RelationType, SourceAnchor
from arkui_agent.graph.property import PropertyBinding
from arkui_agent.knowledge import SnapshotIdentity
from arkui_agent.repository.model import RepositoryFile, SourceLocation, SymbolIdentity
from arkui_agent.retrieval.candidates import EvidenceSide


class SnippetCoordinateTests(unittest.TestCase):
    def test_unicode_crlf_eof_and_empty_file(self):
        file = RepositoryFile.from_path("example.cpp")
        first = SourceLocation(file, 1, 2)
        text = "中😀x\r\nnext\n"
        self.assertEqual(text[_offset(text, first)], "😀")
        self.assertEqual(_offset(text, SourceLocation(file, 2, 1)), 5)
        self.assertEqual(_offset(text, SourceLocation(file, 3, 1)), len(text))
        self.assertEqual(_offset("", SourceLocation(file, 1, 1)), 0)
        self.assertEqual(_offset("abc", SourceLocation(file, 2, 1)), 3)
        for location in (replace(first, column=5), replace(first, line=9)):
            with self.assertRaises(ValueError):
                _offset(text, location)

    def test_bounds_are_io_limits_not_token_budget(self):
        for kwargs in ({"max_file_bytes": 0}, {"max_backing_characters": True}, {"max_file_bytes": 1.0}):
            with self.assertRaises(MaterializationError):
                SnippetBounds(**kwargs)


class AssociationExtractionTests(unittest.TestCase):
    def test_independent_creation_property_layout_associations_do_not_create_call(self):
        # Hand-authored P2 observation units, not a real retrieval/baseline substitute.
        caller, factory, pattern, property_class = (NodeIdentity("symbol", value)
                                                   for value in ("caller", "factory", "pattern", "property"))
        proof = RelationEvidence("unit:existing", SourceAnchor(SymbolIdentity("caller")), "identity only")
        call = GraphEdge(EdgeIdentity(caller, factory, RelationType.CALL), (proof,))
        reference = GraphEdge(EdgeIdentity(NodeIdentity("file", "example.cpp"), property_class,
                                            RelationType.REFERENCE), (proof,))
        update = GraphEdge(EdgeIdentity(caller, property_class, RelationType.UPDATE_PROPERTY), (proof,))
        values = (PatternArgument(caller, factory, pattern, (call,), (proof,)),
                  LayoutDependency(factory, property_class, reference, (proof,)),
                  PropertyBinding("FontWeight", property_class, NodeKind.LAYOUT_PROPERTY, update, (proof,)))
        extractor = _Extractor()
        snapshot = SnapshotIdentity("unit", "generation", "repo", "a" * 40)
        extractor.add(values, snapshot=snapshot, side=EvidenceSide.TARGET, repository="repo", revision="a" * 40,
                      origin=CandidateOrigin("expansion", "query", (), caller, None, "unit observation", ()),
                      hashes=(), limits=CandidateLimitations(ambiguous=True, truncated=True,
                                                           notes=("missing_property_writer",)))
        candidates = tuple(extractor.records.values())
        edges = {v.identity for c in candidates for v in c.observations if isinstance(v, GraphEdge)}
        self.assertEqual(edges, {call.identity, reference.identity, update.identity})
        self.assertEqual(sum(c.kind is ContextKind.ASSOCIATION for c in candidates), 2)
        self.assertEqual(sum(c.kind is ContextKind.BINDING for c in candidates), 1)
        ids = set(extractor.records)
        self.assertTrue(all(set(c.dependencies) <= ids for c in candidates))
        self.assertTrue(all(c.limitations.ambiguous and c.limitations.truncated for c in candidates))
        self.assertTrue(all("missing_property_writer" in c.limitations.notes for c in candidates))
