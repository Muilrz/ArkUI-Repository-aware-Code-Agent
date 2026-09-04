# ADR-0001: Development Phase and Milestone Model

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

项目长期技术路线已经定义了 Repository Intelligence、ArkUI Code Graph、Task Retrieval / Context Builder、Agent Runtime、UT Agent / Repair 和 Evaluation。

为了让 Codex 可以持续实现且每次变更都能独立验收，需要把长期架构转换成更严格的工程开发阶段。

如果直接给 Codex “完成 Phase 1”或“实现 Agent”这类大任务，容易出现：

- 提前实现后续模块；
- 架构边界混杂；
- diff 过大难以 review；
- failure root cause 难以定位；
- execution plan 失去状态管理价值。

## Decision

采用三层开发管理模型：

```text
Phase
  ↓
Milestone
  ↓
Codex Task
```

正式 Phase：

- P0 — Engineering Foundation
- P1 — Repository Intelligence
- P2 — ArkUI Code Graph
- P3 — Task Retrieval & Context Builder
- P4 — Agent Runtime
- P5 — UT Agent & Repair
- P6 — Evaluation & Hardening

### Key Boundaries

1. P0 只负责工程基础，不理解 C++ symbol。
2. P1 负责通用 C++ repository facts，不负责 ArkUI domain trace。
3. P2 负责 ArkUI framework-aware graph relation。
4. P3 负责 Task Retrieval 与 Task Context Pack，不负责 Agent loop。
5. P4 负责 Agent Runtime，优先完成 read-only source analysis。
6. P5 才引入真实 edit/build/test/repair coding loop。
7. Evaluation 从 P1 开始持续建设，P6 负责正式 benchmark、ablation 和 hardening。

### Milestone Naming

使用：

```text
P0-A
P0-B
P1-A
P1-B
...
```

若 milestone 仍过大，可以继续拆：

```text
P1-C1
P1-C2
P1-C3
```

## Consequences

### Positive

- Codex task 更小、更可 review。
- 每个阶段有明确 Definition of Done。
- 可以独立定位 Retrieval、Graph、Context、Agent、Coding failure。
- 避免把 ArkUI domain knowledge 提前混入 Repository Intelligence。
- 便于持续 Evaluation。

### Trade-offs

- 文档与 milestone 状态需要持续维护。
- 某些能力可能跨 milestone，需要明确 dependency。
- 早期开发速度可能略慢，但能降低后续架构返工。

## Follow-up

Initial follow-up at ADR acceptance:

- 优先细化并执行 P0、P1。
- P2-P6 暂保持 Phase-level definition，接近开发时再进一步拆 milestone。

### Follow-up Status

- P0: Completed
- P1: Completed
- P2: 已进入执行阶段，并已细化为独立 execution plan。
- P3-P6: 继续保持 Phase-level definition，接近开发时再细化 milestone。
