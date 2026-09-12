# P3 — Task / Change Retrieval & Context Builder (Superseded)

- **Phase Status:** Superseded
- **Status when superseded:** P3-A～E Completed；P3-F1 In Progress；F2～F6/G/H/I Not Started
- **Superseded by:** [ADR-0005](../../decisions/ADR-0005-code-review-service-pivot.md) and the [R0–R6 phase map](../phase-map.md)
- **Historical Phase Goal:** 在 P1/P2 之上建立 dependency-driven incremental Repository Knowledge lifecycle，并将自然语言/结构化 Task 或平台无关 Change 转换为版本可追溯、证据充分且满足 token budget 的结构化 Context Pack。
- **Current Source of Truth:** [Technical roadmap](../../architecture/technical-roadmap.md)
- **Historical Phase Boundary:** [Phase map historical phases](../phase-map.md#3-historical-phases)
- **Dependencies:** [P1 completed plan](../completed/P1-repository-intelligence.md)、[P2 completed plan](../completed/P2-arkui-code-graph.md)、[P2 specs](../../specs/code-graph/README.md)。
- **Evaluation inputs:** [P1 baseline](../../evaluation/p1-retrieval-baseline.md)、[P2 baseline](../../evaluation/p2-code-graph-baseline.md)。冻结 expected 保持在既有 fixtures 中。

> 本计划未完成，因此没有标记 Completed。A～E 的完成状态和对应 specs/evaluation 继续是历史事实；F1 及其后续 milestone 已停止，不得从本文件继续开发。旧代码和文档保留，是否由 R 路线复用须在新的 active plan 中明确决定。

## Historical authority and planning decisions

以下内容保留 supersession 时的规划和验收门槛，仅用于解释历史，不再授权实施。已实现行为仍以 `docs/specs/task-change-context/` 为准；旧共享知识草案保留在 `docs/specs/repository-knowledge/`。当前 provider-based 长期架构见 [`repository-knowledge-architecture.md`](../../architecture/repository-knowledge-architecture.md)，迁移决策见 [`ADR-0005`](../../decisions/ADR-0005-code-review-service-pivot.md)。

### Architecture migration directive

本计划替换旧的“repository revision 变化 → 默认 full P1/P2 rebuild”路线。应用本文件时必须遵守：

- 不回写或篡改 P1/P2 completed plan 的历史完成事实；
- 不修改 frozen P2 relation expected / baseline 来让增量实现“通过”；
- P1/P2 现有 public query contracts 能复用则保持兼容；增量能力优先通过新的 lifecycle/storage/provider 边界接入；
- 已存在的旧 P3-F 代码不得盲目删除。manifest、generation、lock、refresh service、full rebuild adapter 等若符合新 contract，应迁移为 F5/F6 或 fallback path；
- full rebuild 继续作为 bootstrap/recovery/fallback，但不再是高频源码变化的默认策略；
- 实时状态已核对为 P3 Phase In Progress、A–E Completed、旧 F In Progress；架构迁移后保持 A–E Completed，将 F1 作为新的当前 In Progress milestone，F2–F6/G/H/I 保持未开始，除非实时工作区随后已有更新。

### 1. 从 representation 开始，紧接 snapshot 读取契约

P3-A 先确定 Task/Change 的输入、坐标、revision intent、解析来源与 unresolved 状态。检索 orchestration 必须先知道检索什么、针对哪个 revision、哪些信息只是 hint。先做 refresh engine 会把工作扩大到全仓准备和发布流程，无法独立验证最早的输入边界。

P3-B 已完成 KnowledgeSnapshot identity、freshness check 与固定 generation 的只读 `SnapshotSession` 绑定；P3-C1 起所有真实查询均消费该既有 contract。新架构不追溯修改 B 的完成事实：基于 immutable shard membership 的 `SnapshotQueryView`、parent generation 与写侧 publication contract 由 P3-F5 扩展。P3-F1–F6 再逐步实现 dependency impact、P1/P2 incremental lifecycle 与完整 refresh entry point。

### 2. P1/P2 接入 candidate retrieval 的接口

以下为已核对的当前 API；P3 在其上增加薄的 typed adapter，不能直接查询私有 SQLite 表、拼 rg 命令或消费 clangd 私有 JSON。

| Channel | 已有入口 | P3 接入与限制 |
| --- | --- | --- |
| Text | `RepositoryTextSearch.search(TextSearchQuery)` | rg 留在 P1 backend；保留 range、query、路径范围、limit 和文本证据；不据文本创建 symbol identity |
| Symbol / declaration / definition | `DefinitionDeclarationRetriever.candidates_by_name / candidates_by_qualified_name / declaration / definition` | 消费 SQLite-backed `SymbolIndex`；保留全部 overload，不将 `resolve_unique` 失败转换为默认首项 |
| Reference / caller / callee | `ReferenceCallRetriever.references / callers / callees` | 使用精确 `SymbolIdentity`；保留 dangling endpoint 和 caller-range 精度，不伪造 call-site |
| Changed range mapping | `SymbolIndex.symbols_in_file` 及 declaration/definition ranges | P3-C2 按 revision side 和语义范围映射；P1 range 无法证明 enclosing symbol 时保留 unresolved |
| Tests | `SymbolIndex.find_test_fixtures / find_test_cases / test_cases_for_fixture / test_cases_for_symbol / tested_symbol_mappings_for_symbol` | typed test candidates 保留 mapping evidence；名称/文本找到的相似测试不冒充 tested-symbol mapping |
| Graph / domain | `GraphSnapshot.query()` → `GraphQuery.node / incoming_edges / outgoing_edges / neighbors / traverse`，`DomainMap.lookup / members` | C1 暴露显式 seed 的直接 graph 候选；D 才选择任务相关 expansion policy，不更改 P2 traversal |
| Domain trace | 现有 `trace_component_creation / trace_property_update / trace_measure_layout / trace_overlay` | D 按可证明的 seed 调用；保留 trace-local association、status、gaps、candidates、exhaustive，不把 association 转为 CALL |
| Semantic backend | `SemanticProvider`，当前实现 `ClangdSemanticProvider` | clangd 通过 P1 producer/adapter 为 F3 重建 affected TU；candidate orchestration 不临时启动私有 semantic 查询补洞，也不依赖 clangd 私有 `.idx` 作为 Repository Knowledge contract |

P1 没有统一 Task retrieval orchestrator，也没有跨 artifact freshness manager。P2 `snapshot_key` 是调用方提供的 scope key，不自动证明 Git revision 一致。现有 evaluation preparation 是选定文件/查询的 harness，不能直接充当生产全仓知识管理器。

INHERIT/OVERRIDE 当前在 P2 `unavailable_relations` 中，可靠 MOCK mapping 尚不可生产。通道须返回 unsupported/unknown 与来源，不返回假成功空关系。Similar implementation/test/mock 的文本候选可以进入 optional evidence，但本 Phase 不新增 similarity engine、mock 语义推断或测试覆盖率分析。

### 3. Expansion、subgraph、ranking 与 selection 分工

```text
Task / Change representation (A)
        + Knowledge binding (B)
        ↓
Candidate retrieval (C1) + changed-symbol mapping (C2)
        ↓
Task / Change-driven expansion (D)
        ↓
Task / Change subgraph + ContextCandidateSet (E)
        ↓
Context ranking / tiers (G)
        ↓
Token selection + Context Pack (H)

Incremental Repository Knowledge (F1–F6) → 复用 B 的 binding，供 C1–H 查询前调用
Evaluation annotations 自 A 开始，阶段检查随 C1–H 累积，I 汇总真实验收
```

- **Candidate retrieval:** 有界多路召回、身份去重、provenance 合并和各通道完整性说明；其 query/node/candidate limits 控制查询规模，不是最终 token 预算，不删除候选以伪装最终 context。
- **P2 traversal:** 显式 seeds、方向、relation filter 与局部 bounds 下的通用查询，不理解 Task/Change，BFS 结果不是 induced subgraph，canonical order 不是 ranking。
- **P3 expansion:** 根据输入意图、changed symbols 和已有证据选 seeds、方向、relations、trace family 与各 seed 预算；记录 policy/version、seed reason、已查询范围、截断和未知。只能消费现有关系，不能生成缺失的 P2 edge 或修改 trace 规则。
- **P3 subgraph:** 从 D 的观察结果按任务关联性抽取带边界说明的任务视图；保留 endpoints、supporting evidence、trace association 与缺口。默认不声称 induced/全仓完整，不以“同组件”作为纳入全部成员的理由。
- **Ranking input:** E 交付 immutable typed `ContextCandidateSet`（拟名），包含 input reference、B snapshot reference、candidate records、task subgraph、channel/expansion diagnostics。单个 candidate 含稳定 scoped ID、kind（symbol/range/relation/test/trace association）、repository/revision/side、精确 identity/range 或缺失原因、evidence references、命中通道/query/seed、距离及关联理由、source hash、依赖 candidate IDs、ambiguity/truncation 状态。重叠 source range 可共享 backing evidence；不能只传裸字符串/snippet 列表。E 同时实现有界 snippet materialization，未能取得源码的候选有明确状态。
- **Ranking output:** G 产出候选引用、tier、score/features、排序理由和稳定 tie-break，不消耗最终 token budget、不丢弃候选、不通过排序消除语义 ambiguity。
- **Selection / Pack:** H 根据 ranked candidates、依赖闭包及准确计量的 budget 选择内容并记录排除理由。E 冻结内部 candidate/ranking 输入 v1；H 在具备真实候选、freshness 和超预算案例后冻结最终 Context Pack v1 schema。A 只确定 envelope 概念，不能提前承诺最终 Pack schema。

### 4. Revision 和知识生命周期约束

Task 针对显式目标 revision；Change 保留 base/head、old/new path、old/new range 与 diff provenance。默认 supporting context 针对 head；deleted/base-only 内容来自 base-side evidence。没有 base snapshot 时保留 deletion hunk 并报告 base symbol unresolved，不能拿 head 同行号或同名 symbol 替代。跨 revision 的 identity 不假设可直接比较。

B 的 snapshot manifest 覆盖 repository identity/revision/generation、parent snapshot、P1 semantic manifest、P2 graph manifest、dependency/build configuration、schema/tool/ruleset identity、build scope/coverage、built_at、build/freshness 与 refresh metadata，并区分 latest attempt 和 last usable snapshot。Snapshot 是 logical manifest，不要求每个 generation 复制一份完整物理数据库。build scope 必须显式，选定文件的 evaluation index 不可宣称全仓完整。

fresh/stale/building/failed/unknown 语义遵循 roadmap；未知 revision、dirty checkout、P1/P2 manifest 不一致、源码查询期间变化不能标 fresh。默认阻止不兼容的混合知识；允许调用方显式请求降级并在结果记录限制，不由 P3 替具体 capability 决定接受 stale 的业务政策。查询绑定的 published shard/version 不可被就地覆盖；B 定义只读 session，F5/F6 实现独立 generation 与 atomic publication。当前 rg 查询和 snippet 读取仍接触 source workspace，必须验证其与绑定 revision/source fingerprint 一致。

F1–F6 在不改变 P1/P2 语义 contract 的前提下补齐增量 lifecycle：Change/Dependency Impact → P1 semantic shard/ownership → P1 delta → P2 derived-fact invalidation/incremental projection → snapshot/query view → refresh planner/atomic publish。manual 与外部 scheduler 调用同一单次 entry point；不实现 scheduler daemon、PR polling 或 Code Host adapter。

## Milestone sequence

架构迁移后，P3-F 拆为 F1–F6。状态以实时工作区为准；下表描述依赖顺序，不要求重做已经通过且不受新架构影响的 A–E。

| Milestone | Core goal | Dependencies |
| --- | --- | --- |
| P3-A | Task/Change representation 与解析边界 | P1/P2 completed |
| P3-B | 既有 KnowledgeSnapshot manifest、freshness 与固定-generation 只读 SnapshotSession | A |
| P3-C1 | 多通道 candidate retrieval | A、B |
| P3-C2 | Change ranges → symbol seeds | C1 |
| P3-D | Task/Change-driven Graph Expansion | C1、C2 |
| P3-E | Task Subgraph、snippet materialization 与统一 candidate set | D |
| P3-F1 | Change Detection、Compile Context 与 Dependency Impact foundation | B；P1 public contracts |
| P3-F2 | P1 immutable Semantic Shard、fact ownership 与 visibility storage | F1 |
| P3-F3 | P1 affected-TU incremental semantic refresh 与 P1 Delta | F1、F2 |
| P3-F4 | P2 derived-fact provenance/ownership 与 incremental graph refresh | F3；既有 P2 semantics |
| P3-F5 | immutable KnowledgeSnapshot generation、Snapshot Query View 与 atomic publication primitives | B、F2、F4 |
| P3-F6 | Refresh Planner / Orchestrator：NO_OP / INCREMENTAL / FULL_REBUILD | F1–F5；C1 可作为 read consumer |
| P3-G | Context Ranking 与 tiering | E |
| P3-H | token selection 与 Context Pack v1 | F6、G |
| P3-I | 真实 incremental refresh + expansion/context baseline 与 P3 收尾 | A–H、F1–F6 |

推荐在进入 H 前完成 F1 → F2 → F3 → F4 → F5 → F6。G 与 F1–F6 可以在依赖允许时并行开发，但 H 必须消费已冻结的 snapshot/query binding。若旧 P3-F 已有实现，先按 migration directive 将可复用部分映射到 F5/F6/fallback，不要重新从零实现。

## P3-A — Task / Change Representation and Parsing Boundary

- **Status:** Completed
- **Goal:** 建立共享 typed 输入，使后续检索无需重新解释原始请求和 diff 坐标。
- **Dependencies:** P1/P2 completed；输出供 B、C1/C2 使用。
- **Scope:** 自然语言 Task 的原文、显式/提取 hints（component、symbol、property、action、test intent）及提取来源；结构化 Task；平台无关 Change 的 base/head、files/hunks/ranges、change kind/provenance；受支持 unified diff 解析、坐标规范化、错误与 unresolved 模型。有限 deterministic 解析，未知自然语言保留全文供 text retrieval。
- **Non-goals:** symbol resolution、retrieval orchestration、LLM parser、GitCode ingestion、snapshot 构建、最终 Pack、源码变更。
- **Deliverables:** 输入模型/parser/serialization；对应 input specification 与 contract tests；P3 evaluation case 的输入/标注提纲（不填充未经验证的 expected）。
- **Acceptance Criteria:** Task/Change 均可 round-trip；输入来源与 hint 不混淆为 repository fact；old/new 侧明确；rename/add/delete、零长度 insertion/deletion range 可表达；不支持 binary/combined diff 以显式状态保留而非误解析；路径逃逸与非法范围拒绝；不要求 index/clangd/LLM 才能解析输入。
- **Tests / real validation:** 更新纯模型与 parser tests，覆盖中文 Task、未知组件、overload hint、多文件多 hunk、缺 revision、非法 diff。真实验证仅人工检查所选 P2 case 的 Task 输入及可复现 Change 输入设计，不运行 baseline；本 milestone 不以真实 retrieval 成功为 AC。
- **Known Limitations:** 不承诺通用自然语言意图理解；PR/commit 数据必须由外部转换为平台无关输入。
- **Implementation / acceptance:** 输入实现位于 `arkui_agent.context`；contract 见 [input v1](../../specs/task-change-context/input-v1.md)，标注提纲见 [P3 input annotations](../../evaluation/p3-input-annotation-outline.md)。Stop Hook 已验证两个 input/parser 模块的 20 个测试通过；用户已接受当前输入设计，P3-A 收口。

## P3-B — Knowledge Snapshot Read Contract and Freshness

- **Status:** Completed
- **Goal:** 在第一条多通道查询前确保所有 evidence 有一致且可核验的知识来源。该 milestone 的完成事实保持不变；增量 shard-aware Query View 属于 F5，而不是追溯要求 B 重做。
- **Dependencies:** A；为 C1–H 提供既有固定-generation 读取绑定，F5/F6 继续复用并扩展。
- **Scope:** typed manifest、repository/revision/build scope 身份、freshness evaluation、读取和验证显式预构建 artifacts、固定 generation 的只读 session binding、source revision/hash 检查；last usable 与 latest attempt 分离。
- **Non-goals:** dependency invalidation、semantic/graph shard storage、自动 refresh、长期 scheduler、parent-manifest reuse、shard-aware SnapshotQueryView、写侧 atomic publication。
- **Deliverables:** 已实现的 snapshot/freshness spec、只读 manifest adapter、检查入口和 temporary repository integration fixtures；权威 contract 继续见 `docs/specs/task-change-context/knowledge-snapshot-v1.md`。
- **Acceptance Criteria:** 保持既有 B contract：五种 freshness 语义可区分；old index/new graph 或未知 revision 不得 fresh；dirty/source drift 明确拒绝或降级；覆盖范围不足区别于 stale；合法预构建 snapshot 可固定 generation 绑定并供查询复用；缺失/损坏 manifest 不能静默产生空 fresh snapshot。
- **Implementation / acceptance:** `arkui_agent.knowledge` 已实现 manifest、freshness、prebuilt read adapter 与固定-generation session，B 已完成。F5 将在不破坏该读取 contract 的前提下增加 immutable shard membership、parent generation、SnapshotQueryView 与 publication primitives；不得把这些新要求伪装成 B 当时已经实现。

## P3-C1 — Multi-channel Candidate Retrieval

- **Status:** Completed
- **Goal:** 将 Task hints 或显式 Change seeds 转换为统一、可追溯的候选集合。
- **Dependencies:** A、B；供 C2 映射后重新召回及 D expansion 使用。
- **Scope:** 上述 P1/P2 typed adapters、有限 query planning、Text/Symbol/Reference/Call/Test/直接 Graph 候选、通道预算、identity-based dedup、provenance 合并、channel availability/completeness。候选模型在 E 汇总时收敛，不冻结最终 Pack。
- **Non-goals:** changed range 语义映射、递归任务图扩展、最终排序/selection、直接依赖 rg/clangd/SQLite 私有协议。
- **Deliverables:** retrieval service 与 candidate result types、对应 spec、真实 P1 接口 integration tests，首批独立 P3 人工 expected cases。
- **Acceptance Criteria:** Task 和结构化 Change seed 可走相同通道；同名不同 identity 保留；查询顺序不影响 canonical output；empty/unsupported/backend failure/truncated 分开；每个 candidate 有 snapshot/source/query provenance；有限 candidate limit 不被表述为最终上下文完整性。
- **Tests / real validation:** 临时 C++ repository 使用真实 P1 facade/index/rg 验证跨通道重复、空 test mapping、工具缺失与错误传播；用户显式触发 Button/Text/Menu 小范围 candidate smoke，复用 P1 revision 检查和标注 anchors，不读取 expected 生产候选。
- **Known Limitations:** C1 只消费显式 changed symbol seeds；普通 diff 的 symbol seeds 在 C2 接通。没有可靠 test mapping 时可返回文本测试候选，但必须区分证据等级。
- **Implementation / acceptance:** 用户接受实现设计并于 2026-09-09 人工冻结三组 [expected](../../evaluation/p3-c1-annotation-draft.md)。trusted Stop Hook 22/22 通过；显式 real smoke 在查询前固定的 30-file snapshot 上 required 12/12、provenance/顺序稳定性通过、0 新造 relation。组件 text query 的截断和 P1 caller-range 精度限制保留；详见 [C1 验收记录](../../evaluation/p3-c1-candidate-smoke.md)。未运行 strict full，不进入 C2。

## P3-C2 — Change Range to Symbol Mapping

- **Status:** Completed
- **Goal:** 在可证明范围内把 Change 文件/hunk/range 转为语义 seeds，并保持双侧 provenance。
- **Dependencies:** A、B、C1；输出供 D，映射后复用 C1 检索。
- **Scope:** 按 revision side 查询 P1 file/symbol ranges；enclosing/overlap 关系分类；新增、删除、重命名、多 symbol hunk、无法映射和 ambiguity；head 支持上下文与 base-only evidence 分离。
- **Non-goals:** 猜测跨 revision symbol identity、修改 P1 C++ backend、Git diff 获取平台集成、从文本补出语义关系。
- **Deliverables:** mapper、Change retrieval integration、mapping spec、revision-bound Change cases。
- **Acceptance Criteria:** 可证明的 changed symbols 保留 identity 和范围依据；多个相交 symbol 不静默选一个；P1 范围不足保持 unresolved；缺 base snapshot 不用 head 行号替代 deletion；有两个兼容 side snapshots 时各自映射并不跨侧合并；未解析 diff 仍进入 file/range candidates。
- **Tests / real validation:** 临时双 revision Git/C++ fixture 验证行移动、rename、删除、宏、hunk 跨函数、declaration/definition；用户显式触发真实 ArkUI Change smoke，使用人工确认的 base/head 和 hunks。若尚无可用真实 revision pair，保持该真实验收未完成，不能用伪造相同 base/head 顶替。
- **Known Limitations:** changed symbol 不等于行为影响范围；不要求所有 hunk 都能映射。
- **Implementation / acceptance:** C2 mapper、双侧绑定及最小 P1 canonicalization 已通过 trusted Hook（72/72，188.289 秒）与原冻结真实 smoke。4 required hits / 3 unresolved / 1 not_applicable 全通过，双侧 fresh、identity/extent/provenance 独立审计与重复 canonical output 稳定性通过。见 [最终验收](../../evaluation/p3-c2-change-smoke.md)；frozen expected 未变，不启动 D。

## P3-D — Task / Change-driven Graph Expansion

- **Status:** Completed
- **Goal:** 根据任务/变更有界选择和组合已有 graph 与 trace 观察，扩大相关证据召回。
- **Dependencies:** C1、C2；输出供 E。
- **Scope:** 显式 policy 配置/version；Task/Change seeds、上下游方向、relation family、适用 trace query；per-seed 与全局 node/edge/query/path 限额；去重、stop reason、ambiguity 与已知缺口透传。
- **Non-goals:** 重写 P2 BFS/trace、补齐 19 条 frozen missing relation、通用 Lifecycle Trace、虚拟调用/宏/callback 推断、token selection。
- **Deliverables:** expansion orchestrator/result、expansion spec、P2 case 对应 P3 expansion annotations 与 tests。
- **Acceptance Criteria:** 相同 snapshot/input/policy 可重复；所有扩展均可追溯 seed 与真实 relation；跨组件扩展必须有事实依据；操作 binding 不转为 CALL；预算限制显式说明；Menu layout 多 algorithm、Overlay 多 Close path 保留；缺关系时可召回独立证据但不能宣称 P2 trace 已修复。
- **Tests / real validation:** cycle、多 seed 汇合、预算刚好/超限、unsupported relation、partial graph；用户显式运行四类真实 P2 trace 场景的 P3 expansion smoke，同时报告原 P2 status 与新增任务相关 evidence，指标遵循下方 evaluation 设计。
- **Known Limitations:** expansion 不能超过 P1/P2 已有事实能力；role catalog 限制和 unknown components 原样可见。
- **Implementation / acceptance:** `arkui_agent.retrieval.expansion` 实现 versioned、有界 P2 observation 编排；[spec](../../specs/task-change-context/graph-expansion-v1.md)。trusted Hook 12/12、11 个真实 Task cases 与正式 frozen Change expansion 验收通过；用户于 2026-09-10 批准 [语义 gold](../../evaluation/p3-d-expansion-annotations.md)，所有 D AC 满足，见 [验收报告](../../evaluation/p3-d-expansion-smoke.md)。recall/无关比例保持 N/A；未改 P2 expected，未进入后续 milestone。

## P3-E — Task Subgraph and Context Candidate Materialization

- **Status:** Completed
- **Goal:** 将召回与 expansion 观察整理为可独立供 ranking 消费的任务视图及证据单元。
- **Dependencies:** D（复用 B/C1/C2）；供 G/H 使用。
- **Scope:** Task/Change subgraph extraction、关系端点和 supporting evidence 闭包、trace-local association 独立表达、显式边界；只读 snippet materialization、range/hash 校验、重叠片段去重、统一 `ContextCandidateSet`。
- **Non-goals:** induced 全图承诺、ranking、token selection、生成自然语言分析结论、扩展新的 parser/graph relation。
- **Deliverables:** subgraph extractor、candidate materializer、内部 candidate/ranking input v1 spec；引用既有 P2 evidence spec，不复制定义。
- **Acceptance Criteria:** 所有 relation endpoints 可解析；文本命中和语义 evidence 可区分；snippet 来自所声明 revision/range；缺 source/range 返回明确限制；无悬空 candidate dependency；unknown/ambiguous/truncation 不在 extraction 中消失；序列化/反序列化后身份和关联保持；不需要 ranker 或 LLM。
- **Tests / real validation:** 非 induced BFS 结果、共享 endpoint、association 非 edge、跨 revision snippet 拒绝、source drift、overlapping ranges；用户显式检查 Button creation、FontWeight property、Menu layout/overlay 的真实 subgraph/snippet provenance。
- **Known Limitations:** subgraph 完整性仅相对于已观察和声明的检索范围；源码不可得时不能提供伪造 snippet。
- **Implementation / acceptance:** `arkui_agent.context.materialization`、`snippets`、`candidate_serialization` 提供观察闭包与内部 ranking input v1，见 [spec](../../specs/task-change-context/context-candidates-v1.md)。BFS provenance 修复后 trusted Hook 12/12（76.592 秒）；四类五个核心真实 cases 与 Button text 补充检查通过。2026-09-10 按用户授权冻结 [evidence gold](../../evaluation/p3-e-materialization-annotations.md)，逐项 AC 复核无新缺口，见 [验收报告](../../evaluation/p3-e-materialization-smoke.md)。真实 Change 双侧 E smoke 非本 milestone 必需项，保留未验证至 P3-I；未运行 strict full，未进入 F。

## P3-F1 — Change Detection, Compile Context and Dependency Impact

- **Status:** In Progress
- **Goal:** 为高频源码变化建立可证明的 affected-TU 计算，不再把“repository revision changed”直接等价为 full rebuild。
- **Dependencies:** B；复用 P1 workspace/scanner/config/provider 边界。
- **Scope:** repository diff/change normalization、compile command/context identity、TU identity、dependency metadata adapter、reverse dependency lookup、header/config → affected TU propagation、semantic fingerprint input model、impact diagnostics；dependency source 可以来自 compile/build dep metadata 或可验证的 compiler-derived source，具体 backend 隔离在 adapter 后。
- **Non-goals:** 重新解析 affected TU、写 semantic facts、P2 graph refresh、scheduler daemon、只靠文本 `#include` 扫描宣称完整 dependency graph。
- **Deliverables:** dependency/impact model 与 service、backend adapter contract、对应 repository-knowledge spec/tests。
- **Acceptance Criteria:** `.cpp` 变化至少命中自身 TU；header 变化传播到直接/传递依赖 TU；compile command/relevant config 变化使对应 TU fingerprint 变化；dependency coverage 不足返回 unknown/degraded/fallback reason；相同输入 canonical output 稳定；不把未证明完整的依赖结果标为 safe incremental。
- **Tests / real validation:** temporary C++ fixture 覆盖 direct/transitive header、多个 TU、compile flag 改动、文件删除/rename、缺 dependency metadata；用户显式在 ArkUI 选定 scope 比较 changed files → affected TUs 与 build metadata。

## P3-F2 — P1 Semantic Shard Versioning and Fact Ownership

- **Status:** Not Started
- **Goal:** 让 P1 persistent knowledge 支持 immutable semantic shard version 与 shared fact ownership，为 copy-on-write generation 奠定存储基础。
- **Dependencies:** F1；保持现有 P1 retrieval facade 兼容。
- **Scope:** logical `SemanticShardId/Version`、TU/fingerprint binding、fact canonical identity 与 ownership、immutable published shard、candidate/unpublished shard、snapshot visibility primitives、replacement/removal semantics、schema migration boundary；允许 single/few SQLite stores，不要求一 TU 一文件。
- **Non-goals:** Base+Delta/LSM、复杂 compaction、P2 graph、跨 repository fact dedup、改变 P1 symbol identity 语义。
- **Deliverables:** P1 shard/ownership storage API、migration/spec、query-index compatibility tests。
- **Acceptance Criteria:** 新 shard 不原地修改 published old shard；shared fact 撤销一个 owner 后仍可由其他 owner 保留；owner 归零后在新视图消失；旧 snapshot/session 仍可读取旧 shard；普通 symbol/reference/test query 通过索引执行，不扫描全部 shard；损坏/冲突显式失败。
- **Tests / real validation:** multi-owner header fact、TU replacement、deletion、old/new visibility、transaction failure、query latency smoke；不以创建大量 SQLite 文件作为分片实现。

## P3-F3 — P1 Incremental Semantic Refresh and Delta

- **Status:** Not Started
- **Goal:** 只对 F1 的 affected TUs 调用 semantic producer，并形成可供 P2 消费的结构化 P1 Delta。
- **Dependencies:** F1、F2；复用 `SemanticProvider` / `ClangdSemanticProvider`。
- **Scope:** fingerprint reuse/no-op、affected-TU semantic production、candidate shard build、ownership diff、added/removed/changed facts、touched symbols/files、coverage diagnostics、P1-level full rebuild fallback adapter。
- **Non-goals:** 使用 clangd 私有 `.idx` 作为持久化 contract、P2 projection、task retrieval、无限重试。
- **Deliverables:** incremental P1 refresher、`P1Delta` contract/spec、integration tests 和 reusable full-build fallback。
- **Acceptance Criteria:** unaffected TU 不调用 semantic producer；fingerprint unchanged 可复用；header impact 仅重建 F1 判定的 safe affected set；producer/IO/source drift 失败不发布 candidate P1 state；P1 Delta 可稳定表达 add/change/delete；同一最终源码的 incremental P1 view 与 full rebuild 在受支持 facts 上等价。
- **Tests / real validation:** temporary repo incremental-vs-full conformance、删除/rename、header fan-out、compile flag 变化、producer failure；用户显式 ArkUI 小范围变更 smoke 记录 rebuilt/reused TU/shard counts。

## P3-F4 — P2 Incremental Graph Refresh

- **Status:** Not Started
- **Goal:** 让 P2 不再在每次 P1 小变化后默认全量 projection，而是根据 P1 Delta 和 derived-fact provenance 更新受影响 graph/domain facts。
- **Dependencies:** F3；既有 P2 graph/domain semantics、trace specs 与 frozen baseline 不变。
- **Scope:** derived-fact provenance/ownership、rule/ruleset identity、invalidation scope metadata、P1 Delta → affected derivations、incremental generic projection、role/framework relation refresh、graph derivation shard/partition replacement、rule-level/wide-scope/full-P2 fallback。
- **Non-goals:** 修改 frozen relation expected、补齐历史 missing relation、通过增量机制发明新 CALL/ArkUI edge、要求所有规则第一版都支持精确局部 invalidation。
- **Deliverables:** P2 incremental projection API、`P2Delta/Impact` 或等价 contract、storage/provenance spec 更新、conformance tests。
- **Acceptance Criteria:** unchanged derivations 可复用；失效 fact 不在新 graph view 残留；所有增量 derived facts 保留与 full projection 同等 provenance；无法证明局部失效的规则显式扩大 scope/fallback；相同源码/ruleset 下 incremental result 与 full P2 rebuild 在规范化 graph/domain facts 上等价；frozen P2 baseline 不因迁移被改 gold。
- **Tests / real validation:** generic edge add/remove、shared endpoint、role/framework rule impact、ruleset change、fallback path；用户显式在已有 Button/Text/Menu cases 对 incremental vs full graph 做规范化 diff。

## P3-F5 — Snapshot Generation, Query View and Atomic Publication Primitives

- **Status:** Not Started
- **Goal:** 把 B 的 read contract 与 F2/F4 的 versioned artifacts 连接成 immutable logical generation，并保证查询性能不随 shard 数线性退化。
- **Dependencies:** B、F2、F4。
- **Scope:** semantic/graph manifest identity、parent generation、candidate vs published state、active shard membership 或等价 visibility index、`SnapshotSession` realization、atomic generation switch、old-reader preservation、retention/GC safety metadata；query path 保持 P1/P2 indexed facade。
- **Non-goals:** refresh strategy 决策、scheduler daemon、Base+Delta compaction、删除仍被 reader/retained snapshot 引用的 shard。
- **Deliverables:** manifest store、query-view binding、publication primitives、repository-knowledge spec/tests。
- **Acceptance Criteria:** Generation N 与 N+1 可共享未变 shard；publish 前 candidate 对普通 reader 不可见；publish 原子切换 current generation；已绑定 N 的 session 在 N+1 发布后仍读 N；symbol/relation query 不扫描全部 manifest/shards；失败 publish 保留 last usable；GC 只标记/删除无引用安全对象。
- **Tests / real validation:** concurrent old reader/new publish、manifest corruption、publish crash injection、membership query、retention/GC roots、query latency 随 shard 数增长的 smoke。

## P3-F6 — Refresh Planner and Incremental Orchestration

- **Status:** Not Started
- **Goal:** 提供 manual/scheduler-invokable 的统一 refresh service，把 F1–F5 组织成可观测、可回退、失败安全的生产流程。
- **Dependencies:** F1–F5；C1 可作为 snapshot-bound read consumer；H 依赖本 milestone。
- **Scope:** target revision/config resolve、reason/force、single-writer、`NO_OP / INCREMENTAL / FULL_REBUILD` planning、P1/P2 stage orchestration、candidate validation、source drift recheck、atomic publish、last usable/latest attempt、coverage/metrics report、配置化 full rebuild fallback。
- **Non-goals:** scheduler daemon、自动拉取/checkout target、PR polling、GitCode provider、无限重试、在 planner 中实现新的 semantic/graph facts。
- **Deliverables:** shared refresh service/CLI、planner policy/spec、full fallback adapter、integration tests 与可复用真实 smoke entry point。
- **Acceptance Criteria:** revision/config unchanged 可 NO_OP；safe small change 默认走 incremental；dependency/schema/ruleset incompatibility 可选择 wider/full fallback；force 可 full rebuild；任一 stage/source drift/validation/publish 失败均不发布 fresh candidate；old session 保持原 generation；writer conflict 显式失败；报告 changed files、affected TUs、reused/rebuilt P1/P2 shards、strategy 与 timing；输出可直接被 B/C1–H 消费。
- **Tests / real validation:** temporary repository incremental round-trip、incremental-vs-full equality、失败注入、writer conflict、rules/config change、large-impact fallback；用户显式触发 ArkUI 指定 scope incremental refresh → retrieval/expansion，并单独运行 full fallback 作 correctness comparison。昂贵全仓验证仍由用户显式触发。
- **Known Limitations:** 第一版不承诺所有 P2 rule 都精确局部增量，也不引入 Base+Delta；任何 unknown invalidation 必须扩大 scope/fallback，不能以性能为由牺牲 freshness correctness。

## P3-G — Context Ranking and Tiering

- **Status:** Not Started
- **Goal:** 对 E 的候选做可解释排序，表达 Tier 1/2/3 的任务相关性。
- **Dependencies:** E；H 消费结果，可与 F1–F6 独立验收。
- **Scope:** deterministic feature-based ranker、target/changed evidence、direct dependency、graph distance、channel/provenance strength、test relevance、tiers 和稳定 tie-break；同一 ranker 支持 Task/Change。
- **Non-goals:** token selection、LLM reranker 依赖、用 ranking 解决 symbol ambiguity、创建新的事实。
- **Deliverables:** ranked candidate model、ranking policy/spec、独立人工 relevant/required annotation、ranking tests。
- **Acceptance Criteria:** 输入为 E `ContextCandidateSet`；输出引用原 candidate 且保留全部证据与限制；逐项 tier/features/reason 可解释；输入顺序变化不改变结果；低置信候选不被升级为确定 relation；Task/Change must-have priority 可验证。
- **Tests / real validation:** ties、缺 features、ambiguous targets、duplicate snippets、optional text test vs semantic test mapping；用户显式在相同 P3 真实 candidate sets 比较无任务排序与 ranking，记录 relevant/required evidence 排位，不据实际排序反填 gold。
- **Known Limitations:** 分数用于排序，不是正确性概率；不承诺每个 Tier 1 项都能塞入任意 budget。

## P3-H — Token Selection and Context Pack v1

- **Status:** Not Started
- **Goal:** 输出可直接供后续 P4 消费的稳定、可追溯且受预算约束的 Task/Change Context Pack。
- **Dependencies:** F6、G（复用 A–E）；I 验收完整链路。
- **Scope:** tokenizer adapter/identity、完整序列化输出计量、上下文 budget 与可配置外部预留；依赖一致的 selection、snippet 安全裁剪、include/exclude reason；Task 与 Review/Change 共享的 versioned Context Pack envelope。
- **Non-goals:** Agent/LLM invocation、ReviewFinding、最终评论、UT 生成、为了压缩而改写源码或丢失 provenance。
- **Deliverables:** selector、serializer、Context Pack v1 稳定 schema/spec、Task/Change 示例与 end-to-end 入口。本 milestone 完成时冻结 schema，后续破坏性修改必须显式升级版本。
- **Acceptance Criteria:** Pack 包含 input、target/changed/related symbols、call/framework relations、snippets、tests、similar/mock evidence 的可用性、snapshot/revision、provenance、selection reasons、tokenizer/budget/actual cost 和 partial/unknown 状态；空或 unavailable 类别可表达，不要求伪造内容。全部输出（含元数据）计量不超 budget；必需项或最小 envelope 放不下时返回明确 budget failure/不完整状态，不能静默越界。预算被裁掉的依赖与上游缺事实分开报告；selected relation 的端点和必要 supporting evidence 不悬空；schema round-trip 与版本不兼容行为明确。
- **Tests / real validation:** 中文/C++/Unicode、精确预算边界、零/过小预算、单个超大 symbol、共享片段、裁剪后 range、无候选、stale downgrade、base-only deletion、schema round-trip；用户显式运行真实 Task/Change packs，在固定 tokenizer 和多档 budget 下人工核验 source/provenance、missing dependency 和成本。
- **Known Limitations:** 不保证极小 budget 下 context 完整；精确 token cost 只对记录的 tokenizer/serialization 有效，不能把估算当成硬上限证明。

## P3-I — Real Expansion / Context Baseline and Phase Closure

- **Status:** Not Started
- **Goal:** 对整个 P3 链路建立可重现真实基线，并对照 phase-map DoD 收尾。
- **Dependencies:** A–H 与 F1–F6 全部完成，人工 expected 已在执行前冻结。
- **Scope:** 复用各 milestone annotations，整合 Task/Change、incremental snapshot/refresh、retrieval/expansion/ranking/selection 的真实 suite、指标、失败分类和报告入口；记录局限及分阶段成本。
- **Non-goals:** 修改 P2 frozen expected/算法、追求全部 P2 traces complete、P4 agent 或 P5 review/repair benchmark、P6 全面 ablation。
- **Deliverables:** 独立 P3 revision-bound dataset/fixtures、evaluation command、`docs/evaluation/p3-context-baseline.md`、DoD 对照及简洁 completion evidence；runtime report 不入 Git。
- **Acceptance Criteria:** 下方最小真实覆盖与指标全部可复现；无 provenance/snapshot/budget/expected-conformance 回归；known missing 能力单列且不得伪装恢复；所有必需测试和用户显式触发的真实/strict full 验证通过；对照 phase-map P3 DoD 1–13 给出证据后才将 Phase 标 Completed 并归档。
- **Tests / real validation:** metric arithmetic/empty denominators/失败分类 tests；用户显式执行真实 P3 suite、refresh integration 与 strict full；revision/anchor 不一致为 setup failure，不能 skip 后宣称通过。
- **Known Limitations:** 首个 baseline 只承诺标注范围内质量；P2 局限、P1 空 test mapping 与未支持语义关系仍可能影响上下文。

## Evaluation design and acceptance gates

### Frozen P2 baseline 是对照，不是 P3 自动修复清单

固定 source revision 与数字以 [P2 baseline](../../evaluation/p2-code-graph-baseline.md) 为唯一来源：18/18 expected conformance、64/83 relation coverage、19 missing、0 incorrect、trace Call Chain Accuracy 2/14。P3 expected 以独立标注存储，只引用 P2 case ID/revision/anchor；不改 P2 denominator、status、gap、unresolved 或 report。

| P2 实际情况 | P3 必需验证 |
| --- | --- |
| Button/Text creation complete | 正例：有限 expansion 找到任务需要的已存在依赖，selection 保留 required evidence |
| Menu creation callback/Pattern gap | 保留 known gap；可返回 callback 源码上下文，但不能生成 Pattern binding |
| FontWeight property 的 missing update/entry/writer | 区分文件/宏文本证据与不可证明的 state flow；source retrieval 命中不等于 relation 恢复 |
| Button partial layout、Text unsupported factory | 返回已知 stages 和依赖范围，说明缺失原因 |
| Menu layout 多 algorithm | 所有有证据候选保留 ambiguity；task hint 可改变排序，不能证明 runtime branch |
| Overlay 多 Close path、manager body unsupported、animation unresolved | 保留路径与未知，不把“未观察到”写成不存在 animation |
| P1/P2 missing test mapping、INHERIT/OVERRIDE/MOCK unavailable | 区分无 mapping、通道不支持、文本测试候选；不声称覆盖率或 mock relation |

### Dataset 和执行路径

1. A 定输入样例；C1/D 开始在独立 P3 fixtures 冻结人工 expected，E/G/H 增补 subgraph、relevance、budget 维度；I 汇总，不等到收尾才设计 gold。
2. 最小 Task suite 覆盖 Button/Text/Menu、四类 trace，以及上表各类 complete/incomplete/ambiguous/unresolved 情况；允许一个 case 覆盖多个标签，但不能只选成功案例。
3. Change suite 至少覆盖真实、可读取的 base/head pair 上的修改与一个 add/delete/rename 场景，包含可映射及无法证明 symbol 的范围。C2 选择具体 revision pair 并人工审查；Task suite 继续固定 P2 revision，Change pair 独立声明，不能冒充同一 snapshot。
4. gold 包含 required evidence、relevant optional evidence、已知不可得 dependency、禁止伪造的 relation、annotation rationale/annotator、source anchors 与 revision。精确 expected、空集和“未标注维度”分开；不从 actual 输出反填 expected。
5. 真实运行通过 P1/P2 生产接口准备/query、P3 orchestration 生成结果；expectations 只供比较。冻结 P2 observations 可用于 metric unit fixtures，但不能作为真实 P3 检索器的 canned output。
6. 至少比较相同输入/知识/预算下的 C1/C2 direct retrieval 与 D expansion，以及 H 的多档 token budget；不增加 LLM/Agent ablation。expected evidence 归一化单位在首批 P3 annotations 时冻结（建议 symbol/range/typed relation/test），重叠 range 去重规则同步确定。

### 指标与通过标准

- **Candidate / expansion recall:** 分别统计 direct retrieval 和 expansion 命中的人工 required/relevant evidence；报告新增召回及引入无关候选，不能只报告候选规模。
- **Relevant Context Ratio:** selected 去重 evidence 单元中人工 relevant 的比例；同时记录 snippet token 占比作为补充，不混用两种分母。
- **Missing Dependency Rate:** 未进入最终 Pack 的 required dependency / 全部人工 required dependency。另分列 upstream unavailable、retrieval miss、expansion bound、ranking/selection exclusion，主指标保留全部 required 分母；不能因为 P2 已知缺失就从主分母移除。
- **Context Token Cost:** H 最终序列化 Pack 的实际 token 数，记录 tokenizer/version、预算与预留；召回量、构建耗时和 token 成本独立报告。
- **Snapshot Freshness Correctness:** revision/status 转移及 failure cases 上的预期状态符合率；任何 mixed/failed/unknown 被误报 fresh 为硬失败。
- **Incremental Refresh Efficiency:** changed files、affected TU ratio、reused/rebuilt semantic/graph shards、stage latency；效率指标不覆盖 correctness。
- **Incremental-vs-Full Conformance:** 同一最终 revision/config 下 incremental 与 full rebuild 的规范化 P1/P2 facts 差异；unsupported/unknown 必须分类，stale leftover 或 missing supported fact 为硬失败。
- **Snapshot-bound Query Latency:** 固定 query suite 在 snapshot visibility 下的延迟/结果一致性；不得随 shard 数量通过线性扫描退化。
- **Provenance / uncertainty:** source/revision/identity/hash 可追溯率，ambiguity/gap/truncation 保留情况，新增无证据 relation 数；无证据关系、身份错误或静默丢失重要 uncertainty 为硬失败。
- 非适用维度报告 N/A，不当作 0 或 1；空 gold/empty output 的分母规则在 evaluation spec 中冻结，并同时报告 case 数与分母。按 case/component/Task-vs-Change 分解，再给 macro aggregate，不能用成功 case 隐藏失败。

首版不凭空承诺 RCR 达到某百分比或全部 dependency 命中；C1/D 在执行前冻结逐 case 可实现 evidence 预期，I 要求这些 expected 全部符合，并解释全部 missing。质量门槛为：可得且标为必需的事实符合预期、无伪造关系、provenance 完整、freshness 判断正确、输出不超预算；保留上游缺口不会阻止通过，但未完成必需验证会阻止 Completed。

### Validation discipline

遵循当前 AGENTS.md：开发时新增/更新行为测试，但 Codex 不主动执行测试命令；trusted Stop Hook 仅运行工作树新增/修改的 `test_*.py`。Hook 不可用或未 trusted 必须报告未验证，不手动补跑。任何本计划列出的真实 ArkUI smoke/baseline、全仓 refresh、incremental-vs-full 大范围对照、strict full 和昂贵验证均由用户显式触发；未执行的必需项保留待验收，不能提前将 milestone 设 Completed。

本 session 仅做文档整理与 `git diff --check`，不运行 P2 baseline 或 P3 测试。既有工作树产品代码、测试、Hook 修改和 frozen expected 全部保留；不导出 patch、逐命令日志或新的 runtime snapshot。

## P3 Definition of Done traceability

| Phase-map P3 DoD | Delivery / final validation |
| --- | --- |
| 1 Task → structured Pack | A、C1、D–H；I |
| 2 Change revisions / hunks / symbols | A、C2、B、H；I |
| 3 shared retrieval channels | C1、C2、D；I（unsupported 明示） |
| 4 retrieval / final context separation + budget | C1、E、G、H；I |
| 5 source traceability and inclusion/exclusion | B、C1–E、G、H；I |
| 6 snapshot/generation/session freshness | B、F5、F6；I |
| 7 manual + scheduler-invokable refresh / NO_OP | F6；I |
| 8 dependency impact + affected-TU P1 incremental | F1–F3；I |
| 9 P1 delta → P2 incremental / safe fallback | F4、F6；I |
| 10 failure-safe atomic publish + last usable | B、F5、F6；I |
| 11 Pack snapshot identity + indexed query view | B、C1、F5、H；I |
| 12 context + incremental lifecycle metrics | C1–H、F1–F6；I 汇总 |
| 13 bounded graph/source context | C1、D、E、H；I |

## No further execution under this plan

不得继续执行 P3-F1～F6/G/H/I，也不得由本计划启动 P4/P5。P3-A～E 的已完成 contract 不重做；旧实现若对新产品有价值，只能由 R0–R6 的新 active plan 在不修改 frozen semantics 的前提下显式复用。
