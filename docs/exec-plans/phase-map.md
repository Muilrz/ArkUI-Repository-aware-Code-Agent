# Development Phase Map

## 1. Purpose and authority

本文把 [Technical Roadmap](../architecture/technical-roadmap.md) 转换为可验收的工程阶段。Roadmap 决定长期架构，本文件决定 Phase 边界和 Definition of Done，`active/` execution plan 决定当前 milestone 范围。

P0/P1/P2 是已完成历史阶段；P3-A～E 是已完成历史能力。未完成的 P3 后续、P4 Agent Runtime 和旧 P5 Engineering Capabilities 路线已由 [ADR-0005](../decisions/ADR-0005-code-review-service-pivot.md) 取代。新产品阶段使用独立 R0–R6 编号，避免把新路线伪装成旧 Phase 已完成内容。

## 2. Global principles

### 2.1 Service-first product boundary

Code Review Service 自己拥有 GitCode integration、scheduler、review users、revision dedup、job lifecycle、review execution 和 result persistence。系统不建设 generic Agent Runtime。

### 2.2 Provider-based knowledge

Repository Knowledge Service 由 `DocsKbProvider`、`LiveSourceProvider`、`P1Provider` 和 `P2Provider` 组成。Live Source 对当前 PR revision 的源码事实具有最终权威；P1/P2 是可复用增强，不是 availability gate。

### 2.3 Provider-level freshness

Freshness 分 provider 报告。P1/P2 stale 时刷新或排除，Review 可以降级为 Docs + Live Source。公共架构不要求统一 KnowledgeSnapshot、generation、semantic shard 或 incremental lifecycle。

### 2.4 Stable service contracts

最小 review identity 是 `repository + pr_id + head_sha + review_policy_version`。Review input、ReviewContextPack、ReviewFinding、job/result state 和 MCP tools 均使用平台无关 model；GitCode schema 隔离在 provider。

### 2.5 MCP/Skill boundary

MCP 是 Service application API 的标准接口层。Skill 只描述外部 Agent 如何组合 MCP tools。Scheduler、polling、filter、dedup、knowledge update 和 persistence 不进入 Skill。

### 2.6 Preserve historical facts

P1/P2 completed plan、spec、baseline、frozen fixture 和 P3-A～E 已实现 contract 不因新架构重写。Architecture 说明未来消费方式，spec 说明当前代码事实。

### 2.7 Evaluation starts early

每个 R phase 都增加与其行为对应的测试和 evaluation evidence；R6 汇总成正式 benchmark、ablation 与 hardening。No-Issue cases、false positive、revision provenance 和 degradation 必须从 Review Engine 初期纳入。

## 3. Historical phases

| Phase | Status | Continuing role |
| --- | --- | --- |
| P0 — Engineering Foundation | Completed | 工程、配置、测试和可观测基础可复用 |
| P1 — Repository Intelligence | Completed | 通过 `P1Provider` 提供 symbol/definition/reference/caller/callee/tests |
| P2 — ArkUI Code Graph | Completed | 通过 `P2Provider` 提供 ArkUI-specific semantic relations |
| P3-A～E — Task / Change Context contracts | Completed milestones in a superseded phase | 已实现 contract 保留，可由新路线选择性复用 |
| P3 remaining route | Superseded | 不继续 P3-F incremental lifecycle/G/H/I |
| P4/P5 old route | Superseded before execution | 不建设 Agent Runtime，不推进旧 Agent/UT capability 路线 |

P3 历史状态详见 [`superseded/P3-task-change-context.md`](superseded/P3-task-change-context.md)。`Superseded` 不表示整个 P3 Completed，也不否定 A～E 的完成事实。

# 4. R0 — Review Service Foundation

## Goal

建立平台无关、可测试的 Code Review Service 基础边界，使后续 GitCode、Knowledge、Review Engine 和 MCP 能在稳定 domain/application ports 上独立演进。

## In Scope

