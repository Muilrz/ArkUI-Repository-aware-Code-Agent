from __future__ import annotations

import io
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arkui_agent.repository import (
    ClangdSemanticProvider,
    ClangdProtocolError,
    ClangdUnavailableError,
    RepositoryWorkspace,
    RepositoryFile,
    SemanticProviderClosedError,
    SemanticProviderError,
    SymbolIdentity,
    SymbolKind,
)
from arkui_agent.repository.clangd import (
    _identity_key,
    _lsp_range_to_source_range,
    _opaque_symbol_identity,
    _symbol_info_location_to_range,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


class FixedScopeObservationTests(unittest.TestCase):
    def test_large_scope_is_prepared_completely_with_bounded_documents_and_reopens(self):
        with tempfile.TemporaryDirectory() as root:
            paths = tuple(RepositoryFile.from_path(f"file-{i:03d}.cpp") for i in range(100))
            for file in paths:
                (Path(root) / file.path).write_text("int value;\n")
            provider = object.__new__(ClangdSemanticProvider)
            provider._workspace = RepositoryWorkspace(root)
            provider._opened_documents = set()
            provider._closed = False
            opened, prepared, collected, peaks = set(), set(), [], []

            class Transport:
                def notify(inner, method, params):
                    uri = params["textDocument"]["uri"]
                    if method.endswith("didOpen"):
                        opened.add(uri)
                        peaks.append(len(opened))
                    elif method.endswith("didClose"):
                        opened.remove(uri)

                def request(inner, method, params):
                    uri = params["textDocument"]["uri"]
                    self.assertIn(uri, opened)
                    prepared.add(uri)
                    return []

            provider._transport = Transport()
            updates = []
            provider.set_progress_observer(lambda *event: updates.append(event))
            def collect(items, uri, *args):
                self.assertEqual(len(prepared), 100)
                self.assertIn(uri, opened)
                collected.append(uri)
            with patch.object(provider, "_collect_document_symbols", side_effect=collect):
                provider.symbol_observations_in_files(tuple(reversed(paths)))
            self.assertEqual(len(set(collected)), 100)
            self.assertEqual(collected, sorted(collected))
            self.assertLessEqual(max(peaks), provider.MAX_OPEN_DOCUMENTS)
            self.assertIn(("semantic_prepare", 100, 100, paths[-1].path.as_posix()), updates)
            self.assertIn(("semantic_collect", 100, 100, paths[-1].path.as_posix()), updates)
            first_collect = next(i for i, event in enumerate(updates) if event[0] == "semantic_collect")
            self.assertEqual(updates[first_collect - 1][1:3], (100, 100))
            closed_uri = next(uri for uri in collected if uri not in opened)
            provider._request("textDocument/references", {"textDocument": {"uri": closed_uri}})
            self.assertIn(closed_uri, opened)
            self.assertLessEqual(len(opened), provider.MAX_OPEN_DOCUMENTS)

    def test_all_documents_ready_before_any_location_collection(self):
        provider = object.__new__(ClangdSemanticProvider)
        events = []
        paths = (RepositoryFile.from_path("z.cpp"), RepositoryFile.from_path("a.h"))

        def open_document(file):
            events.append(("open", file.path.as_posix()))
            return file.path.as_posix()

        def request(method, params):
            self.assertEqual(method, "textDocument/documentSymbol")
            events.append(("ready", params["textDocument"]["uri"]))
            return []

        def collect(items, uri, *args):
            events.append(("collect", uri))

        with patch.object(provider, "_require_open"), patch.object(provider, "_open_document", side_effect=open_document), \
             patch.object(provider, "_request", side_effect=request), \
             patch.object(provider, "_collect_document_symbols", side_effect=collect):
            self.assertEqual(provider.symbol_observations_in_files(paths), ())
        self.assertEqual(events, [(phase, path) for phase in ("open", "ready", "collect") for path in ("a.h", "z.cpp")])


def _json_rpc_frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


class _LifecycleProcess:
    def __init__(self) -> None:
        self.stdin = _InspectableBytesIO()
        self.stdout = _InspectableBytesIO(
            _json_rpc_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "capabilities": {
                            "positionEncoding": "utf-8",
                            "callHierarchyProvider": True,
                        }
                    },
                }
            )
            + _json_rpc_frame({"jsonrpc": "2.0", "id": 2, "result": None})
        )
        self.stderr = None
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -1


