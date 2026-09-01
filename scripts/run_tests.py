"""Run the complete project test suite with only the Python standard library."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    tests_root = project_root / "tests"

    sys.path.insert(0, str(source_root))
    existing_python_path = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(source_root), existing_python_path) if part
    )

    suite = unittest.defaultTestLoader.discover(
        start_dir=str(tests_root),
        pattern="test_*.py",
        top_level_dir=str(project_root),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

