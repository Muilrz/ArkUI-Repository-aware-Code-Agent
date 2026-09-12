# Documentation Map

项目文档按“长期架构 → 已实现规范 → 开发阶段 → 执行计划 → 可执行验证”组织。

| 位置 | 职责 | 权威内容 |
| --- | --- | --- |
| `architecture/technical-roadmap.md` | 长期系统架构 | Code Review Service 产品定位、依赖方向、核心边界、R0–R6 路线 |
| `architecture/code-review-architecture.md` | 核心业务架构 | GitCode integration、scheduler/filter/dedup、review job、context、finding、result |
| `architecture/repository-knowledge-architecture.md` | Repository Knowledge 专题架构 | provider contract、provider-level freshness、evidence 与降级策略 |
| `architecture/code-graph-architecture.md` | P2 Code Graph 架构视图 | frozen P2 层次、依赖方向，以及作为 `P2Provider` 的新定位 |
| `specs/` | 当前已实现规范 | API、identity、relation、evidence、状态与失败语义 |
| `exec-plans/phase-map.md` | 工程阶段 | 历史 P0–P3 关系和当前 R0–R6 Goal/In Scope/Out of Scope/DoD |
| `exec-plans/active/` | 当前工作 | milestone 范围、交付物、Acceptance Criteria、状态 |
| `exec-plans/completed/` | 已完成计划 | 已完成范围和简要验收记录 |
| `exec-plans/superseded/` | 被替代计划 | 未完成但已停止的历史路线及其已完成事实 |
| `decisions/` | 架构决定 | 决策背景、选择、后果和 supersession 关系 |
| `evaluation/` | 评估说明 | baseline、指标和跨 milestone 结果 |
| `tests/fixtures/` | 可执行 expected | 与指定源码 revision 绑定的具体预期 |

同一规则只在一个层级完整定义。Architecture 描述未来如何组合能力；spec 描述代码当前已经实现什么；execution plan 不复制完整 contract；历史 baseline/fixture 不因产品路线变化而改写。

## 当前状态

- P0、P1、P2 已完成，计划保存在 `exec-plans/completed/`。
- P1 作为 Repository Knowledge Service 的 `P1Provider` 复用；P2 作为 `P2Provider` 复用。既有 specs、baseline 和 frozen fixtures 保持不变。
- P3-A～E 已完成，其 `specs/task-change-context/` 与 `evaluation/p3-*` 继续记录已实现行为和验收事实。
- 未完成的旧 P3 计划已标记 `Superseded` 并移至 [`exec-plans/superseded/P3-task-change-context.md`](exec-plans/superseded/P3-task-change-context.md)。P3-F incremental lifecycle、P4 Agent Runtime 和旧 P5 Engineering Agent 路线不再继续。
- 当前 active plan 是 [`exec-plans/active/R0-review-service-foundation.md`](exec-plans/active/R0-review-service-foundation.md)；它只定义下一阶段计划，不表示 R0 产品代码已经实现。

## 当前架构入口

最高层 source of truth 是 [`architecture/technical-roadmap.md`](architecture/technical-roadmap.md)。专题文档：

- [`architecture/code-review-architecture.md`](architecture/code-review-architecture.md)：独立 Code Review Service 核心业务流；
- [`architecture/repository-knowledge-architecture.md`](architecture/repository-knowledge-architecture.md)：`DocsKbProvider + LiveSourceProvider + P1Provider + P2Provider`；
- [`architecture/code-graph-architecture.md`](architecture/code-graph-architecture.md)：P2 frozen semantics 与 `P2Provider` 边界；
- [`decisions/ADR-0005-code-review-service-pivot.md`](decisions/ADR-0005-code-review-service-pivot.md)：本次产品与架构迁移决定。

核心原则：Live Source 始终按当前 PR revision 提供源码事实；P1/P2 stale 时显式降级或刷新，不阻塞 `Docs + Live Source` review；freshness 按 provider 报告，不依赖统一 snapshot/generation；MCP 是标准接口层，Skill 只描述 MCP tool 组合，后台轮询属于 Service。

## 历史规范与验证入口

- P1：`specs/repository-intelligence/`
- P2：[`specs/code-graph/README.md`](specs/code-graph/README.md)
- P3-A～E：[`specs/task-change-context/README.md`](specs/task-change-context/README.md)
- P1/P2 baseline：[`evaluation/p1-retrieval-baseline.md`](evaluation/p1-retrieval-baseline.md)、[`evaluation/p2-code-graph-baseline.md`](evaluation/p2-code-graph-baseline.md)
- P3 已冻结/验收材料：`evaluation/p3-*`

旧 incremental knowledge 文档和未完成 contract 可以作为历史工作保留，但不得覆盖当前 provider-based architecture，也不得被解释为 R0–R6 的必选实现路径。
