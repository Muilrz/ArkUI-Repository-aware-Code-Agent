from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from arkui_agent.repository import (
    RepositoryFileType,
    RepositoryScanner,
    RepositoryWorkspace,
    classify_repository_path,
)
from tests.fixtures import synthetic_cpp_repository


class RepositoryScannerTests(unittest.TestCase):
    def test_recursively_scans_temporary_repository(self) -> None:
        with synthetic_cpp_repository() as repository:
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            paths = scanner.scan()

            self.assertEqual(
                paths,
                tuple(
                    PurePosixPath(path.as_posix())
                    for path in repository.relative_files
                ),
            )
            for path in paths:
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

            paths = scanner.scan()

            self.assertEqual(
                paths,
                tuple(
                    PurePosixPath(path.as_posix())
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

            paths = scanner.scan(
                include_patterns=("src/*",),
                exclude_patterns=("src/internal/*",),
            )

            self.assertEqual(
                paths,
                (PurePosixPath("src/public.cpp"), PurePosixPath("src/widget.cpp")),
            )

    def test_file_type_filter_uses_minimal_generic_classification(self) -> None:
        with synthetic_cpp_repository() as repository:
            readme = repository.root / "README.md"
            readme.write_text("fixture", encoding="utf-8")
            scanner = RepositoryScanner(RepositoryWorkspace(repository.root))

            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.HEADER}),
                (PurePosixPath("include/fixture/widget.h"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.SOURCE}),
                (PurePosixPath("src/widget.cpp"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.TEST}),
                (PurePosixPath("tests/widget_test.cpp"),),
            )
            self.assertEqual(
                scanner.scan(file_types={RepositoryFileType.OTHER}),
                (PurePosixPath("README.md"),),
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
                tuple(sorted(first_scan, key=PurePosixPath.as_posix)),
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

                paths = scanner.scan()

                self.assertNotIn(PurePosixPath("outside-link/outside.cpp"), paths)
                self.assertNotIn(PurePosixPath("outside.cpp"), paths)

    def test_excluded_directories_are_configurable(self) -> None:
        with synthetic_cpp_repository() as repository:
            vendor_source = repository.root / "vendor" / "dependency.cpp"
            vendor_source.parent.mkdir()
            vendor_source.write_text("dependency", encoding="utf-8")
            scanner = RepositoryScanner(
                RepositoryWorkspace(repository.root),
                excluded_directories={"vendor"},
            )

            paths = scanner.scan()

            self.assertNotIn(PurePosixPath("vendor/dependency.cpp"), paths)


if __name__ == "__main__":
    unittest.main()
