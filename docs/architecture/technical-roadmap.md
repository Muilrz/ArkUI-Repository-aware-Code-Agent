# Arkui-repository-aware-code-review-service 技术路线

## 1. 产品目标

本项目面向 OpenHarmony ArkUI Ace Engine 大型 C++ 仓库，构建可独立部署和调用的：

- Repository-aware Code Review Service；
- Repository Knowledge Service；
- MCP Server；
- Code Review Skill。

核心产品是 Code Review Service，而不是通用 Engineering Agent。系统不建设 generic Agent Runtime，也不承担通用 planning、任意工具编排、coding loop 或 UT Development / Repair。Codex、Claude 和其他 Agent 通过 MCP 与 Skill 接入，但不是 Service 运行、轮询和持久化的宿主。

本文件是长期产品架构的最高层 source of truth。专题细节分别见：

- [Code Review Architecture](code-review-architecture.md)
- [Repository Knowledge Architecture](repository-knowledge-architecture.md)
- [ArkUI Code Graph Architecture](code-graph-architecture.md)
- [ADR-0005](../decisions/ADR-0005-code-review-service-pivot.md)

## 2. 总体架构

```text
GitCode PR / Diff
        ↓
Code Review Service
├── GitCodeProvider
├── PR Poller / Scheduler
├── Review User Filter
├── Revision Dedup
├── Review Job Manager
├── Review Engine
└── Result Store
        ↓
KnowledgeGateway
        ↓
Repository Knowledge Service
├── DocsKbProvider
├── LiveSourceProvider
├── P1Provider
└── P2Provider
        ↓
ReviewContextPack
        ↓
Structured Review Findings
        ↓
MCP Server
        ↓
Code Review Skill
        ↓
Codex / Claude / Other Agents
```

图中的 KnowledgeGateway 是 Code Review Service 到 Repository Knowledge Service 的唯一业务入口。Review Engine 消费由它构建的 `ReviewContextPack`，结果写入 Result Store；MCP Server 暴露 Service 能力，Skill 说明外部 Agent 如何调用这些标准接口。

核心原则：

- GitCode 私有 API 和数据结构封装在 `GitCodeProvider`。
- 自动发现、过滤、去重、排队、执行与持久化由 Service 自己完成。
- Repository Knowledge 是 provider-based service，不以统一 snapshot/generation 数据库为前提。
- Live Source 始终按目标 PR revision 读取，是源码事实的最终 source of truth。
- P1/P2 被复用而不被重写；stale 时降级或刷新，不能阻塞最低可用 review。
- ReviewFinding 必须定位到变更并带可追溯 evidence；允许 zero findings。
- MCP 是接口层，Skill 是调用说明，两者都不实现通用 Agent Runtime。
- Evaluation 从 R0 开始持续建设，R6 形成正式 benchmark 和 hardening。

## 3. Code Review Service

### 3.1 Service responsibilities

Code Review Service 负责：

- 从 GitCode 读取 PR metadata、diff、changed files/hunks 和 revision；
- 按配置的 review users 提前过滤候选 PR；
- 用稳定 review identity 去重；
- 管理 review job 状态、并发、retry、取消和结果；
- 通过 KnowledgeGateway 获取与本次 change 对齐的 context；
- 运行 Review Engine 并生成结构化 findings；
- 持久化 result、provider freshness、degradation 和 diagnostics；
- 支持显式 `review_pr` / `review_diff` 与后台 auto review。

Service 不负责通用 Agent planning、任意 skill 调度、源码修改、build/test/repair loop 或外部 Agent 的长期 memory。

### 3.2 Review identity

最小 review identity 固定为：

```text
repository + pr_id + head_sha + review_policy_version
```

同一 identity 不因 poll 重复创建成功 review；`head_sha` 或 `review_policy_version` 变化会产生新 identity。手动 force/retry、并发 claim、finding fingerprint 和发布策略由后续 spec 定义，但不能削弱该最小身份。

### 3.3 Trigger flow

自动 review 属于 Service：

```text
Scheduler
    ↓
GitCodeProvider
    ↓
review user filter
    ↓
head SHA + policy dedup
    ↓
Review Job Manager
    ↓
review
    ↓
persist result
```

