# ArkUI Repository-aware Code Review Service

本项目面向 OpenHarmony ArkUI Ace Engine，构建独立的 **Repository-aware Code Review Service**、**Repository Knowledge Service**、**MCP Server** 与供外部 Agent 使用的 **Code Review Skill**。系统不建设通用 Agent Runtime；自动轮询、review state、知识更新和结果持久化属于 Service，不属于 Skill 或外部 Agent。

## Source of Truth

项目长期技术架构的 source of truth：

- `docs/architecture/technical-roadmap.md`

工程开发阶段、Phase 边界与 Definition of Done：

- `docs/exec-plans/phase-map.md`

当前正在执行或待执行的开发计划：

- `docs/exec-plans/active/`

已结束和被路线替代的计划分别保存在：

- `docs/exec-plans/completed/`
- `docs/exec-plans/superseded/`

当文档存在层级差异时，按以下优先级理解：

1. `technical-roadmap.md` 决定长期产品目标、核心架构与依赖方向；
2. `phase-map.md` 决定开发阶段边界与 Definition of Done；
3. `active/` 下的 execution plan 决定当前具体实现范围与验收标准；
4. `specs/` 记录当前代码已经实现的 contract，不因未来架构迁移而自动改变历史事实。

不要自行用新的总体架构替换这些文档中的既定设计。若发现实际冲突，应在实现前明确指出。

### Documentation Authority

- `docs/architecture/`：长期结构、模块职责、依赖方向和架构边界；不记录源码行号或逐次测试日志。
- `docs/specs/`：当前已实现能力的规范行为、接口、不变量和失败语义。未来架构只有在实现完成后才进入 spec。
- `docs/exec-plans/phase-map.md`：Phase 边界与 Definition of Done。
- `docs/exec-plans/active/`：当前变更的目标、范围、交付物、Acceptance Criteria 和状态。
- `docs/exec-plans/completed/`：已完成计划。
- `docs/exec-plans/superseded/`：未完成但已被产品或架构决定替代的计划。`Superseded` 不等于 `Completed`，其中已完成 milestone 仍是历史事实。
- `tests/fixtures/`：与具体源码 revision 绑定的冻结 expected cases。
- `docs/evaluation/`：baseline、benchmark、指标和跨 milestone 结果。
- `docs/decisions/`：需要长期保留背景、选择与后果的架构决定。

当 active plan 有意修改既有行为时，它描述拟议变更；完成实现时必须同步更新对应 spec。代码与 spec 不一致是实现或文档缺陷，不通过复制一份新规则规避。

## Current Development Scope

历史基础：

- P0 — Engineering Foundation：Completed
- P1 — Repository Intelligence：Completed，作为 `P1Provider` 被复用
- P2 — ArkUI Code Graph：Completed，作为 `P2Provider` 被复用；frozen semantics、fixtures 和 baseline 不重写
- P3-A～E：已完成 contract 继续保留为当前实现事实
- 原 P3 后续路线：`Superseded`；不继续开发 P3-F incremental lifecycle、P4 Agent Runtime 或旧 P5 Engineering Agent 路线

新的产品开发路线使用独立编号：

- R0 — Review Service Foundation
- R1 — GitCode Integration & Review State
- R2 — Repository Knowledge Service
- R3 — Review Engine
- R4 — MCP Server
- R5 — Auto Review & Code Review Skill
- R6 — Evaluation & Hardening

当前 active plan 是 `docs/exec-plans/active/R0-review-service-foundation.md`。只有任务明确要求实现相应 milestone 时才修改产品代码；不得因计划已存在而提前实现 R0 或后续阶段。

## Core Architecture Boundaries

### Code Review Service

- Review identity 至少为 `repository + pr_id + head_sha + review_policy_version`。
- `GitCodeProvider` 隔离平台私有 API；Review Engine 不依赖 GitCode schema。
- PR Poller / Scheduler、review user filter、head SHA dedup、Review Job Manager 和 Result Store 都属于 Service。
- 第一阶段重点 review category 为 Stability、Memory / Resource / Lifetime、Functional Correctness。
- Review 允许成功地产生 zero findings；无证据不得制造 finding。

### Repository Knowledge Service

Repository Knowledge 是 provider-based service，不要求维护统一 `KnowledgeSnapshot` 或 generation：

- `DocsKbProvider`：ArkUI docs/kb、`context_registry`、`kb_search`，提供架构、组件和领域知识。
- `LiveSourceProvider`：`rg` / Git / filesystem，读取当前 PR revision 的真实源码，是源码事实的最终 source of truth。
- `P1Provider`：复用 P1 symbol / definition / reference / caller / callee / tests。
- `P2Provider`：复用 P2 ArkUI-specific framework semantic relations。

