# Test conventions

Run the complete test suite from the project root:

```powershell
py -3 scripts/run_tests.py
```

On platforms where Python is exposed as `python`, the equivalent command is
`python scripts/run_tests.py`.

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

## Codex validation hook

The repository-level `.codex/hooks.json` runs
`scripts/codex_stop_validation.py` before Codex stops. The hook executes the
fixed project validation; it does not replace milestone-focused tests or decide
that acceptance criteria are satisfied. Successful and failed reports under
`var/validation/` are generated runtime data and may be deleted at any time.
They are ignored by Git and are not application inputs.

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