- review package/module dependency direction；
- `ReviewIdentity` 最小字段与 canonical equality/serialization；
- 平台无关的 ReviewRequest、ReviewJob、ReviewResult、ReviewFinding 基础 model；
- severity `Critical/High/Medium/Low` 与 finding 必填字段边界；
- Review Job Manager、Result Store、KnowledgeGateway、ReviewEngine 的 ports；
- service configuration/loading boundary；
- deterministic lifecycle/error taxonomy、logging/trace correlation 基础；
- unit-level contract tests and fixtures。

## Out of Scope

- GitCode API/credentials/HTTP；
- real PR polling、author filtering 和 durable revision dedup；
- provider implementation 或 knowledge refresh；
- review reasoning/LLM/category detection；
- MCP tools、auto review 和 Skill；
- 修改 P1/P2/P3 frozen semantics。

## Definition of Done

1. Domain model 不引用 GitCode 私有 schema、MCP transport 或具体 storage。
2. `ReviewIdentity` 明确包含 `repository + pr_id + head_sha + review_policy_version`，具有确定 serialization/equality。
3. ReviewFinding model 至少包含 file、location/range、category、severity、title、description、evidence、reasoning、suggestion、confidence，severity 仅允许四级枚举。
4. Job/result/knowledge/engine ports 的职责、dependency direction 和失败类型由 spec 与 tests 固定。
5. Service 可以用 test doubles 走通一个不含真实 GitCode/knowledge/reasoning 的 application orchestration contract，且不伪装后续能力已实现。
6. 配置和 trace/correlation 基础不承载 secrets 或平台私有逻辑。
7. 对应 tests 通过，active plan Acceptance Criteria 满足后才标记 Completed。

# 5. R1 — GitCode Integration & Review State

## Goal

可靠地把 GitCode PR/revision 转换为平台无关 review work，并持久化 review identity/state，防止同一 head/policy 重复处理。

## In Scope

- `GitCodeProvider` read adapter；
- PR metadata、author、base/head SHA、diff、changed files/hunks normalization；
- authentication/configuration、pagination、bounded retry/error mapping；
- review users set/get application APIs；
- `repository + pr_id + head_sha + review_policy_version` dedup；
- job/result durable state needed for claim/retry/restart；
- manual `review_pr` ingestion path without Review Engine implementation。

## Out of Scope

- Repository Knowledge providers；
- LLM/review reasoning；
- MCP transport；
- background scheduler/auto review；
- GitCode comment publishing unless separately planned later。

## Definition of Done

1. GitCode-specific fields/errors stop at adapter boundary。
2. PR input produces deterministic platform-neutral change model with exact head SHA and hunks。
3. User filter is configurable and evaluated before expensive downstream work。
4. Same review identity is not double-claimed across retry/restart/concurrent submission；new head or policy is distinct。
5. State transitions and failed/retry behavior are queryable and covered by tests。
6. Provider failure never creates a false successful review record。
7. Credential/secret handling and redaction meet documented safety contract。

# 6. R2 — Repository Knowledge Service

## Goal

实现 provider-based KnowledgeGateway，为目标 review revision 构建可追溯 evidence，并在 P1/P2 stale 时安全降级。

## In Scope

- common provider capability/evidence/status contract；
- `DocsKbProvider` for docs/kb、`context_registry`、`kb_search`；
- `LiveSourceProvider` for Git/filesystem/`rg` at explicit revision；
- `P1Provider` adapter over existing P1；
- `P2Provider` adapter over existing P2；
- provider-level freshness、status diagnostics；
- update/rebuild/status application APIs；
- KnowledgeGateway query, normalization, provenance, budget and degradation；
- Docs + Live Source minimum review context path。

## Out of Scope

- unified KnowledgeSnapshot/generation requirement；
- mandatory dependency-driven incremental knowledge、TU invalidation、shard/ownership/P1 delta/P2 incremental projection；
- changing P1/P2 semantics or baseline；
- `SemanticMcpProvider` dependency；
- Review Engine reasoning or MCP transport。

## Definition of Done