P1/P2 stale、unavailable 或 refresh 失败时不得阻塞 review；Review 必须可降级为 `Docs + Live Source`。旧 revision 的 P1/P2 facts 不能作为当前 revision 的确定事实。

Freshness 以 provider 为单位报告，至少包含目标 `repository_revision` 以及每个 provider 的 `status`、`revision` 和必要 diagnostics。允许 provider 分别 refresh；不得以统一 snapshot readiness 作为 review 的硬门槛。

未来可以增加 `SemanticMcpProvider`，但当前架构、contract、测试和可用性不能依赖它。

### MCP and Skill

- MCP Server 只是 Code Review Service 与 Repository Knowledge Service 的标准接口层，不实现 planning、agent loop、长期 memory 或通用 Agent Runtime。
- Code Review Skill 只告诉 Codex、Claude 或其他 Agent 如何组合 MCP tools，不能承载 polling、scheduler、dedup、知识持久化或 review result storage。
- 自动检视固定属于 Service：`Scheduler → GitCodeProvider → author filter → head SHA dedup → review → persist`。
- 外部 Agent 可消费 MCP，但 Service 的正确性和自动检视生命周期不依赖外部 Agent 自己维持后台循环。

### Historical P1/P2/P3 Contracts

- P1/P2 不删除、不重写既有 frozen semantics。
- P1/P2 specs、baseline 与 frozen fixtures 是已实现历史事实。
- 已实现 P3-A～E specs/evaluation 继续保留；新架构可以复用其能力，但不把它们追溯改写为新 Service contract。
- 原 dependency-driven incremental knowledge、TU invalidation、semantic shard、fact ownership、P1 delta、P2 incremental projection、KnowledgeSnapshot generation 和 SnapshotQueryView 不是新产品必选主线。历史实现和文档可以保留，但不能被描述为当前路线要求。

## Target Repository

ArkUI Ace Engine 是外部 target repository，不属于本项目源码。

- 不得复制或 vendor ArkUI Ace Engine 到本项目。
- 目标仓库路径通过显式配置提供，例如 `ARKUI_REPO_ROOT`。
- 默认将 target repository 视为只读。
- 仅在任务明确要求修改 ArkUI 源码时才允许写入。
- 不得在源码中硬编码开发者本地 ArkUI 路径。

## Development Rules

- 保持 patch 小且可审查，不做无关重构。
- 不提前实现后续 milestone。
- 行为变更必须新增或更新测试。
- 外部工具集成隐藏在清晰的 adapter / provider 边界后。
- Python 接口优先使用明确的数据类型与 type hints。
- 不使用 broad exception handling 隐藏失败。
- 不通过绕过真实行为的 mock 让测试“假通过”。

## Validation

完成 coding task 前必须：

1. Codex 开发过程中不主动执行测试命令；行为变更仍须新增或更新对应测试；
2. trusted Stop Hook 在停止前只运行工作树中新增或修改的 `test_*.py`；Codex 根据 Hook 结果继续修复或汇报；
3. strict full、真实 ArkUI baseline 和其他昂贵验证由用户显式触发，不由 Codex 或 Stop Hook 自动执行；
4. Hook 不可用或未 trusted 时必须明确报告本次未验证，不得以手动 full 自动补跑；
5. 报告 Hook 实际结果、未验证项、修改文件、重要决定和可 review diff。

纯文档任务按任务要求执行 Markdown/link/diff 检查，不主动运行产品测试。若存在必需测试失败，不得宣称任务完成。

## Execution Plan Updates

- 开始开发：将对应 milestone Status 设为 `In Progress`。
- 仅当 Acceptance Criteria 与必需测试全部通过：设为 `Completed`。
- 存在未完成项或失败测试：保持 `In Progress`。
- 路线被新产品或架构决定替代且未完成：设为 `Superseded` 并移动到 `docs/exec-plans/superseded/`；不得标记 `Completed`。
- 不得顺手修改其他 milestone 状态。

## Git and Generated Data

不要提交 Python cache、virtual environment、build output、SQLite/database/index、runtime cache、`var/` 运行数据、target repository 派生数据或 `compile_commands.json` 等大型外部构建产物。不要重写既有 Git history。

### Runtime Artifact Discipline

- 不为每个 milestone 自动保存 `.patch`、diff/before snapshot、code-freeze 文件或逐命令测试日志。
- Code review 默认使用当前 Git 状态与 `git diff` / `git diff --check`；仅在任务明确要求时导出 patch。
- probe、临时诊断和中间测试输出默认不持久化到 `var/`。
- `var/` 只保留明确项目流程会消费的可重建产物，例如 evaluation 输出、P1/P2 index/graph data、provider cache/status 或 Stop Hook 最新结果。
- 若最终报告文字可完整表达验证结果，不额外生成同内容 JSON/log。
