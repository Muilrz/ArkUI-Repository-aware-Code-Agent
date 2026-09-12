# ADR-0005: Pivot to an Independent Code Review Service

- **Status:** Accepted
- **Date:** 2026-09-13
- **Supersedes:** [ADR-0003](ADR-0003-multi-capability-engineering-agent.md), [ADR-0004](ADR-0004-incremental-repository-knowledge.md)
- **Amends:** [ADR-0001](ADR-0001-development-phase-model.md) phase catalog while retaining its Phase → Milestone → Codex Task management model

## Context

项目原路线将 P1 Repository Intelligence、P2 ArkUI Code Graph、P3 Task / Change Context 和 P4 Agent Runtime 组织为 multi-capability Engineering Agent 的共享基础设施，再在 P5 提供 Code Review 与 UT Development / Repair。

该路线同时把 Repository Knowledge 的未来关键路径绑定到统一 snapshot/generation 和 dependency-driven incremental P1/P2 lifecycle。对于当前产品目标，这带来了两类不必要耦合：

- 为交付独立在线 Code Review 必须先建设 generic Agent Runtime；
- P1/P2 索引的 freshness/refresh 复杂度成为 Review availability 的硬门槛。

产品方向现已明确为可独立运行的 Code Review Service，通过标准 MCP 接口供 Codex、Claude 和其他 Agent 使用；Repository Knowledge 需要组合现有资产并允许安全降级，而不是先完成一套统一知识数据库。

## Decision

### 1. Product positioning

项目转向：

```text
Repository-aware Code Review Service
+ Repository Knowledge Service
+ MCP Server
+ Code Review Skill
```

Code Review Service 是核心产品。停止建设 generic Agent Runtime，不继续旧 P4/P5 Agent/UT 路线。

### 2. Service-owned review lifecycle

Code Review Service 自己拥有：

- `GitCodeProvider`；
- PR Poller / Scheduler；
- Review User Filter；
- Revision Dedup；
- Review Job Manager；
- Review Engine；
- Result Store。

最小 review identity 为：

```text
repository + pr_id + head_sha + review_policy_version
```

自动 review 固定为 Service 行为：

```text
Scheduler → GitCodeProvider → author filter → head SHA dedup → review → persist
```

### 3. Provider-based Repository Knowledge

Repository Knowledge Service 聚合：

```text
DocsKbProvider
+ LiveSourceProvider
+ P1Provider
+ P2Provider
```

- DocsKbProvider 提供 ArkUI docs/kb、context_registry、kb_search 的架构与领域证据。
- LiveSourceProvider 通过 rg/Git/filesystem 读取当前 PR revision，是源码事实的最终 source of truth。
- P1Provider 复用现有 symbol/definition/reference/caller/callee/tests 能力。
- P2Provider 复用现有 ArkUI-specific framework semantic relations。

P1/P2 stale 或 unavailable 时，Service 刷新或排除旧 revision facts，并允许以 `Docs + Live Source` 降级完成 review。未来可以增加 `SemanticMcpProvider`，但当前架构不得依赖它。

### 4. Provider-level freshness

Freshness 以 provider 为单位报告。公共 contract 不要求统一 `KnowledgeSnapshot`、generation 或所有 provider 原子同步 ready。旧 revision 的 P1/P2 facts 不得作为当前确定事实。

### 5. Preserve P1/P2 and implemented P3 contracts

P0/P1/P2 completed plans、P1/P2 specs、baseline、frozen fixtures 和已经实现的 P3-A～E contracts 全部保留。P1/P2 不删除、不重写 frozen semantics；本决策只改变未来如何通过 provider 使用它们。

### 6. Stop the old incremental and Agent route

Dependency-driven incremental knowledge、TU invalidation、semantic shard、fact ownership、P1 delta、P2 incremental projection、KnowledgeSnapshot generation 和 SnapshotQueryView 不再是产品必选主线。历史实现不删除，可以在未来作为单个 provider 的内部优化重新评估。

未完成的 P3 plan 标记 `Superseded` 并移至 `docs/exec-plans/superseded/`。A～E Completed 仍是历史事实；F 及后续路线停止。

### 7. MCP and Skill boundary

MCP Server 是 Service 的标准接口层，不实现 Agent Runtime。第一阶段规划 review/result、knowledge update/rebuild/status、review users 和 auto-review control/status tools。

Code Review Skill 只指导外部 Agent 如何组合 MCP tools。Polling、scheduler、filter、dedup、knowledge persistence 和 result persistence 不进入 Skill。

### 8. New phase catalog

保留 P0/P1/P2 历史，新的未来开发使用：

- R0 Review Service Foundation
- R1 GitCode Integration & Review State
- R2 Repository Knowledge Service
- R3 Review Engine
- R4 MCP Server
- R5 Auto Review & Code Review Skill
- R6 Evaluation & Hardening

## Consequences

### Positive

- Code Review 可独立运行，不等待通用 Agent Runtime。
- P1/P2 继续产生价值，同时其 stale/rebuild 不阻断最低 review path。
- 当前源码 authority、provider provenance 和 degradation 更明确。
- MCP/Skill 为多种外部 Agent 提供稳定接入，不把后台生命周期推给 Agent。
- 新 R 编号清楚区分历史完成事实与新产品工作。

### Trade-offs

- Docs、Live Source、P1、P2 可能处于不同 freshness 状态，ContextPack 必须保留冲突和降级。
- 不依赖统一 snapshot 后，跨 provider 不能假设天然 transaction consistency。
- Review Service 需要自己承担 scheduler、job、dedup、result store 和 operational reliability。
- P1/P2 provider adapter 必须避免把旧 revision facts 提升成当前事实。

## Rejected alternatives

### Continue P3-F then build Agent Runtime

会把当前 Code Review 交付继续绑定到非核心的通用 runtime 和 incremental lifecycle，拒绝。

### Delete P1/P2 and use source-only review

会丢失已完成的 semantic/domain investment 与可追溯事实，拒绝。Source-only 是降级路径，不是删除 P1/P2 的理由。

### Require all providers to publish one generation

会重新引入统一 snapshot 的协调与阻塞语义，拒绝作为公共架构要求。Provider 内部仍可自行 version/cache。

### Put polling in the Skill

Skill/Agent 生命周期不适合作为可靠后台 scheduler 和 dedup owner，拒绝。

## Follow-up

1. 将 `technical-roadmap.md` 改为最高层 Code Review Service 路线。
2. 将 Repository Knowledge 改为 provider architecture，并冻结 provider-level freshness/degradation 原则。
3. 将 Code Review architecture 提升为核心业务架构。
4. 更新 phase map 为 R0–R6，并创建 R0 active plan。
5. 将未完成 P3 plan 标记 Superseded；不删除历史实现/spec/baseline/fixtures。
6. 只有后续明确 coding task 才开始 R0 产品实现。
