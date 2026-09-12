# R0 — Review Service Foundation

- **Phase Status:** Not Started
- **Planning Status:** Active
- **Product code in this migration:** Not authorized
- **Depends on:** completed P0 foundation; existing P1/P2 only as future provider contracts
- **Architecture:** [Technical Roadmap](../../architecture/technical-roadmap.md), [Code Review Architecture](../../architecture/code-review-architecture.md), [ADR-0005](../../decisions/ADR-0005-code-review-service-pivot.md)
- **Phase boundary:** [Phase Map §4](../phase-map.md#4-r0--review-service-foundation)

## Goal

建立平台无关、可测试的 Code Review Service 基础，使 R1–R5 能在稳定 domain/application ports 上实现 GitCode、Repository Knowledge、Review Engine、MCP 和 auto review，而不引入 generic Agent Runtime。

本文件只规划未来 R0。创建或更新本计划不表示任何 R0 产品能力已实现；开始实现时须由明确任务选择一个 milestone，并按 AGENTS.md 更新状态。

## In scope

- Code Review Service package/module ownership 与 dependency direction；
- core review domain models and serialization；
- review identity and policy version boundary；
- ReviewFinding required fields/severity types；
- job/result/application ports；
- `GitCodeProvider`、`KnowledgeGateway`、`ReviewEngine`、`ResultStore` 的抽象边界；
- configuration、error taxonomy、correlation/observability foundation；
- unit-level contract tests and fixtures；
- R0 实现完成后同步新增的 specs。

## Out of scope

- 真实 GitCode API、credentials、PR polling 或 comment publishing；
- review user filter 的持久化实现与 durable revision dedup；
- DocsKb/LiveSource/P1/P2 provider implementation；
- Repository Knowledge update/rebuild；
- LLM integration、review policy reasoning 或真实 findings detection；
- MCP Server/tools；
- Scheduler、auto review 和 Code Review Skill；
- generic Agent Runtime、UT Development / Repair；
- 修改 P1/P2 frozen semantics、fixtures 或 baseline；
- 继续 P3-F incremental knowledge 路线。

## Milestone sequence

| Milestone | Scope | Depends on | Status |
| --- | --- | --- | --- |
| R0-A | Package boundaries and dependency rules | P0 | Not Started |
| R0-B | Core review domain contracts | R0-A | Not Started |
| R0-C | Application ports and job lifecycle contract | R0-B | Not Started |
| R0-D | Configuration, errors, observability and foundation acceptance | R0-A–C | Not Started |

一次 Codex coding task 默认只执行一个 milestone；若实际 diff 仍过大，应继续拆分，而不是跨入 R1。

## R0-A — Package Boundaries and Dependency Rules

- **Status:** Not Started
- **Goal:** 建立 review service 的模块所有权、依赖方向和可导入骨架。
- **Deliverables:** package layout；domain/application/ports/adapters dependency rules；architecture/spec link；boundary tests。
- **Acceptance Criteria:** domain 不依赖 GitCode、MCP、LLM 或具体 storage；现有 P1/P2 包不被移动或重写；import/dependency tests 固定允许方向。
- **Non-goals:** 任何 provider、engine、MCP 或 scheduler behavior。

## R0-B — Core Review Domain Contracts

- **Status:** Not Started
- **Goal:** 冻结后续阶段共享的最小平台无关 value objects。
- **Deliverables:** `ReviewIdentity`、ReviewRequest/change refs、ReviewFinding、ReviewResult summary、provider evidence/status references 的 typed models；canonical serialization tests；spec。
- **Acceptance Criteria:** identity 必含 `repository + pr_id + head_sha + review_policy_version`；finding 必含 file、location/range、category、severity、title、description、evidence、reasoning、suggestion、confidence；severity 仅为 Critical/High/Medium/Low；invalid/unknown fields 具有明确失败语义。
- **Non-goals:** GitCode schema mapping、prompt/output parsing、finding detection。

## R0-C — Application Ports and Job Lifecycle Contract

- **Status:** Not Started
- **Goal:** 定义 Service orchestration 需要的稳定 ports 和最小 job lifecycle。
- **Deliverables:** GitCodeProvider、KnowledgeGateway、ReviewEngine、ResultStore ports；Review Job Manager application service contract；job states/errors；test doubles and orchestration contract tests；spec。
- **Acceptance Criteria:** application layer 只依赖 ports；一次 fake request 可沿 fake gateway/engine/store 走通 deterministic lifecycle；失败不会保存为 success；不实现 durable dedup、real review 或 background loop。
- **Non-goals:** R1–R5 adapter/behavior 实现。

## R0-D — Configuration, Errors, Observability and Acceptance

- **Status:** Not Started
- **Goal:** 提供后续 adapter 可复用的安全配置、错误分类和 correlation 基础，并完成 R0 phase acceptance。
- **Deliverables:** config boundary；typed error taxonomy；review/job correlation identifiers；structured diagnostic contract；R0 traceability matrix and targeted tests。
- **Acceptance Criteria:** secrets 不进入 repr/log/result；domain/application failures 可稳定分类；correlation 不改变 review identity；Phase Map R0 DoD 逐项有 spec/test evidence；所有 required validation 通过后才能标记 R0 Completed。
- **Non-goals:** production telemetry backend、credential acquisition、retry/backoff policy beyond the port contract。

## Cross-cutting contract decisions

### Review identity

```text
repository + pr_id + head_sha + review_policy_version
```

R0 只冻结 identity value object。并发 claim、durable dedup、retry/force semantics 属于 R1。

### ReviewFinding

R0 固定必填字段和 severity vocabulary，不提前定义 R3 的 category policy、LLM schema/prompt 或 evidence sufficiency algorithm。

### Provider references

R0 model 可以表达 provider name/status/revision/version/evidence reference，但不建立统一 `KnowledgeSnapshot` 或 generation。R2 冻结 provider-level freshness 和 degradation behavior。

### MCP and Skill

R0 application ports 不依赖 MCP。R4 将 application APIs 映射为 MCP；R5 Skill 只消费 MCP public tools。

## Validation plan

实现 R0 milestone 时：

- 行为变更新增或更新对应 `test_*.py`；
- Codex 不主动执行测试，由 trusted Stop Hook 按 AGENTS.md 运行工作树相关测试；
- strict full、ArkUI baseline 或其他昂贵验证仅由用户显式触发；
- 文档与 schema link 做相对链接检查；
- 完成前运行 `git diff --check`。

本次文档迁移不执行上述产品测试，也不把任何 milestone 改为 `In Progress` 或 `Completed`。

## Phase acceptance checklist

- [ ] R0-A Completed
- [ ] R0-B Completed
- [ ] R0-C Completed
- [ ] R0-D Completed
- [ ] R0 specs describe implemented behavior only
- [ ] Required targeted tests passed through the trusted validation path
- [ ] Phase Map R0 DoD fully traceable
- [ ] No R1+ behavior claimed as implemented

## Risks and controls

- **Over-generalization:** 只抽象已知 Code Review Service seams，不建设通用 workflow/runtime framework。
- **Platform leakage:** GitCode fields只在 R1 adapter，R0 domain 使用 platform-neutral identity/change types。
- **Premature knowledge model:** R0 只保留 provider evidence references，provider status/fallback 在 R2 冻结。
- **Historical rewrite:** 不修改 P1/P2 frozen semantics 或 P3-A～E contract。
- **Scope creep:** R0 不接入网络、LLM、MCP 或 scheduler。
