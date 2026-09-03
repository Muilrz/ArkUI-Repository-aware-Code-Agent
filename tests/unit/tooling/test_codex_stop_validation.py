from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.codex_stop_validation import (
    CommandResult,
    REPORT_PATH,
    classify_failure,
    run_command,
    stop_response,
    validate,
    write_report,
)


class CodexStopValidationTests(unittest.TestCase):
    def test_nonzero_command_is_preserved(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            result = run_command(
                (
                    sys.executable,
                    "-c",
                    "import sys; print('real failure'); raise SystemExit(7)",
                ),
                cwd=Path(temporary),
            )

        self.assertEqual(result.returncode, 7)
        self.assertIn("real failure", result.output)

    def test_failure_response_blocks_first_stop(self) -> None:
        self.assertEqual(
            stop_response(passed=False, reason="tests failed"),
            {"decision": "block", "reason": "tests failed"},
        )

    def test_repeated_failure_stops_with_visible_failure(self) -> None:
        response = stop_response(
            passed=False,
            reason="tests failed",
            already_continued=True,
        )

        self.assertFalse(response["continue"])
        self.assertEqual(response["stopReason"], "tests failed")
        self.assertEqual(response["systemMessage"], "tests failed")

    def test_generated_success_report_is_runtime_data(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            result = CommandResult(("python", "tests"), 0, "ok\n")
            write_report(
                root,
                status="passed",
                classification="passed",
                result=result,
            )

            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["returncode"], 0)
            self.assertTrue((root / "var/validation/latest.log").is_file())

    def test_missing_external_environment_is_classified_separately(self) -> None:
        result = CommandResult(
            ("python", "tests"),
            2,
            "EXTERNAL REQUIREMENT MISSING: ARKUI_REPO_ROOT\n",
        )

        self.assertEqual(classify_failure(result), "external_environment_missing")

    def test_missing_clangd_skip_is_external_environment_failure(self) -> None:
        result = CommandResult(
            ("python", "tests"),
            1,
            "SKIPPED test: clangd integration unavailable: executable not found\n",
        )

        self.assertEqual(classify_failure(result), "external_environment_missing")

    def test_validate_blocks_a_real_nonzero_test_runner(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (scripts / "run_tests.py").write_text(
                "print('intentional test failure')\nraise SystemExit(7)\n",
                encoding="utf-8",
            )
            initialized = run_command(("git", "init", "--quiet"), cwd=root)
            self.assertEqual(initialized.returncode, 0, initialized.output)

            response = validate(root, already_continued=False)

            self.assertEqual(response["decision"], "block")
            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["returncode"], 7)


if __name__ == "__main__":
    unittest.main()
