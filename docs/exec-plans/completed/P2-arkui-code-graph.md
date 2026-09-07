# P2 — ArkUI Code Graph

- **Phase Status:** Completed
- **Phase Goal:** 在 P1 Repository Intelligence 的通用 C++ facts 上建立可追溯、可查询的 ArkUI framework-aware graph 和 domain traces。
- **Architecture:** [`docs/architecture/code-graph-architecture.md`](../../architecture/code-graph-architecture.md)
- **Specifications:** [`docs/specs/code-graph/`](../../specs/code-graph/README.md)
- **Long-term Source of Truth:** [`docs/architecture/technical-roadmap.md`](../../architecture/technical-roadmap.md)
- **Phase Boundary:** [`docs/exec-plans/phase-map.md`](../phase-map.md)

本文只管理 milestone 的目标、范围、交付物、Acceptance Criteria 和状态。已经实现的 API、identity、relation、evidence 与失败语义由对应 specification 定义；真实 ArkUI source checks 和 expected result 由 `tests/fixtures/` 维护。

## Phase Boundary

P2 消费 P1 的 File/Symbol、Declaration/Definition、Reference、Caller/Callee、Test Fixture/Case 和 Text Search，新增：

- generic Symbol/Test Graph；
- ArkUI Component 和 framework role metadata；
- framework-aware relation；
- Creation、Property、Measure/Layout、Overlay Show/Close trace。

P2 不负责 Task Parser、task-driven graph expansion、Context Ranking/Pack、Agent Runtime、源码修改或 Build/Test/Repair Loop。这些能力属于 P3、P4 和 P5。通用 Lifecycle Trace 当前 deferred。

## Milestone Status

| Milestone | Status | Specification |
| --- | --- | --- |
| P2-A Graph Model & Query Contract | Completed | [Graph model and query](../../specs/code-graph/graph-model-and-query.md) |
| P2-B Symbol/Test Graph Projection | Completed | [Projection and storage](../../specs/code-graph/projection-and-storage.md) |
| P2-C ArkUI Role Mapping | Completed | [Domain role mapping](../../specs/code-graph/domain-role-mapping.md) |
| P2-D Framework Relations | Completed | [Framework relations](../../specs/code-graph/framework-relations.md) |
| P2-E Component Creation Trace | Completed | [Creation trace](../../specs/code-graph/traces/creation.md) |
| P2-F Property Update Trace | Completed | [Property update trace](../../specs/code-graph/traces/property-update.md) |
| P2-G Measure/Layout Trace | Completed | [Measure/layout trace](../../specs/code-graph/traces/measure-layout.md) |
| P2-H Overlay Show/Close Trace | Completed | [Overlay trace](../../specs/code-graph/traces/overlay-show-close.md) |
| P2-I Real ArkUI Validation & P2 Baseline | Completed | 本计划 |

---

# P2-A — Graph Model & Query Contract

- **Status:** Completed

## Goal and Scope

建立统一、storage-independent 的 immutable graph model 和 read-only query contract，供 Symbol Graph、Component Graph、Test Graph、framework relation 和后续 trace 复用。

交付物：`graph/model.py`、`query.py`、`memory.py`，以及 model/query contract tests。

## Non-goals

ArkUI role recognition、framework extraction、domain trace、task-specific expansion、ranking、LLM context 和专用 Graph Database。

## Acceptance Criteria

1. Graph node/edge 使用稳定统一的数据模型。
2. Identity 与 display name 分离。
3. Entity 可追溯到 P1 symbol/file/source range。
4. Edge 保存 relation provenance。
5. Relation dedup 稳定、确定。
6. Query 和 traversal 结果可重复。
7. Contract 不绑定 storage backend。
8. Model/query contract tests 完整通过。

## Completion Evidence

规范见 [Graph model and query](../../specs/code-graph/graph-model-and-query.md)；验证位于 `tests/unit/graph/test_model.py` 和 `test_query.py`。AC 1–8 已通过。

---

# P2-B — Symbol Graph & Test Graph Projection

- **Status:** Completed
- **Dependencies:** P1、P2-A

## Goal and Scope

将 P1 repository facts 投影为可重建的 generic Symbol/Test Graph，并建立 snapshot persistence/query lifecycle。

