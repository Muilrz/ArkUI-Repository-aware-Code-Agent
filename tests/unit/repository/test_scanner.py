from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arkui_agent.repository import (
    RepositoryFile,
    RepositoryFileType,
    RepositoryScanner,
    RepositoryWorkspace,
    classify_repository_path,
)
from tests.fixtures import synthetic_cpp_repository


class RepositoryScannerTests(unittest.TestCase):
    def test_policy_exclusion_is_independent_of_scan_results_and_uses_configured_names(self):
        with TemporaryDirectory() as root:
            scanner = RepositoryScanner(RepositoryWorkspace(root))
            self.assertEqual(scanner.excluded_directory(RepositoryFile.from_path("nested/Generated/x.cpp")), "Generated")
            self.assertIsNone(scanner.excluded_directory(RepositoryFile.from_path("src/missing.cpp")))
            self.assertIsNone(scanner.excluded_directory(RepositoryFile.from_path("src/generated.cpp")))
            custom = RepositoryScanner(RepositoryWorkspace(root), excluded_directories=("custom",))
            self.assertIsNone(custom.excluded_directory(RepositoryFile.from_path("generated/x.cpp")))
            self.assertEqual(custom.excluded_directory(RepositoryFile.from_path("CUSTOM/x.h")), "CUSTOM")

    def test_recursively_scans_temporary_repository(self) -> None:
        with synthetic_cpp_repository() as repository:
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            files = scanner.scan()

            self.assertEqual(
                files,
                tuple(
                    RepositoryFile.from_path(path)
                    for path in repository.relative_files
                ),
            )
            for file in files:
                path = file.path
                self.assertIsInstance(path, PurePosixPath)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertNotIn("\\", path.as_posix())

    def test_default_ignored_directories_are_not_scanned(self) -> None:
        with synthetic_cpp_repository() as repository:
            for directory_name in (".git", "build", "generated", "out", "var"):
                ignored_file = repository.root / directory_name / "ignored.cpp"
                ignored_file.parent.mkdir(parents=True)
                ignored_file.write_text("ignored", encoding="utf-8")
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            files = scanner.scan()

            self.assertEqual(
                files,
                tuple(
                    RepositoryFile.from_path(path)
                    for path in repository.relative_files
                ),
            )

    def test_include_and_exclude_patterns_filter_canonical_paths(self) -> None:
        with synthetic_cpp_repository() as repository:
            public_source = repository.root / "src" / "public.cpp"
            private_source = repository.root / "src" / "internal" / "private.cpp"
            public_source.write_text("public", encoding="utf-8")
            private_source.parent.mkdir()
            private_source.write_text("private", encoding="utf-8")
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            files = scanner.scan(
                include_patterns=("src/*",),
                exclude_patterns=("src/internal/*",),
            )

            self.assertEqual(
                files,
                (
                    RepositoryFile.from_path("src/public.cpp"),
                    RepositoryFile.from_path("src/widget.cpp"),
                ),
            )

    def test_file_type_filter_uses_minimal_generic_classification(self) -> None:
        with synthetic_cpp_repository() as repository:
            readme = repository.root / "README.md"
            readme.write_text("fixture", encoding="utf-8")
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.HEADER}),
                (RepositoryFile.from_path("include/fixture/widget.h"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.SOURCE}),
                (RepositoryFile.from_path("src/widget.cpp"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.TEST}),
                (RepositoryFile.from_path("tests/widget_test.cpp"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.OTHER}),
                (RepositoryFile.from_path("README.md"),),
            )

    def test_classification_uses_paths_only(self) -> None:
        self.assertEqual(
            classify_repository_path(PurePosixPath("source/component.cc")),
            RepositoryFileType.SOURCE,
        )
        self.assertEqual(
            classify_repository_path(PurePosixPath("include/component.hpp")),
            RepositoryFileType.HEADER,
        )
        self.assertEqual(
            classify_repository_path(PurePosixPath("test/component_test.cpp")),
            RepositoryFileType.TEST,
        )
        self.assertEqual(
            classify_repository_path(PurePosixPath("docs/component.md")),
            RepositoryFileType.OTHER,
        )

    def test_scan_order_is_deterministic(self) -> None:
        with synthetic_cpp_repository() as repository:
            for relative_path in ("zeta.txt", "alpha.txt", "nested/middle.txt"):
                path = repository.root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative_path, encoding="utf-8")
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            first_scan = scanner.scan()
            second_scan = scanner.scan()

            self.assertEqual(first_scan, second_scan)
            self.assertEqual(
                first_scan,
                tuple(sorted(first_scan, key=lambda file: file.path.as_posix())),
            )

    def test_scan_does_not_escape_workspace_root(self) -> None:
        with synthetic_cpp_repository() as repository:
            with TemporaryDirectory() as outside_directory:
                outside_file = Path(outside_directory) / "outside.cpp"
                outside_file.write_text("outside", encoding="utf-8")
                link = repository.root / "outside-link"
                try:
                    link.symlink_to(outside_directory, target_is_directory=True)
                except OSError:
                    pass
                scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

                files = scanner.scan()

                self.assertNotIn(
                    RepositoryFile.from_path("outside-link/outside.cpp"), files
                )
                self.assertNotIn(RepositoryFile.from_path("outside.cpp"), files)

    def test_excluded_directories_are_configurable(self) -> None:
        with synthetic_cpp_repository() as repository:
            vendor_source = repository.root / "vendor" / "dependency.cpp"
            vendor_source.parent.mkdir()
            vendor_source.write_text("dependency", encoding="utf-8")
            scanner = RepositoryScanner(
                RepositoryWorkspace(repository.root),
                excluded_directories={"vendor"},
            )

            files = scanner.scan()

            self.assertNotIn(
                RepositoryFile.from_path("vendor/dependency.cpp"), files
            )

    def test_directory_enumeration_error_fails_the_scan(self) -> None:
        with synthetic_cpp_repository() as repository:
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))
            error = PermissionError(
                13,
                "access denied",
                str(repository.root / "restricted"),
            )

            with patch(
                "arkui_agent.repository.scanner.os.scandir",
                side_effect=error,
            ):
                with self.assertRaises(PermissionError) as raised:
                    scanner.scan()

            self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
