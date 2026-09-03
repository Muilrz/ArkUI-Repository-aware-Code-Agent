# P1 Retrieval Baseline Harness

P1-I1 provides a repeatable harness; it does not contain the formal ArkUI
component benchmark. Expected answers are static, human-authored JSON and are
never inferred from retrieval output.

## Case model

Each suite records `repository_revision` and one or more cases. Every case has:

- a unique `id`;
- one typed `query`;
- an `expected` object whose present fields are the annotated dimensions;
- an `annotation` with a non-empty human `annotator` and `rationale`.

Omitting an expected dimension means “not evaluated.” Providing an empty array
means “human-confirmed empty result.” Expected symbols and relation endpoints
always require both the backend/persistence identity and qualified name. The
harness considers a symbol correct only when both values agree.

```json
{
  "schema_version": 1,
  "suite_id": "controlled-example",
  "repository": "synthetic-cpp",
  "repository_revision": "fixture-v1",
  "cases": [
    {
      "id": "widget-value-symbol",
      "query": {
        "kind": "search_symbol",
        "name": "fixture::Widget::value",
        "match": "qualified_name"
      },
      "expected": {
        "files": ["include/fixture/widget.h"],
        "symbols": [
          {
            "identity": "opaque:widget-value",
            "qualified_name": "fixture::Widget::value"
          }
        ]
      },
      "annotation": {
        "annotator": "human-reviewer",
        "rationale": "Declaration and identity checked against fixture source."
      }
    }
  ]
}
```

Supported kinds are `text_search`, `search_symbol`, `find_declaration`,
`find_definition`, `find_references`, `find_callers`, `find_callees`, and
`find_tests`. Identity-based queries use a `symbol` object with `identity` and
`qualified_name`; the P1 adapter rejects disagreement with the index instead of
falling back to same-name text matching.

## Metrics

- **Target File Recall** = distinct annotated files returned / distinct
  annotated files. It is not applicable when `files` is omitted, and equals
  `1.0` for a human-annotated empty set that is returned empty.
- **Target Symbol Recall** uses the same formula over exact
  `(identity, qualified_name)` pairs.
- **Recall@K** is calculated only for `search_symbol`: distinct annotated exact
  symbols in the first K ranked symbols / all distinct annotated symbols.
- **MRR** is calculated only for `search_symbol`: reciprocal rank of the first
  exact annotated symbol, or `0.0` when none is returned.
- **Direct Relation Correctness** is calculated when `relations` is present and
  is true only when the returned direct caller/callee edge set exactly equals
  the annotation. It is a P1 direct-edge check, not the P2 domain call-chain
  metric.
- **Target Test Recall** applies the recall formula to exact
  `(identity, display_name, file)` test records.
- **Latency** surrounds each executor call with `perf_counter_ns` and is
  reported in milliseconds per case and as a suite mean. It excludes case-file
  parsing and report serialization.

Suite metrics are unweighted macro means over cases where a metric applies.

## Failure taxonomy

Operational failures are `query_rejected`, `backend_unavailable`,
`backend_failure`, `index_failure`, and `unexpected_error`. Result-analysis
failures are `empty_result`, `target_file_miss`, `target_symbol_miss`,
`target_test_miss`, `symbol_identity_mismatch`, `unexpected_file`,
`unexpected_symbol`, `unexpected_test`, `direct_relation_miss`, and
`unexpected_direct_relation`. The three `unexpected_*` result categories for
files/symbols/tests apply to human-annotated empty sets; non-empty candidate
annotations are recall-oriented and may return additional candidates. A case
may retain multiple result-analysis categories.

## Entry point and generated data

The formal real-repository path validates the checkout revision before doing
any preparation or retrieval. It uses the checked-in preparation manifest to
select repository-relative files, then reuses `RepositoryScanner`,
`ClangdSemanticProvider`, `RepositoryTestDiscoverer`, `SymbolIndex`, and the P1
retrieval facades. The preparation code reads query targets but never reads
expected results when building the index.

Run the pinned Button/Text/Menu suite from the project root:

```powershell
py -3 scripts/run_retrieval_baseline.py `
  --cases benchmarks/p1/arkui-button-text-menu.json `
  --preparation benchmarks/p1/arkui-button-text-menu.preparation.json `
  --repository-root $env:ARKUI_REPO_ROOT `
  --index var/evaluation/arkui-p1-symbol-index.sqlite3 `
  --output var/evaluation/arkui-button-text-menu-baseline.json
```

With `--preparation`, Git revision mismatch is a setup failure and no benchmark
queries run. The report records the actual revision plus clangd and ripgrep
version strings without recording executable or repository absolute paths.

For a prebuilt generated index, omit `--preparation`; this lower-level mode is
useful for controlled harness tests and does not claim checkout validation.

The default report is `var/evaluation/p1-retrieval-baseline.json`. `var/`, P1
indexes, compile databases, and target-repository-derived data remain generated
and Git-ignored. A different report location may be supplied with `--output`.
