# P3 — Task / Change Retrieval & Context Builder

- **Phase Status:** Not Started
- **Planning:** 本计划已建立；本 session 不实现 P3 产品代码，不启动 P3-A。
- **Phase Goal:** 复用 P1/P2，将自然语言/结构化 Task 或平台无关 Change 转换为版本可追溯、证据充分且满足 token budget 的结构化 Context Pack。
- **Source of Truth:** [Technical roadmap](../../architecture/technical-roadmap.md)，重点为 §4–6。
- **Phase Boundary / Definition of Done:** [Phase map §6](../phase-map.md#6-p3--task--change-retrieval--context-builder)。
- **Dependencies:** [P1 completed plan](../completed/P1-repository-intelligence.md)、[P2 completed plan](../completed/P2-arkui-code-graph.md)、[P2 specs](../../specs/code-graph/README.md)。
- **Evaluation inputs:** [P1 baseline](../../evaluation/p1-retrieval-baseline.md)、[P2 baseline](../../evaluation/p2-code-graph-baseline.md)。冻结 expected 保持在既有 fixtures 中。

## Authority and planning decisions

本文件定义拟实施范围和验收门槛，不把规划字段当作已实现 API。各 milestone 实现时将行为、类型、不变量及失败语义写入 `docs/specs/task-change-context/`；共享知识契约写入 `docs/specs/repository-knowledge/`。这些是拟新增目录，本 session 不创建空 spec 或复制 P2 contract。完成后本计划只保留范围、验收索引和简要结果。

核对结果：roadmap 与 phase-map 的 P3 能力边界一致，没有需要重写总体架构的冲突。存在以下文档状态差异：

- `AGENTS.md` 的当前阶段仍停留 P2；本次仅同步为 P2 completed、P3 planning。
- `docs/README.md` 原引用不存在的 `repository-knowledge-lifecycle.md`；ADR-0003 Follow-up 与 Code Review architecture 均明确由 roadmap 统一维护生命周期，本次将导航指向 roadmap §4。
- 已完成 P2 计划中的历史 validation 流程保留归档；本次及后续开发遵循当前 AGENTS.md，不据此自动执行 strict full。
- phase-map 末尾“本次长期路线修订不创建新的 active plan”是前次路线修订的范围记录；本次用户已明确要求进入 P3 规划，不修改该历史说明。

### 1. 从 representation 开始，紧接 snapshot 读取契约

P3-A 先确定 Task/Change 的输入、坐标、revision intent、解析来源与 unresolved 状态。检索 orchestration 必须先知道检索什么、针对哪个 revision、哪些信息只是 hint。先做 refresh engine 会把工作扩大到全仓准备和发布流程，无法独立验证最早的输入边界。

P3-B 随即落实 KnowledgeSnapshot identity、freshness check 与只读 session binding。P3-C1 起所有真实查询均消费此绑定；P3-F 再实现完整 refresh/rebuild entry point。早期允许调用方显式提供已构建且能验证的 manifest，不能临时用任意字符串伪装 fresh。这样不依赖自动 refresh，也不在最后补装版本一致性。

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
| Semantic backend | `SemanticProvider`，当前实现 `ClangdSemanticProvider` | clangd 通过 P1 收集并进入 index，主要在 F rebuild 使用；candidate orchestration 不临时启动私有 semantic 查询补洞 |

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

Refresh / rebuild (F) → 复用 B 的 binding，供 C1–H 查询前调用
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

B 的 snapshot manifest 覆盖 repository identity/revision、P1 index/P2 graph/domain metadata identity/version、build scope/config/toolchain fingerprint、built_at、build/freshness 与 refresh metadata，并区分 latest attempt 和 last usable snapshot。build scope 必须显式，选定文件的 evaluation index 不可宣称全仓完整。

fresh/stale/building/failed/unknown 语义遵循 roadmap；未知 revision、dirty checkout、index/graph 不一致、源码查询期间变化不能标 fresh。默认阻止不兼容的混合知识；允许调用方显式请求降级并在结果记录限制，不由 P3 替具体 capability 决定接受 stale 的业务政策。查询绑定的 artifacts 不可被就地 rebuild 覆盖；B 先用校验和失败保护，F 实现独立 generation 发布。当前 rg 查询和 snippet 读取仍接触 source workspace，必须验证其与绑定 revision/source fingerprint 一致；不能因为 index 已绑定就忽略源码变化。

F 复用 P1 scanner/provider/test discovery/index 和 P2 projection → role mapper → framework extractor → store，第一版允许全量 rebuild。manual 与外部 scheduler 调用同一单次 entry point，支持 reason/force、revision 未变且配置兼容时 no-op；不实现 scheduler daemon、PR polling 或 Code Host adapter。

## Milestone sequence

所有 Status 均为 `Not Started`。仅当用户开始对应开发任务时设为 `In Progress`；AC 与必需验证全部通过后才 `Completed`，不得自动进入下一 milestone。

| Milestone | Core goal | Dependencies |
| --- | --- | --- |
| P3-A | Task/Change representation 与解析边界 | P1/P2 completed |
| P3-B | KnowledgeSnapshot manifest、freshness 与只读绑定 | A |
| P3-C1 | 多通道 candidate retrieval | A、B |
| P3-C2 | Change ranges → symbol seeds | C1 |
| P3-D | Task/Change-driven Graph Expansion | C1、C2 |
| P3-E | Task Subgraph、snippet materialization 与统一 candidate set | D |
| P3-F | manual/scheduler-invokable refresh integration | B、C1；建议 E 后实施 |
| P3-G | Context Ranking 与 tiering | E |
| P3-H | token selection 与 Context Pack v1 | F、G |
| P3-I | 真实 expansion/context baseline 与 P3 收尾 | A–H |

建议 session 顺序为 A → B → C1 → C2 → D → E → F → G → H → I。F 不依赖 ranking 算法，G 不依赖 rebuild 实现，但两者必须在 H 汇合。C1/C2 分拆是为避免多通道编排和双 revision 坐标映射挤入同一次任务；其他 milestone 不按通道或 trace family 机械拆碎。

## P3-A — Task / Change Representation and Parsing Boundary

- **Status:** Not Started
- **Goal:** 建立共享 typed 输入，使后续检索无需重新解释原始请求和 diff 坐标。
- **Dependencies:** P1/P2 completed；输出供 B、C1/C2 使用。
- **Scope:** 自然语言 Task 的原文、显式/提取 hints（component、symbol、property、action、test intent）及提取来源；结构化 Task；平台无关 Change 的 base/head、files/hunks/ranges、change kind/provenance；受支持 unified diff 解析、坐标规范化、错误与 unresolved 模型。有限 deterministic 解析，未知自然语言保留全文供 text retrieval。
- **Non-goals:** symbol resolution、retrieval orchestration、LLM parser、GitCode ingestion、snapshot 构建、最终 Pack、源码变更。
- **Deliverables:** 输入模型/parser/serialization；对应 input specification 与 contract tests；P3 evaluation case 的输入/标注提纲（不填充未经验证的 expected）。
- **Acceptance Criteria:** Task/Change 均可 round-trip；输入来源与 hint 不混淆为 repository fact；old/new 侧明确；rename/add/delete、零长度 insertion/deletion range 可表达；不支持 binary/combined diff 以显式状态保留而非误解析；路径逃逸与非法范围拒绝；不要求 index/clangd/LLM 才能解析输入。
- **Tests / real validation:** 更新纯模型与 parser tests，覆盖中文 Task、未知组件、overload hint、多文件多 hunk、缺 revision、非法 diff。真实验证仅人工检查所选 P2 case 的 Task 输入及可复现 Change 输入设计，不运行 baseline；本 milestone 不以真实 retrieval 成功为 AC。
- **Known Limitations:** 不承诺通用自然语言意图理解；PR/commit 数据必须由外部转换为平台无关输入。

## P3-B — Knowledge Snapshot Read Contract and Freshness

- **Status:** Not Started
- **Goal:** 在第一条多通道查询前确保所有 evidence 有一致且可核验的知识来源。
- **Dependencies:** A；为 C1–H 提供绑定接口，F 复用同一 manifest。
- **Scope:** typed manifest、repository/revision/build scope 身份、freshness evaluation、读取和验证显式预构建 artifacts、query session binding、source revision/hash 检查；last usable 与 latest attempt 分离。
- **Non-goals:** 自动 rebuild、长期 scheduler、多版本缓存优化、把 graph key 直接当 Git revision。
- **Deliverables:** snapshot/freshness spec、只读 manifest adapter、检查入口和 temporary repository integration fixtures。
- **Acceptance Criteria:** 五种 freshness 语义可区分；old index/new graph 或未知 revision 不得 fresh；dirty/source drift 明确拒绝或降级；覆盖范围不足区别于 stale；合法预构建 snapshot 可绑定并供查询复用；缺失/损坏 manifest 不能静默产生空 fresh snapshot；状态和诊断可序列化。
- **Tests / real validation:** 临时 Git repository 的 revision transition、dirty source、混合 artifact、工具/规则配置变化、scope mismatch、读取期间变化；人工核对 P2 fixture preparation scope 可被 manifest 表达。真实大仓库 refresh 尚非本 milestone 验收条件。
- **Known Limitations:** 不负责生产已有 index 的 revision 证明；没有可信 manifest 的遗留 artifact 为 unknown，需要 F rebuild 或显式验证流程。

## P3-C1 — Multi-channel Candidate Retrieval

- **Status:** Not Started
- **Goal:** 将 Task hints 或显式 Change seeds 转换为统一、可追溯的候选集合。
- **Dependencies:** A、B；供 C2 映射后重新召回及 D expansion 使用。
- **Scope:** 上述 P1/P2 typed adapters、有限 query planning、Text/Symbol/Reference/Call/Test/直接 Graph 候选、通道预算、identity-based dedup、provenance 合并、channel availability/completeness。候选模型在 E 汇总时收敛，不冻结最终 Pack。
- **Non-goals:** changed range 语义映射、递归任务图扩展、最终排序/selection、直接依赖 rg/clangd/SQLite 私有协议。
- **Deliverables:** retrieval service 与 candidate result types、对应 spec、真实 P1 接口 integration tests，首批独立 P3 人工 expected cases。
- **Acceptance Criteria:** Task 和结构化 Change seed 可走相同通道；同名不同 identity 保留；查询顺序不影响 canonical output；empty/unsupported/backend failure/truncated 分开；每个 candidate 有 snapshot/source/query provenance；有限 candidate limit 不被表述为最终上下文完整性。
- **Tests / real validation:** 临时 C++ repository 使用真实 P1 facade/index/rg 验证跨通道重复、空 test mapping、工具缺失与错误传播；用户显式触发 Button/Text/Menu 小范围 candidate smoke，复用 P1 revision 检查和标注 anchors，不读取 expected 生产候选。
- **Known Limitations:** C1 只消费显式 changed symbol seeds；普通 diff 的 symbol seeds 在 C2 接通。没有可靠 test mapping 时可返回文本测试候选，但必须区分证据等级。

## P3-C2 — Change Range to Symbol Mapping

- **Status:** Not Started
- **Goal:** 在可证明范围内把 Change 文件/hunk/range 转为语义 seeds，并保持双侧 provenance。
- **Dependencies:** A、B、C1；输出供 D，映射后复用 C1 检索。
- **Scope:** 按 revision side 查询 P1 file/symbol ranges；enclosing/overlap 关系分类；新增、删除、重命名、多 symbol hunk、无法映射和 ambiguity；head 支持上下文与 base-only evidence 分离。
- **Non-goals:** 猜测跨 revision symbol identity、修改 P1 C++ backend、Git diff 获取平台集成、从文本补出语义关系。
- **Deliverables:** mapper、Change retrieval integration、mapping spec、revision-bound Change cases。
- **Acceptance Criteria:** 可证明的 changed symbols 保留 identity 和范围依据；多个相交 symbol 不静默选一个；P1 范围不足保持 unresolved；缺 base snapshot 不用 head 行号替代 deletion；有两个兼容 side snapshots 时各自映射并不跨侧合并；未解析 diff 仍进入 file/range candidates。
- **Tests / real validation:** 临时双 revision Git/C++ fixture 验证行移动、rename、删除、宏、hunk 跨函数、declaration/definition；用户显式触发真实 ArkUI Change smoke，使用人工确认的 base/head 和 hunks。若尚无可用真实 revision pair，保持该真实验收未完成，不能用伪造相同 base/head 顶替。
- **Known Limitations:** changed symbol 不等于行为影响范围；不要求所有 hunk 都能映射。

## P3-D — Task / Change-driven Graph Expansion

- **Status:** Not Started
- **Goal:** 根据任务/变更有界选择和组合已有 graph 与 trace 观察，扩大相关证据召回。
- **Dependencies:** C1、C2；输出供 E。
- **Scope:** 显式 policy 配置/version；Task/Change seeds、上下游方向、relation family、适用 trace query；per-seed 与全局 node/edge/query/path 限额；去重、stop reason、ambiguity 与已知缺口透传。
- **Non-goals:** 重写 P2 BFS/trace、补齐 19 条 frozen missing relation、通用 Lifecycle Trace、虚拟调用/宏/callback 推断、token selection。
- **Deliverables:** expansion orchestrator/result、expansion spec、P2 case 对应 P3 expansion annotations 与 tests。
- **Acceptance Criteria:** 相同 snapshot/input/policy 可重复；所有扩展均可追溯 seed 与真实 relation；跨组件扩展必须有事实依据；操作 binding 不转为 CALL；预算限制显式说明；Menu layout 多 algorithm、Overlay 多 Close path 保留；缺关系时可召回独立证据但不能宣称 P2 trace 已修复。
- **Tests / real validation:** cycle、多 seed 汇合、预算刚好/超限、unsupported relation、partial graph；用户显式运行四类真实 P2 trace 场景的 P3 expansion smoke，同时报告原 P2 status 与新增任务相关 evidence，指标遵循下方 evaluation 设计。
- **Known Limitations:** expansion 不能超过 P1/P2 已有事实能力；role catalog 限制和 unknown components 原样可见。

## P3-E — Task Subgraph and Context Candidate Materialization

- **Status:** Not Started
- **Goal:** 将召回与 expansion 观察整理为可独立供 ranking 消费的任务视图及证据单元。
- **Dependencies:** D（复用 B/C1/C2）；供 G/H 使用。
- **Scope:** Task/Change subgraph extraction、关系端点和 supporting evidence 闭包、trace-local association 独立表达、显式边界；只读 snippet materialization、range/hash 校验、重叠片段去重、统一 `ContextCandidateSet`。
- **Non-goals:** induced 全图承诺、ranking、token selection、生成自然语言分析结论、扩展新的 parser/graph relation。
- **Deliverables:** subgraph extractor、candidate materializer、内部 candidate/ranking input v1 spec；引用既有 P2 evidence spec，不复制定义。
- **Acceptance Criteria:** 所有 relation endpoints 可解析；文本命中和语义 evidence 可区分；snippet 来自所声明 revision/range；缺 source/range 返回明确限制；无悬空 candidate dependency；unknown/ambiguous/truncation 不在 extraction 中消失；序列化/反序列化后身份和关联保持；不需要 ranker 或 LLM。
- **Tests / real validation:** 非 induced BFS 结果、共享 endpoint、association 非 edge、跨 revision snippet 拒绝、source drift、overlapping ranges；用户显式检查 Button creation、FontWeight property、Menu layout/overlay 的真实 subgraph/snippet provenance。
- **Known Limitations:** subgraph 完整性仅相对于已观察和声明的检索范围；源码不可得时不能提供伪造 snippet。

## P3-F — Refresh / Rebuild Integration

- **Status:** Not Started
- **Goal:** 让 B 的知识契约获得可调用、失败可见的真实生产和刷新流程。
- **Dependencies:** B、C1；建议 E 后执行以验证真实查询消费者，H 依赖本 milestone。
- **Scope:** 手动 command/service 与 scheduler-invokable 单次入口；revision check、reason/force、no-op、全量 P1/P2 rebuild adapter、独立 generation、原子发布 manifest、失败保留 last usable、单 writer 排他/冲突拒绝；配置化 build coverage 与 compile database 输入。
- **Non-goals:** scheduler daemon、自动拉取/checkout target、PR polling、增量 index/graph、新 semantic backend 或全仓无限重试。
- **Deliverables:** shared refresh service/CLI、P1/P2 build adapters、生命周期 spec、refresh integration tests 与可复用真实 smoke 入口。
- **Acceptance Criteria:** 不调用带 frozen expected 的 evaluation harness 生产知识；使用公开 P1/P2 primitives；manual/scheduler 调用同一服务；revision 未变且配置兼容可 no-op，force 可重建；任一 stage 失败或 revision/source 漂移均不发布 fresh；旧绑定保持原 generation；writer 冲突显式失败；输出可被 C1–E 使用。配置全仓 scope 时覆盖声明的 scanner 范围，失败/未支持文件有报告；小范围 smoke 不宣称全仓验收。
- **Tests / real validation:** temporary repository 真实 rebuild/read round-trip、失败注入在 adapter I/O 边界、manifest 发布失败、两次刷新冲突、rule/config 变化；用户显式触发 ArkUI 指定 scope refresh → retrieval/expansion，再做配置全仓范围的验收并记录 coverage/未支持项。缺外部工具/compile configuration 不算通过。
- **Known Limitations:** 第一版全量 rebuild 成本可能高；性能优化需测量后另立任务，不作为提前实现 incremental 的理由。

## P3-G — Context Ranking and Tiering

- **Status:** Not Started
- **Goal:** 对 E 的候选做可解释排序，表达 Tier 1/2/3 的任务相关性。
- **Dependencies:** E；H 消费结果，可与 F 独立验收。
- **Scope:** deterministic feature-based ranker、target/changed evidence、direct dependency、graph distance、channel/provenance strength、test relevance、tiers 和稳定 tie-break；同一 ranker 支持 Task/Change。
- **Non-goals:** token selection、LLM reranker 依赖、用 ranking 解决 symbol ambiguity、创建新的事实。
- **Deliverables:** ranked candidate model、ranking policy/spec、独立人工 relevant/required annotation、ranking tests。
- **Acceptance Criteria:** 输入为 E `ContextCandidateSet`；输出引用原 candidate 且保留全部证据与限制；逐项 tier/features/reason 可解释；输入顺序变化不改变结果；低置信候选不被升级为确定 relation；Task/Change must-have priority 可验证。
- **Tests / real validation:** ties、缺 features、ambiguous targets、duplicate snippets、optional text test vs semantic test mapping；用户显式在相同 P3 真实 candidate sets 比较无任务排序与 ranking，记录 relevant/required evidence 排位，不据实际排序反填 gold。
- **Known Limitations:** 分数用于排序，不是正确性概率；不承诺每个 Tier 1 项都能塞入任意 budget。

## P3-H — Token Selection and Context Pack v1

- **Status:** Not Started
- **Goal:** 输出可直接供后续 P4 消费的稳定、可追溯且受预算约束的 Task/Change Context Pack。
- **Dependencies:** F、G（复用 A–E）；I 验收完整链路。
- **Scope:** tokenizer adapter/identity、完整序列化输出计量、上下文 budget 与可配置外部预留；依赖一致的 selection、snippet 安全裁剪、include/exclude reason；Task 与 Review/Change 共享的 versioned Context Pack envelope。
- **Non-goals:** Agent/LLM invocation、ReviewFinding、最终评论、UT 生成、为了压缩而改写源码或丢失 provenance。
- **Deliverables:** selector、serializer、Context Pack v1 稳定 schema/spec、Task/Change 示例与 end-to-end 入口。本 milestone 完成时冻结 schema，后续破坏性修改必须显式升级版本。
- **Acceptance Criteria:** Pack 包含 input、target/changed/related symbols、call/framework relations、snippets、tests、similar/mock evidence 的可用性、snapshot/revision、provenance、selection reasons、tokenizer/budget/actual cost 和 partial/unknown 状态；空或 unavailable 类别可表达，不要求伪造内容。全部输出（含元数据）计量不超 budget；必需项或最小 envelope 放不下时返回明确 budget failure/不完整状态，不能静默越界。预算被裁掉的依赖与上游缺事实分开报告；selected relation 的端点和必要 supporting evidence 不悬空；schema round-trip 与版本不兼容行为明确。
- **Tests / real validation:** 中文/C++/Unicode、精确预算边界、零/过小预算、单个超大 symbol、共享片段、裁剪后 range、无候选、stale downgrade、base-only deletion、schema round-trip；用户显式运行真实 Task/Change packs，在固定 tokenizer 和多档 budget 下人工核验 source/provenance、missing dependency 和成本。
- **Known Limitations:** 不保证极小 budget 下 context 完整；精确 token cost 只对记录的 tokenizer/serialization 有效，不能把估算当成硬上限证明。

## P3-I — Real Expansion / Context Baseline and Phase Closure

- **Status:** Not Started
- **Goal:** 对整个 P3 链路建立可重现真实基线，并对照 phase-map DoD 收尾。
- **Dependencies:** A–H 全部完成，人工 expected 已在执行前冻结。
- **Scope:** 复用各 milestone annotations，整合 Task/Change、snapshot/refresh、retrieval/expansion/ranking/selection 的真实 suite、指标、失败分类和报告入口；记录局限及分阶段成本。
- **Non-goals:** 修改 P2 frozen expected/算法、追求全部 P2 traces complete、P4 agent 或 P5 review/repair benchmark、P6 全面 ablation。
- **Deliverables:** 独立 P3 revision-bound dataset/fixtures、evaluation command、`docs/evaluation/p3-context-baseline.md`、DoD 对照及简洁 completion evidence；runtime report 不入 Git。
- **Acceptance Criteria:** 下方最小真实覆盖与指标全部可复现；无 provenance/snapshot/budget/expected-conformance 回归；known missing 能力单列且不得伪装恢复；所有必需测试和用户显式触发的真实/strict full 验证通过；对照 phase-map P3 DoD 1–11 给出证据后才将 Phase 标 Completed 并归档。
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
- **Provenance / uncertainty:** source/revision/identity/hash 可追溯率，ambiguity/gap/truncation 保留情况，新增无证据 relation 数；无证据关系、身份错误或静默丢失重要 uncertainty 为硬失败。
- 非适用维度报告 N/A，不当作 0 或 1；空 gold/empty output 的分母规则在 evaluation spec 中冻结，并同时报告 case 数与分母。按 case/component/Task-vs-Change 分解，再给 macro aggregate，不能用成功 case 隐藏失败。

首版不凭空承诺 RCR 达到某百分比或全部 dependency 命中；C1/D 在执行前冻结逐 case 可实现 evidence 预期，I 要求这些 expected 全部符合，并解释全部 missing。质量门槛为：可得且标为必需的事实符合预期、无伪造关系、provenance 完整、freshness 判断正确、输出不超预算；保留上游缺口不会阻止通过，但未完成必需验证会阻止 Completed。

### Validation discipline

遵循当前 AGENTS.md：开发时新增/更新行为测试，但 Codex 不主动执行测试命令；trusted Stop Hook 仅运行工作树新增/修改的 `test_*.py`。Hook 不可用或未 trusted 必须报告未验证，不手动补跑。任何本计划列出的真实 ArkUI smoke/baseline、全仓 refresh 验收、strict full 和昂贵验证均由用户显式触发；未执行的必需项保留待验收，不能提前将 milestone 设 Completed。

本 session 仅做文档整理与 `git diff --check`，不运行 P2 baseline 或 P3 测试。既有工作树产品代码、测试、Hook 修改和 frozen expected 全部保留；不导出 patch、逐命令日志或新的 runtime snapshot。

## P3 Definition of Done traceability

| Phase-map P3 DoD | Delivery / final validation |
| --- | --- |
| 1 Task → structured Pack | A、C1、D–H；I |
| 2 Change revisions / hunks / symbols | A、C2、B、H；I |
| 3 shared retrieval channels | C1、C2、D；I（unsupported 明示） |
| 4 retrieval / final context separation + budget | C1、E、G、H；I |
| 5 source traceability and inclusion/exclusion | B、C1–E、G、H；I |
| 6 snapshot / freshness | B、F；I |
| 7 manual + scheduler-invokable refresh | F；I |
| 8 refresh failure cannot publish partial fresh | B、F；I |
| 9 Pack snapshot identity | B、H；I |
| 10 context metrics | C1–H 持续标注/验证；I 汇总 |
| 11 bounded graph/source context | C1、D、E、H；I |

## Next session: P3-A only

建议下一 session 仅实现 A 的 typed Task/Change model、有限 parser、序列化/输入错误、old/new range 语义、对应 spec 与 tests。开始时只将 P3-A 和 Phase 设为 In Progress；不实现 retrieval、KnowledgeSnapshot build、Graph Expansion 或 Context Pack，不自动进入 B。若必需 Hook 验证未通过或未执行，保持 In Progress 并报告。
