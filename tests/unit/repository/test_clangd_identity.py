"""Endpoint identity binding regressions at the P1 protocol adapter boundary."""
import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from itertools import permutations
from pathlib import Path

from arkui_agent.repository import (
    ClangdSemanticProvider, ClangdProtocolError, RepositoryWorkspace,
    SymbolKind, SymbolMergeConflict, SymbolObservation, canonicalize_symbols,
)
from arkui_agent.repository.clangd import _identity_key, _opaque_symbol_identity, _select_symbol_info


def info(name, usr):
    return {"name": name, "containerName": "N::", "usr": usr,
            "id": hashlib.sha1(usr.encode()).hexdigest()[:16].upper()}


class EndpointIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.path = root / "widget.h"
        self.path.write_text("class Widget {};\nPROPERTY(value);\nvoid update();\n", encoding="utf-8")
        self.uri = self.path.as_uri()
        self.owner = info("Widget", "c:@N@N@S@Widget")
        self.method = info("update", "c:@N@N@S@Widget@F@update#")
        self.method["containerName"] = "N::Widget::"
        self.provider = object.__new__(ClangdSemanticProvider)
        self.provider._workspace = RepositoryWorkspace(root)
        self.provider._position_encoding = "utf-8"
        self.provider._observations = []
        self.provider._handles = {}
        self.provider._open_document = lambda file: self.uri

        def request(method, params):
            if method == "textDocument/symbolInfo":
                line = params["position"]["line"]
                if line == 2:
                    return [self.method]
                return [self.owner, info("PROPERTY", "c:macro@PROPERTY")]
            return []
        self.provider._request = request

    def item(self, name, kind, line, data=None):
        extent = {"start": {"line": line, "character": 0},
                  "end": {"line": line, "character": 4}}
        return {"name": name, "kind": kind, "uri": self.uri, "range": extent,
                "selectionRange": extent, "data": data, "detail": "N::Widget::" + name}

    def document(self, name, kind, line):
        output = []
        self.provider._collect_document_symbols([self.item(name, kind, line)], self.uri,
                                                 output, None, None, "")
        return output[0].symbol

    def test_macro_method_does_not_inherit_parent_identity_or_locations(self):
        owner = self.document("Widget", 5, 0)
        method = self.provider._call_hierarchy_symbol(self.item("update", 6, 1, self.method["id"]))
        self.assertNotEqual(owner.identity, method.identity)
        self.assertEqual(method.qualified_name, "N::Widget::update")
        self.assertEqual(method.declaration.start.line, 2)
        self.assertIsNone(method.definition)
        # Every endpoint payload is retained, including rejected parent/macro results.
        all_evidence = [json.loads(o.provenance) for o in self.provider.symbol_observations()]
        related = next(e for e in all_evidence if e["endpoint"] == "callHierarchy")
        self.assertEqual(related["symbol_info"]["payload"][0], self.owner)
        self.assertEqual(related["item"]["data"], self.method["id"])

    def test_document_and_call_identity_are_query_order_independent(self):
        results = []
        for order in permutations(("document", "call")):
            symbols = {}
            for endpoint in order:
                symbols[endpoint] = (self.document("update", 6, 2) if endpoint == "document" else
                    self.provider._call_hierarchy_symbol(self.item("update", 6, 2, self.method["id"])))
            self.assertEqual(symbols["document"].identity, symbols["call"].identity)
            results.append(symbols["call"].identity)
        self.assertEqual(results[0], results[1])

    def test_usr_only_and_symbol_id_paths_normalize_equally(self):
        args = (SymbolKind.METHOD, "N::Widget::update", self.uri, {"line": 2, "character": 0})
        self.assertEqual(_identity_key({"usr": self.method["usr"]}, *args),
                         _identity_key({"id": self.method["id"]}, *args))

    def test_symbol_info_selection_does_not_depend_on_payload_order(self):
        for ordered in permutations((self.owner, self.method)):
            self.assertEqual(_select_symbol_info(list(ordered), "update", self.method["id"]), self.method)

    def test_prepare_selects_requested_id_not_first_parent_or_callee(self):
        symbol = self.document("update", 6, 2)
        handle = SimpleNamespace(symbol=symbol, uri=self.uri, position={"line": 2, "character": 0})
        wanted = self.item("update", 6, 2, self.method["id"])
        unrelated = self.item("Widget", 5, 0, self.owner["id"])
        self.provider._supports_call_hierarchy = True
        for ordered in permutations((wanted, unrelated)):
            def request(method, params):
                if method == "textDocument/prepareCallHierarchy":
                    return list(ordered)
                self.assertEqual(params["item"], wanted)
                return []
            self.provider._request = request
            self.assertEqual(self.provider._call_hierarchy_items(handle, "callHierarchy/outgoingCalls", "to"), ())

    def test_fallback_never_borrows_unrelated_identity(self):
        with self.assertRaises(ClangdProtocolError):
            self.provider._call_hierarchy_symbol(self.item("update", 6, 1))
        self.provider._request = lambda method, params: []
        first = self.provider._call_hierarchy_symbol(self.item("update", 6, 1))
        second = self.provider._call_hierarchy_symbol(self.item("other", 6, 1))
        self.assertNotEqual(first.identity, second.identity)
        owner_id = _opaque_symbol_identity(_identity_key(self.owner, SymbolKind.CLASS,
                                                        "N::Widget", self.uri, {"line": 0, "character": 0}))
        self.assertNotEqual(first.identity, owner_id)

    def test_genuine_same_identity_kind_contradiction_still_fails(self):
        method = self.provider._call_hierarchy_symbol(self.item("update", 6, 2, self.method["id"]))
        wrong = self.provider._call_hierarchy_symbol(self.item("update", 5, 2, self.method["id"]))
        for ordered in permutations((method, wrong)):
            with self.assertRaises(SymbolMergeConflict):
                canonicalize_symbols(SymbolObservation(s) for s in ordered)

    def test_id_usr_contradiction_is_not_hidden(self):
        with self.assertRaises(ClangdProtocolError):
            _select_symbol_info([{**self.method, "id": self.owner["id"]}], "update", self.owner["id"])

    def test_anonymous_namespace_endpoint_display_spelling_is_not_an_identity(self):
        anonymous = info("(anonymous)", "c:@N@N@aN")
        self.assertEqual(_select_symbol_info([anonymous], "(anonymous namespace)", None,
                                            SymbolKind.NAMESPACE), anonymous)
        with self.assertRaises(ClangdProtocolError):
            _select_symbol_info([anonymous], "(anonymous namespace)", None, SymbolKind.CLASS)
