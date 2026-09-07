# Documentation Map

项目文档按“架构方向 → 已实现规范 → 执行计划 → 可执行验证”组织。

| 位置 | 职责 | 权威内容 |
| --- | --- | --- |
| `architecture/technical-roadmap.md` | 长期系统架构 | 项目定位、模块目标、长期技术方向、核心边界 |
| `architecture/code-graph-architecture.md` | P2 Code Graph 架构视图 | 数据流、层次、依赖方向、非目标 |
| `architecture/technical-roadmap.md` §4 | Repository Knowledge 生命周期 | snapshot、revision consistency、freshness、scheduled/manual refresh 边界 |
| `architecture/code-review-architecture.md` | Code Review 长期架构 | Code Host adapter、polling/filter/dedup、review context、finding、publisher 边界 |
| `specs/` | 当前实现规范 | API、identity、relation、evidence、状态与失败语义 |
| `exec-plans/phase-map.md` | 工程阶段 | Phase 边界与 Definition of Done |
| `exec-plans/active/` | 当前工作 | milestone 范围、交付物、Acceptance Criteria、状态 |
| `exec-plans/completed/` | 历史执行计划 | 已完成范围和简要验收记录 |
| `decisions/` | 架构决定 | 决策背景、选择、后果 |
| `evaluation/` | 评估说明 | benchmark、指标和跨 milestone 结果 |
| `tests/fixtures/` | 可执行 expected | 与指定源码 revision 绑定的具体预期 |

同一规则只在一个层级完整定义。上层文档可以概括并链接下层规范；execution plan 不复制 spec，spec 不保存逐次命令日志或某次开发过程。

当前 P2 规范入口见 [`specs/code-graph/README.md`](specs/code-graph/README.md)。

P2-I 真实 ArkUI baseline 的 dataset、指标和命令见 [`evaluation/p2-code-graph-baseline.md`](evaluation/p2-code-graph-baseline.md)。

P2 已完成并归档至 [P2 execution plan](exec-plans/completed/P2-arkui-code-graph.md)。当前规划见 [P3 execution plan](exec-plans/active/P3-task-change-context.md)；P3 产品开发尚未开始。

当前长期能力扩展由以下架构文档共同描述：

- [`architecture/technical-roadmap.md`](architecture/technical-roadmap.md)：总体技术路线；
- [`technical-roadmap.md` §4](architecture/technical-roadmap.md#4-repository-knowledge-lifecycle)：共享全仓知识生命周期（统一在 roadmap 维护）；
- [`architecture/code-review-architecture.md`](architecture/code-review-architecture.md)：GitCode-first 在线代码检视架构。

重要架构决策见 `decisions/`。其中 ADR-0003 将项目正式定位为 multi-capability Repository-aware Engineering Agent；该决策不修改当前 P2 spec，也不重写 P0/P1 completed execution plan。
