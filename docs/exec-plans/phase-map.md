# Development Phase Map

## 1. Purpose

本文档定义 `Muil_ArkUI-UT-Agent` 的工程开发 Phase、阶段边界、入口/出口能力与 Definition of Done。

长期架构与技术方向以：

- `docs/architecture/technical-roadmap.md`

为 source of truth。

本文档不替代技术路线，而是把技术路线中的 Repository Intelligence、ArkUI Code Graph、Task Retrieval / Context Builder、Agent Runtime、UT Agent、Evaluation 转换为可执行的工程阶段。

开发遵循三层结构：

```text
Phase
  ↓
Milestone
  ↓
Codex Task
```

- **Phase**：具有明确系统能力边界的一段开发阶段。
- **Milestone**：可以独立实现、独立测试、独立验收的一块能力。
- **Codex Task**：对一个 milestone 或其子任务的具体实现指令。

除非确有必要，不给 Codex 下“完成整个 Phase”的大任务。

## 2. Global Principles

### 2.1 Repository Intelligence First

P1 Repository Intelligence 是后续系统的底层基础设施，不依赖 LLM。

后续 Code Graph、Task Context Builder 和 Agent Runtime 必须建立在稳定的 repository facts 之上，而不是通过 Prompt 临时猜测代码关系。

### 2.2 Separate Generic Code Facts from ArkUI Domain Knowledge

P1 负责通用 repository / C++ facts 与受控文本检索能力，例如：

- text match
- symbol
- declaration
- definition
- reference
- caller
- callee
- inheritance
- override
- test fixture
- test case

P2 才负责把这些事实解释成 ArkUI framework relation，例如：

- Bridge
- Model
- Pattern
- LayoutProperty
- PaintProperty
- LayoutAlgorithm
- OverlayManager
- CREATE
- UPDATE_PROPERTY
- MEASURE
- LAYOUT
- SHOW
- CLOSE

### 2.3 Separate Retrieval from Agent Behavior

P3 必须能够在没有 Agent 自主循环的情况下，根据 Task 构建高质量 Task Context Pack。

P4 才负责：

```text
Planning
→ Tool Call
→ Observation
→ State Update
→ Re-plan
```

### 2.4 Separate Agent Runtime from Coding Loop

P4 先验证 Agent 是否能正确使用 P1-P3 的能力完成只读源码分析任务。

P5 再引入：

- edit
- patch
- build
- test
- failure classification
- repair loop

### 2.5 Evaluation Starts Early

Evaluation 不是 P6 才开始。

每个 Phase 都需要同步建立本阶段指标：

- P1：Retrieval metrics
- P2：Graph / Trace metrics
- P3：Context metrics
- P4：Agent runtime metrics
- P5：Coding / Repair metrics

P6 负责正式 benchmark、ablation comparison、稳定性验证与 hardening。

# 3. P0 — Engineering Foundation

## Goal

建立后续 Repository Intelligence 可以安全复用的工程基础。

P0 只回答：

> 项目如何稳定运行，以及如何安全地接入一个外部 target repository？

P0 不理解 C++ symbol，也不理解 ArkUI framework。

## In Scope

- Python project/package baseline
- repository workspace
- repository configuration
- external target repository path
- read-only boundary
- temporary repository fixtures
- basic test execution convention
- runtime/generated-data directory convention

## Out of Scope

- repository recursive scanner
- C/C++ file discovery
- Symbol model
- Clang / clangd
- Symbol Index
- Definition / Reference / Caller
- ArkUI architecture
- Agent
- Build / UT repair

## Definition of Done

P0 完成时：

1. 可以通过显式配置打开一个外部 repository。
2. 不依赖开发者本地硬编码路径。
3. target repository 默认只读。
4. repository path boundary 明确，不允许无意逃逸 root。
5. automated tests 可以使用 temporary repository fixture。
6. 项目基础测试命令稳定可执行。
7. 后续模块无需重复实现 workspace/config。
8. P0 不包含 ArkUI 或 C++ 业务逻辑。

## Milestones

- `P0-A` — Repository Workspace & Configuration
- `P0-B` — Test / Fixture Foundation

# 4. P1 — Repository Intelligence

## Goal

建立不依赖 LLM 的结构化代码认知能力。

P1 主要回答：

> repository 中哪些位置匹配给定文本，以及给定一个 C++ symbol，它是什么、在哪里、谁引用/调用它、相关测试在哪里？

## In Scope

- repository scanner
- repository text search
- exact / regex text lookup
- path / file filtering
- File / Symbol data model
- C++ semantic provider abstraction
- Clang/clangd semantic backend
- Symbol Index
- declaration lookup
- definition lookup
- reference lookup
- caller / callee lookup
- inheritance / override 等基础语义关系
- Test Fixture / Test Case index
- 基础 test mapping
- 真实 ArkUI repository validation
- 初始 retrieval evaluation

