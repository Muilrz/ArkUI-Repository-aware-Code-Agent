# ADR-0002: Documentation Authority and Specifications

- **Status:** Accepted
- **Date:** 2026-09-07

## Context

P2 最初将 Graph Model/Query contract 作为 P2-A 的 architecture deliverable。后续 P2-B 至 P2-H 持续把 projection、role、framework relation、trace 规则、真实源码预期和测试记录追加到同一 `graph-contract.md`；P2 execution plan 同时复制了大量相同内容。

这使 architecture、规范行为、milestone 管理和验证记录混在两个大文件中，产生更新遗漏和局部双 Source of Truth 风险。

## Decision

采用以下文档职责：

1. `docs/architecture/` 说明系统结构、依赖方向和长期边界。
2. `docs/specs/` 定义当前已实现能力的规范行为、接口、不变量和失败语义。
3. `docs/exec-plans/` 管理 Phase/milestone 的目标、范围、交付物、Acceptance Criteria 和状态。
4. `tests/fixtures/` 保存与具体 repository revision 绑定的可执行 expected cases。
5. `docs/evaluation/` 保存跨 milestone benchmark 和指标；`docs/decisions/` 保存重要选择及后果。

原 `docs/architecture/graph-contract.md` 拆为 Code Graph architecture overview 和按能力划分的 specifications。P2 execution plan 删除重复 contract、源码行号和逐次开发日志，只保留执行管理信息和指向 spec/fixture/test 的验收索引。

当 active plan 有意改变既有 behavior 时，它描述拟议变更；完成实现时同步更新唯一对应 spec。Plan 不长期成为第二份 behavior contract。

## Consequences

### Positive

- 长期架构、当前行为、执行状态和具体 expected 各有唯一维护位置。
- P2-I/P3 后续工作可引用小而明确的 spec，无需继续扩张单一大文档。
- Completed milestone 的历史测试输出不会污染 architecture 或规范。

### Trade-offs

- 文档数量增加，需要维护相对链接和 spec 索引。
- 修改对外行为时必须同时更新代码、测试和对应 spec。
- Git 历史中的旧文件路径仍会出现在既有 commit 和历史对话中。