交付物：`graph/projection.py`、`storage.py`，P1 fixture enumeration 的只读扩展，以及 projection/storage unit 和 synthetic integration tests。

## Non-goals

ArkUI role、CREATE/UPDATE_PROPERTY 等 domain relation 和 task-driven graph expansion。

## Acceptance Criteria

1. Synthetic repository 可生成 Symbol Graph。
2. DECLARE/DEFINE projection 正确。
3. Direct caller/callee 转换为 CALL。
4. Reference 转换为 REFERENCE。
5. TestFixture/TestCase 成为 graph entity。
6. Fixture membership 和 tested-symbol mapping 形成可区分的 TEST relation。
7. Graph 可删除和全量重建。
8. Generated data 不进入 Git。
9. 不通过同名字符串猜 symbol identity。
10. 所有 graph facts 可追溯到 P1 provenance。
11. Unit 和 synthetic integration tests 通过。

## Completion Evidence

规范见 [Projection and storage](../../specs/code-graph/projection-and-storage.md)；验证位于 `test_projection.py`、`test_storage.py` 和 `tests/integration/test_graph_projection.py`。AC 1–11 已通过。

---

# P2-C — ArkUI Component & Framework Role Mapping

- **Status:** Completed
- **Dependencies:** P2-B

## Goal and Scope

在 generic graph 之上，以独立 deterministic metadata 识别 Component、Bridge、Model、Pattern、LayoutProperty、PaintProperty、LayoutAlgorithm 和 shared OverlayManager。Unknown 和 ambiguous decision 必须显式保留。

交付物：`graph/domain.py`、`arkui_rules.py`、role fixtures/unit tests、synthetic 和真实 ArkUI integration smoke。

## Non-goals

Task-based Component 识别、LLM classification、domain traversal、role inheritance/propagation 或修改 P1 identity。

## Acceptance Criteria

1. Synthetic fixture 覆盖主要 framework role。
2. 同一 Component 的已知角色可关联。
3. Role metadata 与 P1 Symbol model 分离。
4. 每个 decision 有 provenance。
5. 无法确定的 symbol 不强制分类。
6. Mapping 稳定、确定。
7. Button/Text/Menu 和 shared OverlayManager 完成真实 smoke。
8. Error、unknown 和 ambiguity tests 完整。

## Completion Evidence

规范见 [Domain role mapping](../../specs/code-graph/domain-role-mapping.md)；具体 expected 在 `tests/fixtures/arkui_role_cases.py`，验证在 `test_domain.py` 和 `test_arkui_role_mapping.py`。AC 1–8 已通过。

---

# P2-D — ArkUI Framework Relation Extraction

- **Status:** Completed
- **Dependencies:** P2-C

## Goal and Scope

在 generic graph 与 role metadata 上提取 CREATE、UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW、CLOSE 和 role-enriched TEST relation，并对当前缺少可靠 P1 fact 的 MOCK 返回 diagnostic。

交付物：`graph/framework.py`、framework fixtures、unit tests、synthetic 和真实 ArkUI smoke。

## Non-goals

完整 C++ data flow、runtime execution、domain trace、task graph expansion，以及通过名称或目录猜 relation。

## Acceptance Criteria

1. Framework relation 使用独立 typed edge。
2. Framework edge 保留底层 semantic evidence。
3. Relation 不仅依赖 class/function 同名。
4. Unsupported/ambiguous relation 不静默伪造。
5. Extractor 可单独测试。
6. Rebuild 后 relation 稳定。
7. Relation provenance 完整。
8. Button/Text/Menu 和 OverlayManager 有真实 smoke validation。

## Completion Evidence

规范见 [Framework relations](../../specs/code-graph/framework-relations.md)；验证位于 `test_framework.py` 和 `test_framework_relations.py`。真实 smoke 覆盖 Button/Text/Menu 及 OverlayManager，AC 1–8 已通过。

---

# P2-E — Component Creation Trace

- **Status:** Completed
- **Dependencies:** P2-D

## Goal and Scope

从显式 entry seed 恢复有界、可追溯的 Entry/Bridge → Model → FrameNode 以及 Pattern argument association。缺事实返回 incomplete，多候选返回 ambiguous。

交付物：`graph/creation.py`、creation fixtures、unit tests、synthetic 和真实 Button/Text/Menu smoke。

## Non-goals