## Out of Scope

- ArkUI domain-aware trace
- Property Update Trace
- Measure / Layout Trace
- Overlay Trace
- Task Context ranking
- Token Budget
- Agent planning loop
- Code editing
- Build / UT repair

## Definition of Done

在真实 ArkUI Ace Engine repository 上，对选定的一组代表性 repository queries 与 symbols，系统可以稳定执行：

```text
text_search
search_symbol
find_declaration
find_definition
find_references
find_callers
find_callees
find_tests
```

并满足：

1. Repository Intelligence 不依赖 LLM。
2. retrieval API 不与具体 Clang/clangd 实现强耦合。
3. Index 可以重新构建。
4. Index 和数据库属于派生数据，不进入 Git。
5. namespace、class member、overload 等 C++ 语义不能只通过关键词猜测。
6. Test Fixture / Test Case 可以作为一等实体查询。
7. 至少在多个真实 ArkUI 组件上完成 integration validation。
8. 有基础 retrieval benchmark 和错误分析。
9. 文本检索受 repository boundary 约束，结果可追溯到 source location，且不用于替代 C++ semantic resolution。

## Milestones

- `P1-A` — Repository Scanner
- `P1-B` — File / Symbol Data Model
- `P1-C` — C++ Semantic Provider Contract
- `P1-D` — Clang/clangd Semantic Backend
- `P1-E` — Symbol Index
- `P1-F` — Definition / Declaration Retrieval
- `P1-G` — Reference + Caller / Callee Retrieval
- `P1-H` — Test Fixture / Test Case Index
- `P1-I` — Real ArkUI Validation & Retrieval Baseline
- `P1-J` — Repository Text Search

# 5. P2 — ArkUI Code Graph

## Goal

在 P1 repository facts 之上建立 ArkUI framework-aware code relations。

P2 回答：

> 这些 symbol 在 ArkUI 架构上是什么关系？

## In Scope

- graph persistence/query
- local / bounded graph traversal
- symbol / component based graph expansion
- component creation trace
- property update trace
- measure/layout trace
- overlay trace
- lifecycle trace

## Out of Scope

- Task Context ranking
- Token Budget
- Agent planning
- Code editing
- Build / Repair

## Definition of Done

至少对代表性 ArkUI components，可以从真实代码中恢复并验证：

- Component Creation
- Property Update
- Measure / Layout
- Overlay Show / Close

并满足：

1. graph node/edge 可以追溯到 P1 symbol/source location；
2. generic edge 与 ArkUI domain edge 可区分；
3. 关键 domain edge 有 provenance；
4. 支持从 symbol/component 做局部 graph expansion；
5. 不需要把整张 graph 塞入 LLM；
6. 有人工标注的小规模 trace baseline；
7. 可以计算初始 Call Chain Accuracy。

# 6. P3 — Task Retrieval & Context Builder

## Goal

把 repository 中的大量事实压缩成与当前开发任务直接相关的上下文。

P3 回答：

> 面对一个具体 Task，后续 Agent 真正需要看到哪些代码和关系？

## In Scope

- Task schema
- Task parser
- Component / Target Symbol / Property / Action / Test Intent extraction
- Text Retrieval
- Symbol Retrieval
- Reference Retrieval
- Test Retrieval
- task-driven Graph Expansion
- Task Subgraph Extraction
- candidate ranking
- context tiering
- Token Budget
- Task Context Pack
- retrieval/context evaluation

## Out of Scope

- autonomous planning loop
- tool selection loop
- code editing
- build
- repair

## Definition of Done

给定自然语言或结构化任务，例如：

```text
给 MenuItem selected 属性补 UT
```

系统可以在没有 Agent 自主循环的情况下生成结构化：

```text
Task Context Pack
- Task
- Target
- Related Symbols
- Call Chain
- Source Snippets
- Existing Tests
- Similar Cases
- Mock Dependencies
```

并满足：

1. candidate retrieval 与 final context 分离；
2. context 有 Tier 1 / Tier 2 / Tier 3 或等价优先级；
3. context 有明确 Token Budget；
4. 每个 snippet / relation 可追溯来源；
5. 可解释为什么某候选被选入或排除；
6. 可以评估 Relevant Context Ratio；
7. 可以评估 Missing Dependency Rate；
8. 可以记录 Context Token Cost。

# 7. P4 — Agent Runtime

## Goal

让 LLM 基于 P1-P3 的能力执行多轮 repository-aware source analysis。

P4 回答：

> Agent 如何计划、调用工具、处理 Observation、更新状态并结束任务？

## In Scope

- tool contract
- planner
- tool executor
- agent state
- observation
- state update
- re-plan
- retry
- stop condition
- iteration limit
- execution trace
- read-only source analysis agent

## Out of Scope

P4 第一阶段默认不追求完整 coding loop：

- arbitrary source editing
- ArkUI build pipeline
- UT repair loop

