# P2 Real ArkUI Code Graph Baseline

P2-I 统一复用 P1 formal benchmark 与 P2-C～P2-H 的 revision-bound frozen fixtures，对外部只读 ArkUI Ace Engine checkout 运行 Symbol Graph、Component Graph、Test Graph、Framework Relations 和四类 domain trace。它不新增 relation/trace 推断能力。

## Dataset

统一 suite 由 `tests/fixtures/p2_baseline_cases.py` 组合，固定到 ArkUI revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。它引用而不复制以下 expected 来源：

- `benchmarks/p1/arkui-button-text-menu.json`：Symbol/Test Graph 的 declaration、definition、CALL 和 TEST identity；
- `tests/fixtures/arkui_role_cases.py`：Button、Text、Menu 与 shared OverlayManager role；
- `tests/fixtures/creation_cases.py`；
- `tests/fixtures/property_cases.py`；
- `tests/fixtures/layout_cases.py`；
- `tests/fixtures/overlay_cases.py`。

各 P2 fixture 的 source fragment/line anchor 在 graph query 前检查。Repository revision 在任何 source check、index preparation 或 query 前校验。revision 或 source anchor 变化时 baseline 失败，必须重新人工审查 expected；不能从 actual output 反填。

suite 共 18 个 case：4 个 graph/framework 聚合 case和 14 个 trace case。覆盖 Button、Text、Menu、shared OverlayManager，以及 Creation、Property Update、Measure/Layout、Overlay Show/Close。

## Metrics

每个 case 区分：

- `present_relations`：当前能力应观察到的冻结 relation；
- `known_missing_relations`：源码审查确认属于目标 chain、但当前受静态能力边界限制而缺失的 relation；
- `incorrect_relations`：actual 中未标注的 relation；
- `status`、`gaps`、`unresolved`、`path_count`、`exhaustive` 与 `provenance_valid`。

**Relation Coverage**：

```text
observed desired relation count
───────────────────────────────
present + known-missing desired relation count
```

因此 expected missing relation 会保留在分母中，不会因 fixture 如实记录 `incomplete` 而消失。

**Expected Conformance** 表示 actual 精确符合当前 revision-bound 预期，包括已知的 `incomplete`、`ambiguous`、gap 和 unresolved。它用于发现回归，不表示 chain 已完整恢复。

**Call Chain Accuracy** 是 14 个 trace case 的严格宏平均。一个 trace case 仅在以下条件全部满足时记 `1`，否则记 `0`：

1. status 为 `complete`；
2. 只有一条 path；
3. traversal exhaustive；
4. ordered relation/path 与 frozen expected 精确一致；
5. provenance 完整；
6. 没有 missing/incorrect relation、gap 或 unresolved state。

所以 `incomplete`、`ambiguous`、truncated 和 animation `unresolved` 不会被局部 relation 命中率隐藏。Expected Conformance 与 Call Chain Accuracy 必须同时报告。

## Failure and limitation taxonomy

回归 failure category 包括：

- `missing_observation` / `unexpected_observation`；
- `status_mismatch`；
- `missing_expected_relation` / `incorrect_relation` / `relation_order_mismatch`；
- `known_missing_relation_observed`（能力变化后要求人工 re-review，而不是自动改 expected）；
- `gap_mismatch` / `unresolved_mismatch`；
- `path_count_mismatch` / `exhaustive_mismatch`；
- `provenance_missing`。

已冻结且 actual 如实复现的 gap/unresolved 不算 regression failure，但仍按 `gap_counts`、`unresolved_counts`、status distribution 和 missing relation 报告为 capability limitation。

## Latency and provenance

P2 stage latency 包含对应真实 validation 的 P1 semantic collection、临时 index/graph 构建、query 和断言；不只计最后一个 trace 函数。报告给出各 stage 与总 wall-clock latency。P1 index、graph snapshot 和 report 都是 ignored、可重建 runtime data。

provenance validation 检查 graph node anchor、edge evidence、role source hash，以及 trace node/binding/support/source evidence。target source 在运行前后由已有 P2 real fixtures 进行 SHA-256 一致性检查。

## Command

在项目根目录运行：

```powershell
py -3 scripts/run_p2_baseline.py `
  --repository-root $env:ARKUI_REPO_ROOT `
  --output var/evaluation/p2-arkui-baseline.json
```

也可省略 `--repository-root` 并直接使用 `ARKUI_REPO_ROOT`。生成 report 不进入 Git；命令在 expected conformance regression 时返回非零。

## Initial baseline

在 revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885` 上的 P2-I 初始结果：

- expected conformance：18/18；regression failure：0；
- relation coverage：64/83（`0.7711`）；missing relation：19；incorrect relation：0；
- Call Chain Accuracy：2/14（`0.1429`）；
- 全 suite status：complete 5、incomplete 11、ambiguous 2；其中 14 个 trace case 为 complete 2、incomplete 10、ambiguous 2；
- provenance：18/18 case 通过；
- unresolved：Overlay Show/Close animation 各 1，共 2；
- 总 stage latency：`480304.0637 ms`。

各 stage latency：Symbol/Test Graph `42046.0335 ms`、Component Graph `52611.2789 ms`、Framework Relations `71412.6433 ms`、Creation `93508.8065 ms`、Property Update `94735.2271 ms`、Measure/Layout `79953.6490 ms`、Overlay `46036.4254 ms`。

初始 gap taxonomy：`missing_test_mapping` 1、`missing_pattern_stage` 1、`unsupported_pattern_callback` 1、`missing_update_binding` 3、`missing_entry_call` 3、`missing_property_writer` 3、`missing_layout_binding` 1、`unsupported_factory_body` 1、`ambiguous_algorithm_identity` 1、`missing_create_binding` 1、`unsupported_manager_body` 2。这里的计数按 case-level normalized gap 统计；Overlay Close 的两个 candidate 保存在 case detail 中，但共享一个 gap category occurrence。
