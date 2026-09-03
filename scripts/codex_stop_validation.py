"""Execute the repository's fixed validation gate for a Codex Stop hook."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPORT_SCHEMA_VERSION = 1
VALIDATION_TIMEOUT_SECONDS = 540
REPORT_PATH = Path("var/validation/latest.json")
LOG_PATH = Path("var/validation/latest.log")


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    schema_version: int
    status: str
    checked_at: str
    classification: str
    command: tuple[str, ...]
    returncode: int
    log_path: str


def project_root_from(start: Path) -> Path:
    candidate = start.resolve()
    for directory in (candidate, *candidate.parents):
        if (
            (directory / "pyproject.toml").is_file()
            and (directory / "scripts/run_tests.py").is_file()
        ):
            return directory
    raise RuntimeError(f"repository root not found from {candidate}")


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int = VALIDATION_TIMEOUT_SECONDS,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        return CommandResult(tuple(command), 127, f"TOOLING MISSING: {error}\n")
    except subprocess.TimeoutExpired as error:
        output = error.stdout if isinstance(error.stdout, str) else ""
        return CommandResult(
            tuple(command),
            124,
            f"VALIDATION TIMEOUT after {timeout}s\n{output}",
        )
    return CommandResult(tuple(command), completed.returncode, completed.stdout)


def run_git_diff_checks(project_root: Path) -> CommandResult:
    outputs: list[str] = []
    commands = (
        ("git", "diff", "--check"),
        ("git", "diff", "--cached", "--check"),
    )
    for command in commands:
        result = run_command(command, cwd=project_root, timeout=30)
        outputs.append(result.output)
        if result.returncode != 0:
            return CommandResult(result.command, result.returncode, "".join(outputs))
    return CommandResult(commands[0], 0, "".join(outputs))


def classify_failure(result: CommandResult) -> str:
    output = result.output
    external_markers = (
        "EXTERNAL REQUIREMENT MISSING:",
        "TOOLING MISSING:",
        "integration unavailable:",
        "ARKUI_REPO_ROOT is not configured",
    )
    if any(marker in output for marker in external_markers):
        return "external_environment_missing"
    if "ResourceWarning" in output or "RESOURCE WARNING:" in output:
        return "resource_warning"
    if "SKIPPED " in output or "skipped tests are not accepted" in output:
        return "skipped_test"
    if result.returncode == 124:
        return "timeout"
    return "command_failed"


def write_report(
    project_root: Path,
    *,
    status: str,
    classification: str,
    result: CommandResult,
) -> None:
    report_path = project_root / REPORT_PATH
    log_path = project_root / LOG_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.output, encoding="utf-8")
    report = ValidationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        status=status,
        checked_at=datetime.now(UTC).isoformat(),
        classification=classification,
        command=result.command,
        returncode=result.returncode,
        log_path=LOG_PATH.as_posix(),
    )
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def failure_reason(classification: str, result: CommandResult) -> str:
    meaningful_lines = [
        line.strip() for line in result.output.splitlines() if line.strip()
    ]
    tail = "\n".join(meaningful_lines[-12:])
    reason = (
        f"Repository validation failed ({classification}, exit {result.returncode}). "
        f"Full output: {LOG_PATH.as_posix()}."
    )
    if tail:
        reason = f"{reason}\n{tail}"
    return reason


def stop_response(
    *,
    passed: bool,
    reason: str = "",
    already_continued: bool = False,
) -> dict[str, Any]:
    if passed:
        return {}
    if already_continued:
        return {
            "continue": False,
            "stopReason": reason,
            "systemMessage": reason,
        }
    return {"decision": "block", "reason": reason}


def validate(project_root: Path, *, already_continued: bool) -> dict[str, Any]:
    diff_result = run_git_diff_checks(project_root)
    if diff_result.returncode != 0:
        classification = classify_failure(diff_result)
        write_report(
            project_root,
            status="failed",
            classification=classification,
            result=diff_result,
        )
        return stop_response(
            passed=False,
            reason=failure_reason(classification, diff_result),
            already_continued=already_continued,
        )

    command = (
        sys.executable,
        "-W",
        "error::ResourceWarning",
        str(project_root / "scripts/run_tests.py"),
    )
    result = run_command(command, cwd=project_root)
    status = "passed" if result.returncode == 0 else "failed"
    classification = "passed" if result.returncode == 0 else classify_failure(result)
    write_report(
        project_root,
        status=status,
        classification=classification,
        result=result,
    )
    if result.returncode == 0:
        return stop_response(passed=True)
    return stop_response(
        passed=False,
        reason=failure_reason(classification, result),
        already_continued=already_continued,
    )


def load_hook_input(stream: Any) -> Mapping[str, Any]:
    payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("codex_stop_validation.py only accepts Stop events")
    return payload


def main() -> int:
    try:
        hook_input = load_hook_input(sys.stdin)
        start = Path(str(hook_input.get("cwd") or Path.cwd()))
        project_root = project_root_from(start)
        response = validate(
            project_root,
            already_continued=bool(hook_input.get("stop_hook_active")),
        )
    except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as error:
        response = stop_response(
            passed=False,
            reason=f"Repository validation hook failed: {type(error).__name__}: {error}",
        )
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