Runtime node creation、任意 callback/data-flow 分析、Task Context Builder 或 LLM 推理。

## Acceptance Criteria

1. Synthetic fixture 可生成完整 creation trace。
2. Trace 顺序稳定。
3. 每一步可追溯 source location。
4. 缺 relation 时返回 incomplete。
5. 多候选不静默选择。
6. Button/Text/Menu 有真实 validation。
7. Query 不依赖 LLM。

## Completion Evidence

规范见 [Creation trace](../../specs/code-graph/traces/creation.md)；冻结 expected 在 `tests/fixtures/creation_cases.py`。真实 validation 中 Button/Text complete，Menu 在 InnerMenuPattern/callback evidence 边界保持 incomplete。AC 1–7 已通过。

---

# P2-F — Property Update Trace

- **Status:** Completed
- **Dependencies:** P2-D

## Goal and Scope

从显式 entry/setter identity 恢复 Model property update，以及证据充分时的 writer/state/reader/consumer 静态关联。LayoutProperty 与 PaintProperty 分开表达。

交付物：`graph/property.py`、property fixtures、unit tests、synthetic 和真实 Button/Text/Menu smoke。

## Non-goals

完整运行时 property flow、宏展开 backend、任意 getter 匹配、Task Context Builder 或 LLM 推理。

## Acceptance Criteria

1. Synthetic fixture 可产生完整 update trace。
2. LayoutProperty 与 PaintProperty 可区分。
3. Setter 不通过纯字符串同名推断。
4. Trace 保存 source provenance。
5. Ambiguity 显式返回。
6. Button/Text/Menu 选取真实 property validation。
7. 重复运行结果稳定。

## Completion Evidence

规范见 [Property update trace](../../specs/code-graph/traces/property-update.md)；冻结 expected 在 `tests/fixtures/property_cases.py`。真实 FontWeight cases 保留 NODE macro 和显式 field writer 能力边界。AC 1–7 已通过。

---

# P2-G — Measure / Layout Trace

- **Status:** Completed
- **Dependencies:** P2-D

## Goal and Scope

从显式 Pattern identity 恢复 CreateLayoutAlgorithm、LayoutAlgorithm、Measure/MeasureContent、Layout 和 LayoutProperty dependency。Measure 与 Layout 保持独立 relation。

交付物：`graph/layout.py`、layout fixtures、unit tests、synthetic 和真实 ArkUI smoke。

## Non-goals

Layout runtime execution、inheritance/virtual dispatch 推断、rendering、performance profiling 或 Task Context Builder。

## Acceptance Criteria

1. Synthetic fixture 可产生 Measure/Layout trace。
2. Factory → LayoutAlgorithm relation 正确。
3. Measure/Layout 可明确区分。
4. 有可靠 evidence 时 LayoutProperty dependency 可进入 trace。
5. 每个节点和 relation 有 provenance。
6. Incomplete chain 可明确报告。
7. 至少一个真实 LayoutAlgorithm component 完成 validation。

## Completion Evidence

规范见 [Measure/layout trace](../../specs/code-graph/traces/measure-layout.md)；冻结 expected 在 `tests/fixtures/layout_cases.py`。真实结果包括 Button partial pipeline、Text unsupported factory 和 Menu 多 algorithm ambiguity。AC 1–7 已通过。

---

# P2-H — Overlay Show / Close Trace

- **Status:** Completed
- **Dependencies:** P2-D

## Goal and Scope

从显式 Show/Close entry identities 恢复各自的 P1 CALL path、OverlayManager operation binding、managed node type，以及证据充分时的 Pattern 和 direct animation association。多个 Close path 全部保留。

交付物：`graph/overlay.py`、overlay fixtures、unit tests、synthetic 和真实 Menu smoke。

## Non-goals

通用 Lifecycle Trace、runtime instance flow、animation simulation、Dialog operation 扩展、P3 task-driven expansion 或 Agent reasoning。

## Acceptance Criteria

1. Synthetic fixture 可建立 Show/Close trace。
2. SHOW/CLOSE 是显式 domain binding，且与 CALL 区分。
3. OverlayManager 使用已有 framework identity。
4. Show/Close provenance 完整。
5. 缺 animation evidence 时不创建 animation node。
6. 至少一个真实 overlay 场景完成 validation。
7. 多条 Close path 可明确表达。

