from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.codex_stop_validation import (
    CommandResult,
    REPORT_PATH,
    VALIDATION_TIMEOUT_SECONDS,
    changed_test_modules,
    classify_failure,
    run_command,
    stop_response,
    targeted_validation_command,
    test_module_name,
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

    def test_repeated_failure_still_blocks_stop(self) -> None:
        response = stop_response(
            passed=False,
            reason="tests failed",
        )

        self.assertEqual(
            response,
            {"decision": "block", "reason": "tests failed"},
        )

    def test_targeted_command_contains_only_selected_modules(self) -> None:
        command = targeted_validation_command(
            Path("repository"),
            ("tests.unit.test_feature",),
        )

        self.assertEqual(command[-1], "tests.unit.test_feature")
        self.assertNotIn("--require-arkui", command)
        self.assertGreaterEqual(VALIDATION_TIMEOUT_SECONDS, 300)

    def test_only_test_modules_are_selected_from_changed_paths(self) -> None:
        self.assertEqual(
            test_module_name("tests/unit/tooling/test_hook.py"),
            "tests.unit.tooling.test_hook",
        )
        self.assertIsNone(test_module_name("tests/fixtures/hook_cases.py"))
        self.assertIsNone(test_module_name("src/test_hook.py"))

    def test_changed_test_modules_include_tracked_and_untracked_tests(self) -> None:
        results = (
            CommandResult(
                ("git", "diff"),
                0,
                "tests/unit/test_alpha.py\ntests/README.md\n",
            ),
            CommandResult(
                ("git", "ls-files"),
                0,
                "tests/integration/test_beta.py\n",
            ),
        )
        with patch(
            "scripts.codex_stop_validation.run_command",
            side_effect=results,
        ):
            modules, error = changed_test_modules(Path("repository"))

        self.assertIsNone(error)
        self.assertEqual(
            modules,
            ("tests.integration.test_beta", "tests.unit.test_alpha"),
        )

    def test_generated_success_report_is_runtime_data(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            result = CommandResult(("python", "tests"), 0, "ok\n")
            write_report(
                root,
                status="passed",
                started_at="2026-09-07T00:00:00+00:00",
                finished_at="2026-09-07T00:00:01+00:00",
                turn_id="turn-1",
                mode="targeted",
                classification="passed",
                command=result.command,
                returncode=result.returncode,
                output=result.output,
            )

            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["turn_id"], "turn-1")
            self.assertEqual(report["mode"], "targeted")
            self.assertIsNotNone(report["finished_at"])
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

    def test_timeout_has_distinct_status_and_classification(self) -> None:
        result = CommandResult(
            ("python", "tests"),
            124,
            "VALIDATION TIMEOUT after 300s\n",
        )

        self.assertEqual(classify_failure(result), "timeout")

    def test_running_state_is_written_before_timeout_result(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)

            def timeout_after_observing_running(
                command: tuple[str, ...],
                *,
                cwd: Path,
                timeout: int = VALIDATION_TIMEOUT_SECONDS,
            ) -> CommandResult:
                del cwd, timeout
                report = json.loads(
                    (root / REPORT_PATH).read_text(encoding="utf-8")
                )
                self.assertEqual(report["status"], "running")
                self.assertIsNone(report["finished_at"])
                return CommandResult(
                    tuple(command),
                    124,
                    "VALIDATION TIMEOUT after 300s\n",
                )

            with (
                patch(
                    "scripts.codex_stop_validation.run_git_diff_checks",
                    return_value=CommandResult(("git", "diff", "--check"), 0, ""),
                ),
                patch(
                    "scripts.codex_stop_validation.changed_test_modules",
                    return_value=(("tests.unit.test_feature",), None),
                ),
                patch(
                    "scripts.codex_stop_validation.run_command",
                    side_effect=timeout_after_observing_running,
                ),
            ):
                response = validate(root, turn_id="turn-timeout")

            self.assertEqual(response["decision"], "block")
            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "timeout")
            self.assertEqual(report["classification"], "timeout")
            self.assertEqual(report["turn_id"], "turn-timeout")

    def test_validate_blocks_a_nonzero_targeted_test_runner(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (scripts / "run_tests.py").write_text(
                "print('intentional test failure')\nraise SystemExit(7)\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "scripts.codex_stop_validation.run_git_diff_checks",
                    return_value=CommandResult(("git", "diff", "--check"), 0, ""),
                ),
                patch(
                    "scripts.codex_stop_validation.changed_test_modules",
                    return_value=(("tests.unit.test_feature",), None),
                ),
            ):
                response = validate(root, turn_id="turn-failure")

            self.assertEqual(response["decision"], "block")
            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["returncode"], 7)
            self.assertEqual(report["command"][-1], "tests.unit.test_feature")

    def test_no_changed_tests_passes_without_running_test_runner(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            with (
                patch(
                    "scripts.codex_stop_validation.run_git_diff_checks",
                    return_value=CommandResult(("git", "diff", "--check"), 0, ""),
                ),
                patch(
                    "scripts.codex_stop_validation.changed_test_modules",
                    return_value=((), None),
                ),
                patch("scripts.codex_stop_validation.run_command") as runner,
            ):
                response = validate(root, turn_id="turn-no-tests")

            self.assertEqual(response, {})
            runner.assert_not_called()
            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["classification"], "no_targeted_tests")
            self.assertEqual(report["mode"], "targeted")

    def test_probe_records_actual_entry_without_running_test_runner(self) -> None:
        with TemporaryDirectory(prefix="codex-hook-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (scripts / "run_tests.py").write_text(
                "raise SystemExit('probe must not run tests')\n",
                encoding="utf-8",
            )

            response = validate(root, turn_id="turn-probe", probe=True)

            self.assertEqual(response, {})
            report = json.loads((root / REPORT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["classification"], "probe_passed")
            self.assertEqual(report["mode"], "probe")
            self.assertEqual(report["turn_id"], "turn-probe")


if __name__ == "__main__":
    unittest.main()
