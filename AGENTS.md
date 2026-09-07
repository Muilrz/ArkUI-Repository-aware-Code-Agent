# ArkUI Repository-aware Code Agent

本项目旨在构建面向 OpenHarmony ArkUI Ace Engine 的 multi-capability Repository-aware Engineering Agent。Repository Intelligence、ArkUI Code Graph、Task / Change Context 与 Agent Runtime 是共享基础设施；Code Review 和 UT Development / Repair 是第一批上层 Engineering Capabilities。

## Source of Truth

项目长期技术架构的 source of truth：

- `docs/architecture/technical-roadmap.md`

工程开发阶段、Phase 边界与 Definition of Done：

- `docs/exec-plans/phase-map.md`

当前正在执行的开发计划：

- `docs/exec-plans/active/`

当长期技术路线、Phase Map 与当前执行计划存在层级差异时，按以下优先级理解：

1. `technical-roadmap.md` 决定长期架构目标与核心技术方向；
2. `phase-map.md` 决定工程开发阶段边界；
3. `active/` 下的 execution plan 决定当前具体实现范围与验收标准。

不要自行用新的总体架构替换这些文档中的既定设计。若发现文档之间存在实际冲突，应在实现前明确指出。

### Documentation Authority

文档按以下职责维护，避免在多处重复定义同一行为：

- `docs/architecture/` 说明长期结构、模块职责、依赖方向和架构边界；不记录源码行号、逐次测试结果或实现过程。
- `docs/specs/` 定义当前已实现能力的规范行为、接口、不变量和失败语义。execution plan 只引用这些规范，不复制完整 contract。
- `docs/exec-plans/phase-map.md` 定义 Phase 边界与 Definition of Done。
- `docs/exec-plans/active/` 定义当前变更的目标、范围、交付物、Acceptance Criteria 和状态；完成记录保持简洁。
- `docs/exec-plans/completed/` 保存已结束的执行计划。
- `tests/fixtures/` 中的冻结 expected case 是具体源码验证预期的可执行来源；`docs/evaluation/` 保存跨 milestone 的 baseline 和指标说明。
- `docs/decisions/` 记录需要长期保留背景、选择与后果的重要架构决定。

当 active execution plan 有意修改既有行为时，它描述本次拟议变更；完成实现时必须同步更新对应 spec。若 spec 与 roadmap 或 phase boundary 冲突，以上层文档为准。代码与 spec 不一致应视为实现或文档缺陷，不通过复制一份新规则来规避。

## Current Development Scope

已完成：

- P0 — Engineering Foundation
- P1 — Repository Intelligence
- P2 — ArkUI Code Graph（已通过最终验收，计划归档于 `docs/exec-plans/completed/`）

当前优先推进：

- P3 — Task / Change Retrieval & Context Builder 的规划与逐 milestone 开发，范围见 `docs/exec-plans/active/`。

当前 session 只整理 P2 收尾文档和 P3 execution plan，不实现 P3-A。后续仅在任务明确要求时实现对应 P3 milestone，不提前实现 P4 及后续 Phase。Code Review 新需求不得扩展已冻结的 P2 scope 或 baseline。

开发任务应尽量以 milestone 为最小可验收单元，例如：

- `P2-A`
- `P2-B`
- `P2-C`

若 milestone 仍过大，可以继续拆成如 `P2-C1`、`P2-C2` 的更小 Codex task。

## Core Architecture Boundaries