第一阶段以 polling 为主；未来可加入 webhook，但不得改变平台无关的 ReviewRequest/ReviewResult 边界。轮询周期是配置，不硬编码进 Skill。

## 4. Repository Knowledge Service

Repository Knowledge Service 聚合多种 evidence provider，而不是要求所有知识先进入一个全局、一致、持久化的 `KnowledgeSnapshot`。

### 4.1 Providers

`DocsKbProvider`：

- 消费 ArkUI docs/kb、`context_registry`、`kb_search`；
- 提供架构、组件、领域规则和术语知识；
- 结果保留文档来源、revision/version 和匹配原因。

`LiveSourceProvider`：

- 使用 `rg`、Git 和 filesystem；
- 在明确 repository revision 下读取 diff 周边、声明、实现、配置和测试源码；
- 对当前 PR revision 的源码事实具有最终裁决权。

`P1Provider`：

- 复用已完成的 P1 Repository Intelligence；
- 提供 symbol、definition、reference、caller、callee 和 tests；
- 保留 P1 identity、provenance 和 unsupported/ambiguous 语义。

`P2Provider`：

- 复用已完成的 P2 ArkUI Code Graph；
- 提供 ArkUI-specific role、framework relations 和 bounded traces；
- 保留 frozen P2 relation semantics、evidence 和 partial/ambiguous 状态。

未来可增加 `SemanticMcpProvider`，但当前服务的 availability、正确性和验收不得依赖它。

### 4.2 Provider-level freshness

Freshness 按 provider 报告，例如：

```json
{
  "repository_revision": "B",
  "docs": {"status": "ready", "revision": "B"},
  "live_source": {"status": "ready", "revision": "B"},
  "p1": {"status": "stale", "revision": "A"},
  "p2": {"status": "stale", "revision": "A"}
}
```

Status 至少区分 `ready`、`stale`、`unavailable`、`refreshing` 和 `error`。每个 provider 可以带 version、checked_at 和 diagnostics。Provider 声明 `ready` 时，其 revision 必须与目标 review revision 对齐或具有明确定义的兼容语义。

不再要求统一 Snapshot freshness，也不要求所有 provider 同时 ready 才 review。P1/P2 stale 时只能：

- 刷新到目标 revision 后使用；或
- 排除其 current-fact claims，并以 `Docs + Live Source` 降级继续。

严禁把 revision A 的 P1/P2 fact 无标记地当作 revision B 的确定事实。降级状态必须进入 `ReviewContextPack` 和 ReviewResult provenance。

### 4.3 Update and rebuild

Repository Knowledge Service 提供显式 update/rebuild entry point。每个 provider 自己决定 refresh、cache、index 或 rebuild 机制，并报告自己的状态；Service 不规定统一物理存储或统一 generation。

旧 dependency-driven incremental knowledge、TU invalidation、semantic shard、fact ownership、P1 delta、P2 incremental projection、KnowledgeSnapshot generation 和 SnapshotQueryView 可作为历史实现或未来 provider 内部优化保留，但不再是产品关键路径，也不能泄漏为 KnowledgeGateway 的强制 contract。

## 5. Review context contract

Review 输入至少包含：

```text
PR metadata
+ diff
+ changed files/hunks
+ Docs evidence
+ Live Source evidence
+ P1 facts
+ optional P2 graph evidence
```

`ReviewContextPack` 是一次 review 的有界、结构化输入，至少表达：

- repository、PR/diff identity、base/head revision；
- changed files、hunks、ranges 和原始 change evidence；
- provider evidence 及各自 source/revision/version；
- provider freshness 与 degradation decisions；
- inclusion reason、uncertainty、truncation 和 budget；
- 无法映射或证据不足的显式 gaps。

P1/P2 是增强证据，不是最低运行前提。P2 graph evidence 在第一阶段是 optional。Docs evidence 不能覆盖与之冲突的当前 Live Source；冲突必须保留并以 Live Source 为准。

## 6. Review Engine and findings

第一阶段 review 重点：

- Stability；
- Memory / Resource / Lifetime；
- Functional Correctness。

Test impact 可以作为 supporting evidence 或后续类别扩展，但本路线不恢复 UT Development / Repair 产品线。

`ReviewFinding` 至少包含：

```text
file
location/range
category
severity
title
description
evidence
reasoning
suggestion
confidence
```

Severity 枚举固定为：

