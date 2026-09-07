"""Run changed or added tests for the repository's Codex Stop hook."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPORT_SCHEMA_VERSION = 3
VALIDATION_TIMEOUT_SECONDS = 300
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
    started_at: str
    finished_at: str | None
    turn_id: str
    mode: str
    classification: str
    command: tuple[str, ...]
    returncode: int | None
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
    if result.returncode == 124:
        return "timeout"
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
    return "command_failed"


def write_report(
    project_root: Path,
    *,
    status: str,
    started_at: str,
    finished_at: str | None,
    turn_id: str,
    mode: str,
    classification: str,
    command: Sequence[str],
    returncode: int | None,
    output: str,
) -> None:
    report_path = project_root / REPORT_PATH
    log_path = project_root / LOG_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    report = ValidationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        status=status,
        checked_at=datetime.now(UTC).isoformat(),
        started_at=started_at,
        finished_at=finished_at,
        turn_id=turn_id,
        mode=mode,
        classification=classification,
        command=tuple(command),
        returncode=returncode,
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
) -> dict[str, Any]:
    if passed:
        return {}
    return {"decision": "block", "reason": reason}


def test_module_name(path: str) -> str | None:
    normalized = path.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.suffix != ".py" or not candidate.name.startswith("test_"):
        return None
    if not candidate.parts or candidate.parts[0] != "tests":
        return None
    return ".".join(candidate.with_suffix("").parts)


def changed_test_modules(
    project_root: Path,
) -> tuple[tuple[str, ...], CommandResult | None]:
    commands = (
        (
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "HEAD",
            "--",
            "tests",
        ),
        ("git", "ls-files", "--others", "--exclude-standard", "--", "tests"),
    )
    modules: set[str] = set()
    for command in commands:
        result = run_command(command, cwd=project_root, timeout=30)
        if result.returncode != 0:
            return (), result
        for path in result.output.splitlines():
            module = test_module_name(path)
            if module is not None:
                modules.add(module)
    return tuple(sorted(modules)), None


def targeted_validation_command(
    project_root: Path,
    test_modules: Sequence[str],
) -> tuple[str, ...]:
    return (
        sys.executable,
        "-W",
        "error::ResourceWarning",
        str(project_root / "scripts/run_tests.py"),
        *test_modules,
    )


def validate(
    project_root: Path,
    *,
    turn_id: str,
    probe: bool = False,
) -> dict[str, Any]:
    mode = "probe" if probe else "targeted"
    command = ("stop-hook-probe",) if probe else ("select-changed-tests",)
    started_at = datetime.now(UTC).isoformat()
    write_report(
        project_root,
        status="running",
        started_at=started_at,
        finished_at=None,
        turn_id=turn_id,
        mode=mode,
        classification="running",
        command=command,
        returncode=None,
        output="",
    )

    if probe:
        output = "Stop Hook probe reached the repository validation entry point.\n"
        write_report(
            project_root,
            status="passed",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            turn_id=turn_id,
            mode=mode,
            classification="probe_passed",
            command=command,
            returncode=0,
            output=output,
        )
        return stop_response(passed=True)

    diff_result = run_git_diff_checks(project_root)
    if diff_result.returncode != 0:
        classification = classify_failure(diff_result)
        write_report(
            project_root,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            turn_id=turn_id,
            mode=mode,
            classification=classification,
            command=diff_result.command,
            returncode=diff_result.returncode,
            output=diff_result.output,
        )
        return stop_response(
            passed=False,
            reason=failure_reason(classification, diff_result),
        )

    test_modules, selection_error = changed_test_modules(project_root)
    if selection_error is not None:
        classification = classify_failure(selection_error)
        write_report(
            project_root,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            turn_id=turn_id,
            mode=mode,
            classification=classification,
            command=selection_error.command,
            returncode=selection_error.returncode,
            output=selection_error.output,
        )
        return stop_response(
            passed=False,
            reason=failure_reason(classification, selection_error),
        )

    if not test_modules:
        write_report(
            project_root,
            status="passed",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            turn_id=turn_id,
            mode=mode,
            classification="no_targeted_tests",
            command=(),
            returncode=0,
            output="No changed or added test_*.py files; no tests were run.\n",
        )
        return stop_response(passed=True)

    command = targeted_validation_command(project_root, test_modules)
    result = run_command(command, cwd=project_root)
    status = (
        "passed"
        if result.returncode == 0
        else "timeout"
        if result.returncode == 124
        else "failed"
    )
    classification = "passed" if result.returncode == 0 else classify_failure(result)
    write_report(
        project_root,
        status=status,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
        turn_id=turn_id,
        mode=mode,
        classification=classification,
        command=result.command,
        returncode=result.returncode,
        output=result.output,
    )
    if result.returncode == 0:
        return stop_response(passed=True)
    return stop_response(
        passed=False,
        reason=failure_reason(classification, result),
    )


def load_hook_input(stream: Any) -> Mapping[str, Any]:
    payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("codex_stop_validation.py only accepts Stop events")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="record a lightweight Stop-event probe without running validation",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        hook_input = load_hook_input(sys.stdin)
        start = Path(str(hook_input.get("cwd") or Path.cwd()))
        project_root = project_root_from(start)
        response = validate(
            project_root,
            turn_id=str(hook_input.get("turn_id") or "unknown"),
            probe=args.probe,
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
