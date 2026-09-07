# Documentation Map

项目文档按“架构方向 → 已实现规范 → 执行计划 → 可执行验证”组织。

| 位置 | 职责 | 权威内容 |
| --- | --- | --- |
| `architecture/technical-roadmap.md` | 长期系统架构 | 模块目标、长期技术方向、核心边界 |
| `architecture/code-graph-architecture.md` | P2 架构视图 | 数据流、层次、依赖方向、非目标 |
| `specs/` | 当前实现规范 | API、identity、relation、evidence、状态与失败语义 |
| `exec-plans/phase-map.md` | 工程阶段 | Phase 边界与 Definition of Done |
| `exec-plans/active/` | 当前工作 | milestone 范围、交付物、Acceptance Criteria、状态 |
| `exec-plans/completed/` | 历史执行计划 | 已完成范围和简要验收记录 |
| `decisions/` | 架构决定 | 决策背景、选择、后果 |
| `evaluation/` | 评估说明 | benchmark、指标和跨 milestone 结果 |
| `tests/fixtures/` | 可执行 expected | 与指定源码 revision 绑定的具体预期 |

同一规则只在一个层级完整定义。上层文档可以概括并链接下层规范；execution plan 不复制 spec，spec 不保存逐次命令日志或某次开发过程。当前 P2 规范入口见 [`specs/code-graph/README.md`](specs/code-graph/README.md)。