```text
Critical
High
Medium
Low
```

Finding 必须定位到 review change 或明确相关源码；evidence 需要保留 provider、revision 和 source location。Reasoning 与 suggestion 分离，confidence 不代替证据。证据不足时降低 confidence、明确 unknown 或不产生 finding。Review 成功允许返回空 findings。

## 7. MCP Server and Code Review Skill

MCP 第一阶段至少规划以下 tools：

```text
review_pr
review_diff
get_review_result

update_repo_knowledge
rebuild_repo_knowledge
get_knowledge_status

set_review_users
get_review_users

start_auto_review
stop_auto_review
get_review_status
```

MCP Server 负责参数校验、鉴权/错误映射和调用 Service application APIs；不实现 review reasoning、scheduler 或 Agent Runtime。

Code Review Skill 只描述外部 Agent 如何：

- 选择 `review_pr` 或 `review_diff`；
- 查询异步 review/result/status；
- 在需要时查看或请求知识更新；
- 解释结构化 findings 和 degradation/provenance；
- 避免越权发布或把 unknown 解释成确定结论。

Skill 不包含永久轮询循环、GitCode 私有访问、author filter、dedup、知识存储或结果存储。

## 8. Historical foundations

### P0/P1/P2

P0、P1、P2 是已完成历史基础，继续保留 completed plans、specs、tests、frozen fixtures 与 evaluation baseline。新路线只改变它们的消费方式：P1 通过 `P1Provider`、P2 通过 `P2Provider` 接入 KnowledgeGateway；不删除、不重写 frozen semantics。

### P3-A～E

已完成 P3-A～E contract 仍描述代码当前具备的 Task/Change input、snapshot read、candidate retrieval、change mapping、graph expansion 和 context materialization 行为。R 路线可以选择复用，但不追溯改写其历史 scope。

### Superseded route

未完成的旧 P3 计划已移至 [`../exec-plans/superseded/P3-task-change-context.md`](../exec-plans/superseded/P3-task-change-context.md)。旧 P3-F incremental lifecycle、P4 Agent Runtime 和 P5 Code Review/UT capability 路线不再继续。对应历史 ADR 保留并标记 `Superseded`，由 [ADR-0005](../decisions/ADR-0005-code-review-service-pivot.md) 取代。

## 9. Evaluation direction

Evaluation 从各 R phase 同步建设，至少覆盖：

- finding precision、recall、false-positive rate；
- category、severity、location accuracy；
- evidence/provenance validity 和 revision alignment；
- P1/P2 stale 时的正确降级；
- No-Issue PR / diff；
- dedup correctness、job reliability、review latency；
- MCP contract compatibility；
- auto review recovery、duplicate suppression 和 operational safety。

Ablation 至少比较 diff-only、Docs + Live Source、增加 P1、增加 P2 的增益，不能预设 P2 对所有 case 都有收益。

## 10. Development route

已完成历史 phase 使用 P 编号；新产品开发使用独立 R 编号：

```text
P0 / P1 / P2 completed foundations
                ↓
R0 Review Service Foundation
                ↓
R1 GitCode Integration & Review State
                ↓
R2 Repository Knowledge Service
                ↓
R3 Review Engine
                ↓
R4 MCP Server
                ↓
R5 Auto Review & Code Review Skill
                ↓
R6 Evaluation & Hardening
```

- **R0**：建立平台无关的 Service package boundary、核心 domain contract、job/result ports、配置和可测试骨架。
- **R1**：实现 GitCodeProvider、PR ingestion、review users、identity/dedup 和 review state。
- **R2**：实现 KnowledgeGateway、四个 provider、provider freshness、update/rebuild 与降级。
- **R3**：实现 ReviewContextPack、Review Engine、finding validation 和首批 review categories。
- **R4**：通过 MCP tools 暴露 review、knowledge、users 和 status/control APIs。
- **R5**：实现 Service-owned auto review，并交付只编排 MCP 的 Code Review Skill。
- **R6**：形成正式 benchmark、ablation、reliability/security/performance hardening。

各 Phase 的 Goal、In Scope、Out of Scope 和 Definition of Done 以 [`../exec-plans/phase-map.md`](../exec-plans/phase-map.md) 为准。当前仅有 R0 active plan；计划存在不代表授权实现产品代码。
