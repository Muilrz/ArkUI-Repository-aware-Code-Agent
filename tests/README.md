# Test conventions

Codex does not proactively run test commands while implementing a change.
Behavior changes must still add or update their directly relevant tests. The
trusted Stop Hook selects changed and added `test_*.py` files from the Git
working tree and runs only those tests through the strict runner.

The Hook command is equivalent to:

```powershell
py -3 -W error::ResourceWarning scripts/run_tests.py <changed-test-modules>
```

If no test module changed, the Hook records `no_targeted_tests` and does not fall
back to the full suite. A changed targeted test that cannot run because an
external requirement is missing fails validation instead of being silently
omitted.

Strict full validation, real ArkUI baselines, and other expensive validation are
manual operations initiated explicitly by the user. The P2 baseline command is:

```powershell
py -3 scripts/run_p2_baseline.py `
  --repository-root $env:ARKUI_REPO_ROOT `
  --output var/evaluation/p2-arkui-baseline.json
```

Do not run that baseline automatically. Optimizing its current
prepare-once/evaluate-many behavior is deferred to a separate task.

The manual strict full command is:

```powershell
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
```

The Stop Hook never runs this command. If the Hook is unavailable or untrusted,
Codex reports that the change is unvalidated rather than automatically replacing
it with a full run.

The runner is strict: a non-zero test result, skipped test, expected failure,
zero-test run, or `ResourceWarning` fails validation. Real-ArkUI smoke tests are
selected automatically when `ARKUI_REPO_ROOT` is configured. When a milestone
requires them, make the requirement explicit:

```powershell
py -3 scripts/run_tests.py --require-arkui
```

If the required repository is not configured, this command exits non-zero and
reports `EXTERNAL REQUIREMENT MISSING`; it never converts the missing environment
into a passing test.

The P2 command reuses the frozen P1/P2 fixtures and writes only ignored,
rebuildable evaluation output.

## Codex validation hook

The repository-level `.codex/hooks.json` runs
`scripts/codex_stop_validation.py` before Codex stops. The Hook runs only changed
or added test modules and blocks on their failure. It does not execute full or
milestone-wide validation or decide that acceptance criteria are satisfied.
`var/validation/latest.json`
records `running`, `passed`, `failed`, or `timeout`, its Stop turn id, and whether
the run was a probe or targeted validation. A missing, stale, or different turn id
means the expected Hook did not trigger. The single rotating JSON report and log
are ignored, rebuildable runtime data.

The hook never commits or pushes changes. New or changed project hooks must be
reviewed and trusted in Codex before they run.

## Test boundaries

- `tests/unit/` contains fast, deterministic tests for one module or contract.
  Unit tests must not require a real ArkUI repository, network access, or an
  external compiler/toolchain.
- `tests/integration/` contains tests spanning adapters, external tools, or an
  explicitly configured target repository. Such dependencies must be stated by
  the test and must never be inferred from a developer-specific path.
- `tests/fixtures/` contains reusable fixture helpers and small checked-in
  inputs. Generated copies belong in temporary directories, not in this tree.

Tests must isolate generated files with `tempfile` facilities. Persistent
runtime output belongs under the ignored `var/` directory and must not be
committed.