1. 四个 provider 通过统一 capability/status/evidence boundary 调用，同时保留各自 source/revision/version。
2. Live Source 对目标 head revision 可验证读取，并裁决当前源码事实冲突。
3. Status 至少区分 ready/stale/unavailable/refreshing/error，按 provider 返回而非统一 snapshot gate。
4. P1/P2 stale facts 不会作为当前确定 evidence；refresh 或 exclusion/degradation 可审计。
5. P1/P2 unavailable 时 Docs + Live Source path 仍可返回有界 context；Live Source 目标 revision 不可用时明确失败。
6. `update_repo_knowledge`、`rebuild_repo_knowledge`、`get_knowledge_status` application contract 已实现并测试。
7. P1/P2 frozen tests/baseline 不因 adapter 改写。

# 7. R3 — Review Engine

## Goal

从标准化 change 与 Repository Knowledge evidence 构建 `ReviewContextPack`，产生少而准确、可定位、可解释的结构化 findings。

## In Scope

- ReviewContextPack assembly、ranking、budget、gaps 与 provider provenance；
- fixed review policy/version；
- Stability category；
- Memory / Resource / Lifetime category；
- Functional Correctness category；
- ReviewFinding parsing/validation/normalization；
- zero-finding success；
- evidence/revision/category/severity/location validation；
- initial review benchmark including No-Issue cases。

## Out of Scope

- generic Agent Runtime or arbitrary skill execution；
- source edits、UT generation、build/test/repair；
- auto polling；
- MCP transport；
- mandatory P2 evidence；
- automatic GitCode comment publishing。

## Definition of Done

1. Engine 只依赖 platform-neutral request/context，不直接调用 GitCode/storage/provider internals。
2. ContextPack 包含 change、provider status/revision、included evidence、gaps/degradation 和 budget。
3. 三个首批 category 有明确 policy、prompt/model boundary（若使用模型）、output validation 和 tests。
4. Finding 含 R0 固定必填字段和四级 severity，关键 claim 可追溯到目标 revision evidence。
5. Invalid/unlocated/unsupported findings 被拒绝或显式降级，不静默发布。
6. No-Issue cases 可成功返回 zero findings，benchmark 报告 false positives。
7. Docs + Live Source 与增加 P1/P2 的初始 ablation 可复现。

# 8. R4 — MCP Server

## Goal

以稳定、安全的 MCP tools 暴露已有 Code Review Service 和 Repository Knowledge Service application APIs，不复制业务逻辑。

## In Scope

- `review_pr`、`review_diff`、`get_review_result`；
- `update_repo_knowledge`、`rebuild_repo_knowledge`、`get_knowledge_status`；
- `set_review_users`、`get_review_users`；
- `start_auto_review`、`stop_auto_review`、`get_review_status` 的 transport contract（调用 R5 前可明确 unsupported/not enabled）；
- schema/versioning、authentication/authorization、input limits、error mapping；
- MCP integration/contract tests and usage documentation。

## Out of Scope

- Agent planning/state/memory；
- review reasoning duplication；
- scheduler implementation；
- Skill；
- platform-specific data leakage。

## Definition of Done

1. 所有规划 tools 有明确 schema、sync/async/result identity、错误和权限 contract。
2. MCP handler 只调用 application APIs，无 Review Engine/Knowledge/GitCode 业务逻辑复制。
3. Invalid/oversized/unauthorized input 有稳定、无 secret 泄漏的失败响应。
4. ReviewFinding 和 provider freshness/degradation 可无损序列化。
5. Auto-review tools 在 R5 未启用时返回显式 capability status，不伪装成功。
6. MCP contract/integration tests 通过，外部 client 可完成 manual review/result/status workflow。

# 9. R5 — Auto Review & Code Review Skill

## Goal

交付 Service-owned 的可靠自动 review，以及只组合 MCP tools 的可移植 Code Review Skill。

## In Scope