## Definition of Done

Agent 可以：

1. 接收开发/分析 Task；
2. 生成和维护 Current Plan；
3. 根据状态选择 repository tools；
4. 使用 P1/P2/P3，而不是绕过基础设施自行做无边界搜索；
5. 处理 Observation；
6. Re-plan；
7. 触发明确 Stop Condition；
8. 防止无限循环；
9. 处理 invalid tool call；
10. 记录完整 Execution Trace；
11. 在一组 read-only Source Analysis benchmark 上稳定完成任务。

Execution Trace 至少记录：

- Task
- Plan
- Tool
- Tool Arguments
- Observation
- Retrieved Context
- Iteration
- Token Cost
- Latency

# 8. P5 — UT Agent & Repair

## Goal

完成真实 ArkUI UT 开发闭环。

P5 回答：

> Agent 能否找到正确测试上下文、生成符合项目风格的 UT、通过编译和测试，并自动修复失败？

## In Scope

- Test Mapping
- Fixture Retrieval
- Similar Test Retrieval
- Mock Retrieval
- Coverage Gap / Test Intent
- UT Generation
- patch application
- minimal build target
- minimal test target
- error parsing
- failure classification
- root cause retrieval
- repair loop
- end-to-end UT Agent

## Definition of Done

对 benchmark UT task，Agent 可以完成：

```text
Task
→ Target Retrieval
→ Existing Fixture
→ Similar Test
→ Mock Dependency
→ UT Patch
→ Compile
→ Minimal Test
→ Failure Classification
→ Root Cause Retrieval
→ Repair
→ Re-run
```

并记录：

- Compile Pass Rate
- UT Pass Rate
- Task Success Rate
- Repair Success Rate
- Average Iterations
- Tool Calls
- Token Cost
- Latency

# 9. P6 — Evaluation & Hardening

## Goal

形成正式 benchmark、ablation comparison、稳定性验证和系统 hardening。

P6 不负责首次建立评价体系，而是整合并完善 P1-P5 已持续建设的 evaluation。

## Benchmark Coverage

优先选择典型 ArkUI components：

- Button
- Text
- Menu
- Dialog
- Tabs
- List

任务至少覆盖：

- Component Creation
- Property Trace
- Layout Trace
- Source Analysis
- UT Generation
- UT Repair

## Metrics

### Retrieval

- Recall@K
- MRR
- Target File Recall
- Target Symbol Recall
- Call Chain Accuracy

### Context

- Relevant Context Ratio
- Missing Dependency Rate
- Context Token Cost

### Agent

- Tool Success Rate
- Invalid Tool Call Rate
- Average Tool Calls
- Average Iterations

### Coding

- Compile Pass Rate
- UT Pass Rate
- Task Success Rate
- Repair Success Rate

### Cost

- Token Usage
- Latency
- Tool Call Count

## Ablation

正式比较：

```text
LLM Only
vs
Keyword Search
vs
Symbol Retrieval
vs
Code Graph Retrieval
vs
Code Graph + Agent
```

## Definition of Done

1. benchmark dataset 固化；
2. evaluation command 可重复运行；
3. 结果可追踪到具体 task / component；
4. 失败案例可分类；
5. 完成主要 ablation comparison；
6. 有成本、延迟和成功率数据；
7. 对系统高频失败点完成 hardening；
8. 可以明确说明 Repository Intelligence、Code Graph、Context Builder 和 Agent Runtime 各自带来的增益或限制。

# 10. Phase Dependency

```text
P0 Engineering Foundation
        ↓
P1 Repository Intelligence
        ↓
P2 ArkUI Code Graph
        ↓
P3 Task Retrieval & Context Builder
        ↓
P4 Agent Runtime
        ↓
P5 UT Agent & Repair
        ↓
P6 Evaluation & Hardening
```

这不是绝对禁止并行开发。

Evaluation fixture、benchmark 标注、文档与测试基础可以提前并行建设，但核心能力依赖必须保持：

- P2 不绕过 P1 自己重新解析 repository facts；
- P3 不绕过 P2/P1 直接依赖 LLM 猜上下文；
- P4 不绕过 P3 长期依赖无约束 Prompt stuffing；
- P5 不把 build/test/repair 逻辑塞回 P4 基础 runtime；
- P6 不成为唯一存在 evaluation 的阶段。

# 11. Milestone Execution Rule

每个 milestone execution plan 至少包含：

- ID
- Status
- Goal
- Scope
- Non-goals
- Dependencies
- Deliverables
- Acceptance Criteria
- Tests / Validation
- Known Limitations

Status 统一使用：

- `Not Started`
- `In Progress`
- `Blocked`
- `Completed`

Milestone 过大时继续拆为 Codex Task：

```text
P1-C
├── P1-C1
├── P1-C2
└── P1-C3
```

Codex 每次只执行当前明确任务，不自动进入下一个 milestone。