- Repository Intelligence 不依赖 LLM。
- Parser / semantic backend 必须与 indexing / retrieval API 解耦。
- Repository-derived persistent knowledge 应沉淀在 index / graph / metadata / knowledge snapshot 中，而不是长期 LLM memory。
- P1/P2/P3/P4 是多个 Engineering Capabilities 共享的基础设施；不得为 Code Review、UT 或后续 capability 分别复制 repository index、ArkUI graph 或 context pipeline。
- P3 负责 Task / Change Retrieval、Knowledge Snapshot/Freshness、Task/Change-driven Graph Expansion、Context Ranking 与 Context Pack；Task/Change candidate retrieval 与最终 context selection 应保持职责分离。
- P4 Agent Runtime 负责通用 planning、Tool/Skill invocation、state、observation、retry、stop condition 与 execution trace；P5 才实现 Code Review、UT Development/Repair 等具体 Engineering workflow。
- Skill 负责描述如何组合 Tool 完成工程任务；周期 polling、平台事件、Repository Knowledge 长期存储不得塞进 Skill 或 LLM memory。
- GitCode 等外部 Code Host 必须隐藏在清晰的 provider/adapter 边界后；上层 Code Review reasoning 不依赖平台私有 API schema。
- Repository Knowledge refresh 是共享平台能力，应支持显式 freshness 状态和可调用的 refresh entry point；Code Review/UT 不维护私有全仓知识副本。
- Evaluation 从项目早期同步建设；P6 负责形成正式 benchmark、ablation 与 hardening，而不是等到 P6 才开始评估。
- P2 负责 graph model、ArkUI framework-aware relation 和通用局部 graph traversal；Task/Change-driven Graph Expansion、Task Subgraph Extraction 与 Context Pack 属于 P3。

## Target Repository

ArkUI Ace Engine 是外部 target repository，不属于本项目源码。

- 不得复制或 vendor ArkUI Ace Engine 到本项目。
- 目标仓库路径通过显式配置提供，例如 `ARKUI_REPO_ROOT`。
- 默认将 target repository 视为只读。
- 仅在任务明确要求修改 ArkUI 源码时才允许写入。
- 不得在源码中硬编码开发者本地 ArkUI 路径。

## Development Rules

- 保持 patch 小且可审查。
- 不做与当前任务无关的重构。
- 不提前实现后续 milestone。
- 行为变更必须新增或更新测试。
- 外部工具集成应隐藏在清晰的 adapter / provider 边界后。
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

若存在必需测试失败，不得宣称任务完成。

## Execution Plan Updates

执行 milestone 时：

- 开始开发：将该 milestone Status 设为 `In Progress`；
- 仅当 Acceptance Criteria 与测试全部通过后：设为 `Completed`；
- 存在未完成项或失败测试：保持 `In Progress`；
- 不得顺手修改其他 milestone 状态。

完成的 execution plan 可从：

- `docs/exec-plans/active/`

移动到：

- `docs/exec-plans/completed/`

## Git and Generated Data

不要提交：

- Python cache；
- virtual environment；
- build output；
- SQLite / database / index files；
- runtime cache；
- `var/` 下运行时数据；
- target repository 派生数据；
- `compile_commands.json` 等大型外部构建派生产物。

不要重写既有 Git history。

### Runtime Artifact Discipline

- 不要为每个 milestone 自动生成或长期保存独立 `.patch`、diff snapshot、`before` snapshot、`code-freeze` 文件或逐命令测试日志。
- Code review 默认使用当前 Git 状态与 `git diff` / `git diff --check`；仅当任务明确要求导出 patch 时才创建 `.patch` 文件。
- 开发过程中的 probe、临时诊断结果和中间测试输出默认只用于当前执行，不持久化到 `var/`。
- `var/` 只保留确有工程用途、可由明确项目流程消费的运行产物，例如：
  - evaluation / benchmark 输出；
  - Symbol Index、Graph snapshot、Knowledge Snapshot 等明确设计为可重建的 runtime data；
  - Stop Hook 使用的最新 validation 结果；
  - execution plan 或测试明确要求用于真实仓库验收的机器可读 smoke / validation report。
- 如果最终报告中的文字即可完整表达验证结果，则不要额外生成同内容的 JSON / log 文件。
- 所有 `var/` 运行产物均视为可重建数据，不应提交 Git，除非项目文档明确规定例外。
