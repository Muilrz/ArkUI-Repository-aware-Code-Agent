# Test conventions

Run the complete test suite from the project root:

```powershell
py -3 scripts/run_tests.py
```

On platforms where Python is exposed as `python`, the equivalent command is
`python scripts/run_tests.py`.

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

