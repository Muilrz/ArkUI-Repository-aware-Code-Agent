from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from arkui_agent.repository import (
    ClangdSemanticProvider,
    ClangdUnavailableError,
    RepositoryWorkspace,
    SemanticProviderClosedError,
    SemanticProviderError,
    SymbolIdentity,
)
from arkui_agent.repository.clangd import (
    _lsp_range_to_source_range,
    _opaque_symbol_identity,
)
from tests.fixtures.synthetic_cpp_repository import synthetic_cpp_repository


def _json_rpc_frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


class _LifecycleProcess:
    def __init__(self) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(
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
        self.assertIn(b'"fallbackFlags":["-std=c++17"]', written)

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