- PR Poller / Scheduler lifecycle；
- GitCodeProvider → user filter → head/policy dedup → job → persist flow；
- configurable interval、start/stop/status；
- restart/retry/backoff、overlap control、operational diagnostics；
- Code Review Skill instructions for MCP-capable Agents；
- skill validation against Codex/Claude-style clients where available。

## Out of Scope

- 在 Skill 中实现 polling/scheduler/dedup/persistence；
- generic Agent Runtime；
- arbitrary engineering workflow；
- UT Development / Repair；
- requiring an external Agent to keep Service alive。

## Definition of Done

1. Scheduler 自动 flow 严格按 provider/filter/dedup/job/persist 边界运行。
2. 同一 identity 在重复 tick、overlap、retry 和 restart 下不重复 review。
3. Review users、interval、start/stop/status 可配置且状态可观测。
4. Provider/review failure 有 bounded retry/backoff，不丢失可诊断 state。
5. Skill 只引用 MCP public tools，不包含后台循环、平台凭据或私有存储逻辑。
6. 禁用/停止 auto review 不删除历史 result，恢复行为由 contract 固定。
7. End-to-end smoke 覆盖 new PR、新 head、filtered user、duplicate head、failure/recovery。

# 10. R6 — Evaluation & Hardening

## Goal

形成正式 Code Review benchmark、provider/engine ablation 与生产级 reliability、security、performance hardening。

## In Scope

- representative ArkUI PR/diff benchmark；
- Stability、Memory/Resource/Lifetime、Functional Correctness 和 No-Issue cases；
- finding precision/recall/FPR、category/severity/location/evidence accuracy；
- provider freshness/degradation correctness；
- diff-only vs Docs+Live Source vs +P1 vs +P2 ablation；
- GitCode/MCP/scheduler/result-store resilience；
- load/latency/cost/resource limits；
- authz、secret redaction、input/diff abuse and prompt-injection hardening；
- operational runbook、upgrade/recovery validation。

## Out of Scope

- 新的 generic Agent product；
- 用 benchmark 驱动修改 frozen P1/P2 semantics 而无独立 scope；
- 把 unsupported case 计作成功或只报告 aggregate；
- 以增加评论数量替代 review quality。

## Definition of Done

1. Dataset、labels、revision、sampling、No-Issue coverage 和 scorer 可复现。
2. 核心质量指标按 category/component/provider state 分解并报告置信/分母。
3. False positive、evidence validity 和 revision alignment 达到冻结 release gate。
4. Docs+Live Source minimum path 与 P1/P2 增益/限制通过 ablation 明确。
5. Duplicate suppression、restart/retry、provider outage、MCP error 和 storage recovery 通过 fault tests。
6. Security review 覆盖 credentials、authorization、untrusted PR/docs content 和 output handling。
7. Performance/cost budgets 和 operational SLO/alerts/runbook 冻结并通过验收。
8. Known limitations 单列，不通过 unsupported/unknown 隐藏失败。

# 11. Dependency and execution rules

主交付顺序：

```text
P0/P1/P2 historical foundations
               ↓
R0 → R1 → R2 → R3 → R4 → R5 → R6
```

这表示默认验收依赖，不禁止在清晰 port 后并行准备数据或测试，但不得把后续能力提前计入前一 Phase DoD。R4 可以先暴露 R5 control tool schema，但在 R5 完成前必须返回显式未启用状态。

每个 active execution plan 必须记录：

- Goal；
- Status；
- dependencies；
- in scope / out of scope；
- deliverables；
- acceptance criteria；
- validation plan；
- risks/decisions。

Status 统一使用：

- `Not Started`
- `In Progress`
- `Blocked`
- `Completed`
- `Superseded`

开始实现时只将当前 milestone 设为 `In Progress`。只有 Acceptance Criteria 与必需测试全部通过才设为 `Completed`。路线被替代但未完成时设为 `Superseded` 并移至 `superseded/`，不得伪装成完成。

当前 active plan 是 [`active/R0-review-service-foundation.md`](active/R0-review-service-foundation.md)，本次架构迁移不授权开始任何 R0 产品代码。