## Completion Evidence

规范见 [Overlay trace](../../specs/code-graph/traces/overlay-show-close.md)；冻结 expected 在 `tests/fixtures/overlay_cases.py`。真实 Menu Show 为 incomplete；两个 Close entry 均保留，Close 和总 trace 为 ambiguous；未解析 modifier dispatch 后的 animation 保持 unresolved。AC 1–7 已通过。

---

# P2-I — Real ArkUI Graph Validation & P2 Baseline

- **Status:** Completed
- **Dependencies:** P2-E、P2-F、P2-G、P2-H

## Goal

在外部只读 ArkUI Ace Engine repository 上统一验收 P2，并为 P3 Graph Expansion 和后续 Evaluation 建立可重复 baseline。

## Scope

- 统一运行 Symbol Graph、Component Graph、Test Graph 和 Framework Relation validation。
- 统一运行 Creation、Property Update、Measure/Layout、Overlay Show/Close 真实 cases。
- 至少覆盖 Button、Text、Menu；按 trace 需要选择 Dialog、Tabs、List 等真实适用组件。
- 汇总 expected node/relation、missing node/edge、incorrect edge、ambiguity、trace completeness、Call Chain Accuracy、latency 和 failure category。
- Expected 必须在 query 前经源码确认，不能根据 actual output 反填。

## Non-goals

P3 task-driven expansion、Context Pack、Agent runtime、源码修改、Build/Repair，以及为了提高完整率伪造缺失 relation。

## Deliverables

- 统一 P2 real-repository validation harness/baseline command。
- 人工冻结且 revision-bound 的 expected dataset。
- 可重建的 ignored evaluation report。
- P2 failure taxonomy 和初始 Call Chain Accuracy。
- P2 Definition of Done 对照。

## Acceptance Criteria

1. 使用外部只读 ArkUI repository。
2. Graph derived data 不进入 Git。
3. 至少 3 个代表性组件进入 validation suite。
4. 四类 domain trace 均有真实 repository case。
5. Expected trace 经人工源码确认并在 query 前冻结。
6. Graph relation 可追溯到底层 source evidence。
7. 记录失败/incomplete/ambiguous case。
8. Baseline command 可重复执行。
9. Call Chain Accuracy 可统计。
10. P2 Definition of Done 全部满足。

## Tests / Validation

开发时运行 P2-I targeted unit/integration；定稿后配置 `ARKUI_REPO_ROOT` 执行一次严格全量：

```powershell
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
```

如最终全量启动后修改代码、测试或 validation config，必须重新执行。运行报告属于 ignored runtime/evaluation data，不提交 index、graph snapshot、target-derived data 或逐命令日志。

## Completion Evidence

统一 command、dataset、指标与 failure taxonomy 见 [P2 baseline](../../evaluation/p2-code-graph-baseline.md)。revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885` 的真实运行 18/18 case 符合冻结 expected；relation coverage 为 64/83，Call Chain Accuracy 为 2/14，19 条 missing relation、0 条 incorrect relation，所有 case provenance 验证通过。最终 strict full 运行 318 tests，全部通过。

---

# P2 Definition of Done

只有 P2-A 至 P2-I 全部 Completed，P2 才能标记 Completed。完成后系统应形成：

```text
P1 Repository Intelligence
        ↓
Generic C++ Facts / Symbol & Test Graph
        ↓
ArkUI Role Mapping / Framework Relations
        ↓
Creation | Property | Measure/Layout | Overlay Traces
```

并满足 phase-map 中 P2 的全部要求。Natural Language Task → Task Parser → task-driven Graph Expansion → Context Ranking/Pack 属于 P3。

## Deferred Capability

长期路线中的 Create → Attach → Modify → Layout → Detach 通用 Lifecycle Trace 不属于当前 P2 Definition of Done。若后续单独实现，应建立新的 milestone 和 specification，不扩张现有 Overlay Trace。

## Phase Completion Evidence

P2-A～P2-I 均已 Completed。P2-I 对 Symbol/Component/Test Graph、Framework Relations 与四类 domain trace 完成统一真实 ArkUI baseline；phase-map P2 Definition of Done 的 provenance、generic/domain relation separation、bounded local expansion、人工 trace baseline 与初始 Call Chain Accuracy 均已有实现和验证。P3 尚未开始。