class _InspectableBytesIO(io.BytesIO):
    def close(self) -> None:
        pass


class _BlockingOutput:
    def __init__(self) -> None:
        self.closed = False
        self._released = threading.Event()

    def readline(self) -> bytes:
        self._released.wait()
        return b""

    def read(self, length: int) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True
        self._released.set()

    def release(self) -> None:
        self._released.set()


class _TimeoutProcess:
    def __init__(self) -> None:
        self.stdin = _InspectableBytesIO()
        self.stdout = _BlockingOutput()
        self.stderr = None
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 1
        self.stdout.release()

    def kill(self) -> None:
        self.terminate()


class ClangdAdapterTests(unittest.TestCase):
    def test_initialize_and_shutdown_lifecycle_uses_json_rpc(self) -> None:
        process = _LifecycleProcess()
        with synthetic_cpp_repository() as repository:
            with (
                patch(
                    "arkui_agent.repository.clangd.shutil.which",
                    return_value="test-clangd",
                ),
                patch(
                    "arkui_agent.repository.clangd.subprocess.Popen",
                    return_value=process,
                ) as popen,
            ):
                provider = ClangdSemanticProvider(
                    RepositoryWorkspace(repository.root),
                    compilation_database_directory=repository.root,
                    fallback_flags=("-std=c++17",),
                )
                self.assertTrue(provider.supports_call_hierarchy)
                provider._opened_documents.add("file:///owned-document.cpp")

                provider.close()
                provider.close()
                with self.assertRaises(SemanticProviderClosedError):
                    provider.declaration(SymbolIdentity("unknown"))

            command = popen.call_args.args[0]
            self.assertIn(
                f"--compile-commands-dir={repository.root}",
                command,
            )
            self.assertFalse((repository.root / "compile_commands.json").exists())

        written = process.stdin.getvalue()
        self.assertIn(b'"method":"initialize"', written)
        self.assertIn(b'"method":"initialized"', written)
        self.assertIn(b'"method":"shutdown"', written)
        self.assertIn(b'"method":"exit"', written)
        self.assertNotIn(b'"method":"textDocument/didClose"', written)
        self.assertIsNotNone(process.poll())
        self.assertIn(b'"fallbackFlags":["-std=c++17"]', written)

    def test_request_timeout_aborts_unresponsive_clangd(self) -> None:
        process = _TimeoutProcess()
        with synthetic_cpp_repository() as repository:
            with (
                patch(
                    "arkui_agent.repository.clangd.shutil.which",
                    return_value="test-clangd",
                ),
                patch(
                    "arkui_agent.repository.clangd.subprocess.Popen",
                    return_value=process,
                ),
            ):
                with self.assertRaisesRegex(
                    ClangdProtocolError, "initialize.*timed out after 0.01 seconds"
                ):
                    ClangdSemanticProvider(
                        RepositoryWorkspace(repository.root),
                        request_timeout=0.01,
                    )

        self.assertEqual(process.returncode, 1)

    def test_request_timeout_must_be_positive_and_finite(self) -> None:
        with synthetic_cpp_repository() as repository:
            for invalid_timeout in (0, -1, float("inf")):
                with self.subTest(request_timeout=invalid_timeout):
                    with self.assertRaisesRegex(
                        ValueError, "finite and greater than zero"
                    ):
                        ClangdSemanticProvider(
                            RepositoryWorkspace(repository.root),
                            executable="not-consulted-for-invalid-timeout",
                            request_timeout=invalid_timeout,
                        )

    def test_symbol_info_definition_range_is_preferred_semantic_fact(self) -> None:
        with synthetic_cpp_repository() as repository:
            workspace = RepositoryWorkspace(repository.root)
            symbol_info = {
                "usr": "c:@N@fixture@S@Widget@F@value#1",
                "declarationRange": {
                    "uri": repository.header.as_uri(),
                    "range": {
                        "start": {"line": 7, "character": 8},
                        "end": {"line": 7, "character": 13},
                    },
                },
                "definitionRange": {
                    "uri": repository.source.as_uri(),
                    "range": {
                        "start": {"line": 4, "character": 12},
                        "end": {"line": 4, "character": 17},
                    },
                },
            }

            declaration = _symbol_info_location_to_range(
                workspace, symbol_info, "declarationRange", "utf-8"
            )
            definition = _symbol_info_location_to_range(
                workspace, symbol_info, "definitionRange", "utf-8"
            )

            self.assertIsNotNone(declaration)
            self.assertIsNotNone(definition)
            assert declaration is not None and definition is not None
            self.assertEqual(
                declaration.file.path.as_posix(), "include/fixture/widget.h"
            )
            self.assertEqual(definition.file.path.as_posix(), "src/widget.cpp")

    def test_lsp_range_is_converted_to_one_based_repository_range(self) -> None:
        with synthetic_cpp_repository() as repository:
            workspace = RepositoryWorkspace(repository.root)

            converted = _lsp_range_to_source_range(
                workspace,
                repository.source.as_uri(),
                {
                    "start": {"line": 4, "character": 4},
                    "end": {"line": 4, "character": 17},
                },
                "utf-8",
            )

            self.assertIsNotNone(converted)
            assert converted is not None
            self.assertEqual(converted.file.path.as_posix(), "src/widget.cpp")
            self.assertEqual((converted.start.line, converted.start.column), (5, 5))
            self.assertEqual((converted.end.line, converted.end.column), (5, 18))

    def test_position_encoding_conversion_is_centralized(self) -> None:
        with synthetic_cpp_repository() as repository:
            unicode_file = repository.root / "src" / "unicode.cpp"
            unicode_file.write_text("void café();\n", encoding="utf-8")
            workspace = RepositoryWorkspace(repository.root)
            lsp_range = {
                "start": {"line": 0, "character": 10},
                "end": {"line": 0, "character": 11},
            }

            converted = _lsp_range_to_source_range(
                workspace, unicode_file.as_uri(), lsp_range, "utf-8"
            )

            self.assertIsNotNone(converted)
            assert converted is not None
            self.assertEqual(converted.start.column, 10)
            self.assertEqual(converted.end.column, 11)

    def test_location_outside_repository_is_not_exposed(self) -> None:
        with synthetic_cpp_repository() as repository:
            workspace = RepositoryWorkspace(repository.root)
            external = Path(repository.root.parent) / "external.h"

            converted = _lsp_range_to_source_range(
                workspace,
                external.as_uri(),
                {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 1},
                },
                "utf-8",
            )

            self.assertIsNone(converted)

    def test_symbol_identity_is_stable_and_does_not_expose_usr(self) -> None:
        usr = "c:@N@fixture@S@Widget@F@value#1"

        first = _opaque_symbol_identity(f"usr\0{usr}")
        second = _opaque_symbol_identity(f"usr\0{usr}")
        other = _opaque_symbol_identity("usr\0other")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotIn(usr, first.value)

    def test_identity_fallback_does_not_collapse_overload_positions(self) -> None:
        first = _identity_key(
            None,
            SymbolKind.FUNCTION,
            "fixture::overloaded",
            "file:///repo/fixture.cpp",
            {"line": 4, "character": 4},
        )
        second = _identity_key(
            None,
            SymbolKind.FUNCTION,
            "fixture::overloaded",
            "file:///repo/fixture.cpp",
            {"line": 8, "character": 4},
        )

        self.assertNotEqual(first, second)

    def test_missing_executable_has_clear_unavailable_error(self) -> None:
        with synthetic_cpp_repository() as repository:
            with self.assertRaisesRegex(
                ClangdUnavailableError, "clangd executable was not found"
            ):
                ClangdSemanticProvider(
                    RepositoryWorkspace(repository.root),
                    executable="definitely-missing-clangd-for-test",
                )

    def test_invalid_compilation_database_directory_is_rejected(self) -> None:
        with synthetic_cpp_repository() as repository:
            with self.assertRaisesRegex(
                SemanticProviderError, "Compilation database directory does not exist"
            ):
                ClangdSemanticProvider(
                    RepositoryWorkspace(repository.root),
                    executable="definitely-missing-clangd-for-test",
                    compilation_database_directory=repository.root / "missing",
                )


if __name__ == "__main__":
    unittest.main()
