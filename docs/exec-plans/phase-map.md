# Development Phase Map

## 1. Purpose

本文档定义 **ArkUI Repository-aware Code Agent** 的工程开发 Phase、阶段边界、入口/出口能力与 Definition of Done。

长期架构与技术方向以：

- `docs/architecture/technical-roadmap.md`

为 source of truth。

本文档不替代技术路线，而是把 Repository Intelligence、ArkUI Code Graph、Repository Knowledge Lifecycle、Task / Change Retrieval & Context Builder、Agent Runtime、Engineering Capabilities 和 Evaluation 转换为可执行的工程阶段。

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

后续 Code Graph、Task/Change Context Builder 和 Agent Runtime 必须建立在稳定的 repository facts 之上，而不是通过 Prompt 临时猜测代码关系。

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

### 2.3 Version Repository Knowledge

Repository-derived persistent knowledge 沉淀在 index、graph、metadata 和 Knowledge Snapshot 中，而不是长期 LLM memory。

P3 建立 snapshot/freshness/refresh orchestration 边界；第一版允许 revision 变化后全量 rebuild。

### 2.4 Treat Task and Change as Peer Inputs

P3 同时支持自然语言 Task 与平台无关的 PR/Commit/Diff Change。GitCode 私有 schema 不进入 P3。

### 2.5 Separate Retrieval from Agent Behavior

P3 必须能够在没有 Agent 自主循环的情况下生成高质量 Task/Change Context Pack。

P4 才负责：

```text
Planning
→ Skill / Tool Selection
→ Tool Call
→ Observation
→ State Update
→ Re-plan
```

### 2.6 Separate Runtime from Engineering Capability

P4 负责通用 Agent Runtime；P5 实现 Code Review、UT Development / Repair 等具体 Engineering workflow。

P5 capability 不得各自复制 P1-P4 基础设施。

### 2.7 Separate Skill, Tool and Provider

- Skill 描述工程任务策略；
- Tool 执行受控动作；
- Provider/Adapter 隔离 clangd、GitCode 等外部系统私有协议。

长期 polling、平台事件和 Repository Knowledge 持久化不隐藏在 Skill Prompt 中。

### 2.8 Evaluation Starts Early

Evaluation 不是 P6 才开始。

- P1：Retrieval metrics
- P2：Graph / Trace metrics
- P3：Knowledge / Context metrics
- P4：Agent runtime metrics
- P5：Code Review + Coding / Repair metrics

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
- Task/Change Context ranking
- Token Budget
- Agent planning loop
- Code Host integration
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
- optional lifecycle trace（需独立 milestone；不属于当前 P2 Definition of Done）

## Out of Scope

- Task/Change Context ranking
- Token Budget
- Knowledge refresh orchestration
- GitCode integration
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

当前 P2 execution plan 按既有 scope 收尾，不因为未来 Code Review 需求新增 GitCode、polling、ReviewFinding 或 Context Builder 工作。

# 6. P3 — Task / Change Retrieval & Context Builder

## Goal

把 repository 中的大量事实压缩成与当前开发 Task 或代码 Change 直接相关的、版本可追溯的上下文。

P3 回答：

> 面对一个 Task 或 PR/Commit/Diff Change，后续 Agent 真正需要看到哪些代码和关系？当前上下文基于哪个 knowledge snapshot？

## In Scope

- KnowledgeSnapshot / repository revision identity
- freshness state 与 refresh result
- manual refresh entry point
- scheduler-invokable refresh entry point
- 基于已有 P1/P2 能力的 refresh/rebuild orchestration
- Task schema / parser
- platform-neutral Change schema
- changed file/hunk/range → changed symbol mapping
- Text / Symbol / Reference / Test Retrieval
- task/change-driven Graph Expansion
- Task / Change Subgraph Extraction
- candidate ranking / context tiering
- Token Budget
- Task Context Pack
- Review/Change Context Pack
- retrieval/context evaluation

## Out of Scope

- autonomous planning loop
- Skill/Tool runtime
- long-running PR polling
- GitCode authentication/API adapter
- review comment publishing
- code editing
- build
- repair

## Definition of Done

1. 给定自然语言/结构化 Task，可以生成结构化 Task Context Pack。
2. 给定平台无关的 Change，可以保留 base/head revision、changed file/hunk/range provenance，并在可证明时解析 changed symbol。
3. Task/Change 均可组合 Text/Symbol/Reference/Test/Graph retrieval。
4. candidate retrieval 与 final context 分离，并有明确 Token Budget。
5. 每个 snippet/relation 可追溯来源，并能解释为何被选入或排除。
6. 可以读取 KnowledgeSnapshot identity/status 并判断 freshness。
7. 支持显式 manual refresh，并允许 scheduler 调用同一 refresh entry point。
8. refresh 失败时不把 partial data 静默标记为 fresh。
9. Context Pack 记录 KnowledgeSnapshot identity。
10. 可以评估 Relevant Context Ratio、Missing Dependency Rate、Context Token Cost。
11. 不把整个 repository graph 或全仓代码直接塞入 LLM。

# 7. P4 — Agent Runtime

## Goal

让 LLM 基于 P1-P3 的共享能力执行多轮 repository-aware source analysis，并建立可供不同 Engineering Capabilities 复用的 Skill/Tool runtime。

P4 回答：

> Agent 如何计划、选择 Skill/Tool、处理 Observation、更新状态并结束任务，而不把 Code Review 或 UT workflow 写死进 runtime？

## In Scope

- tool contract / registry / executor
- skill contract / registry / invocation
- planner
- agent state
- observation / state update
- re-plan / retry
- stop condition / iteration limit
- execution trace
- knowledge/context tool integration
- read-only source analysis agent

## Out of Scope

- long-running GitCode polling
- GitCode review publishing
- arbitrary source editing
- ArkUI build pipeline
- UT repair loop

## Definition of Done

Agent 可以：

1. 接收开发/分析 Task 或结构化 Change context；
2. 生成和维护 Current Plan；
3. 根据状态选择受控 Tool/Skill；
4. 使用 P1/P2/P3，而不是绕过基础设施做无边界搜索；
5. 处理 Observation 并 Re-plan；
6. 触发明确 Stop Condition 并防止无限循环；
7. 处理 invalid tool/skill call；
8. 记录 Task/Change、Plan、Skill、Tool、Observation、Context、Snapshot identity、Iteration、Token Cost、Latency；
9. 在 read-only Source Analysis benchmark 上稳定完成任务；
10. runtime 不依赖 GitCode 私有 API，也不依赖 UT-only state machine。

# 8. P5 — Engineering Capabilities

## Goal

在 P1-P4 的共享 Repository-aware 基础设施上实现真实工程能力。

第一批能力：

```text
P5 Engineering Capabilities
├─ Code Review
└─ UT Development & Repair
```

## Code Review — In Scope

- CodeHostProvider abstraction / GitCodeProvider
- PR/change ingestion
- configurable polling watcher（可表达每 10 分钟等周期）
- PR author username filter
- base/head revision tracking 与 deduplication
- manual re-review entry
- knowledge freshness gate
- P3 Review Context
- Code Review Skill
- Stability / Memory-Lifetime / Functional / Test Impact review
- structured ReviewFinding
- review summary / inline comment publishing
- duplicate finding/comment suppression
- review execution trace

## Code Review — Definition of Done

对配置命中的受控/真实 GitCode PR review task，系统能够：

```text
Poll / Manual Trigger
→ Discover PR
→ Author Filter
→ Head Revision Dedup
→ Read Change
→ Ensure Knowledge Freshness
→ Build Review Context
→ Review
→ Produce 0..N Findings
→ Publish / Record Result
```

并满足：

1. polling interval 可配置；
2. 可按 PR author username 筛选；
3. 同一 PR 同一 head revision 不因轮询重复检视/评论，新 revision 可触发新 review；
4. GitCode 私有 schema 被 provider 隔离；
5. Review 使用 P1/P2/P3 supporting context，而不是 diff-only Prompt；
6. finding 有 source location、category、severity/confidence、evidence/provenance；
7. 至少支持 Stability、Memory/Lifetime、Functional、Test Impact；
8. 支持 zero findings；
9. stale/failed knowledge 不伪装成 fresh；
10. publish failure 可追踪并避免无限重复 spam；
11. evaluation 包含 No-Issue case。

## UT Development & Repair — In Scope

- Test Mapping
- Fixture / Similar Test / Mock Retrieval
- Coverage Gap / Test Intent
- UT Generation
- patch application
- minimal build / test target
- error parsing / failure classification
- root cause retrieval
- repair loop
- end-to-end UT workflow

## UT Development & Repair — Definition of Done

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

并记录 Compile Pass Rate、UT Pass Rate、Task Success Rate、Repair Success Rate、Average Iterations、Tool Calls、Token Cost、Latency。

## Shared Rules

- Code Review 与 UT 是 sibling capabilities，共享 P1/P2/P3/P4。
- Code Review 可以产生 Test Gap finding，后续交给 UT capability。
- P5 具体 milestone 接近开发时再拆入 `docs/exec-plans/active/`，当前 P2 不提前实现。

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
- Task / Change Context
- Code Review Stability
- Code Review Memory/Lifetime
- Code Review Functional Correctness
- Code Review Test Impact
- Code Review No-Issue case
- UT Generation
- UT Repair

## Metrics

### Retrieval

- Recall@K
- MRR
- Target File Recall
- Target Symbol Recall
- Call Chain Accuracy

### Knowledge / Context

- Snapshot Freshness Correctness
- Relevant Context Ratio
- Missing Dependency Rate
- Context Token Cost

### Agent

- Tool Success Rate
- Invalid Tool Call Rate
- Invalid Skill Call Rate
- Average Tool Calls
- Average Iterations

### Code Review

- Finding Precision
- Finding Recall
- False Positive Rate
- Category Accuracy
- Severity Accuracy
- Evidence / Provenance Validity
- Duplicate Comment Rate
- Review Latency

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

通用能力比较：

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

Code Review 额外比较：

```text
Diff-only LLM
vs
Diff + Text Retrieval
vs
Diff + Symbol Retrieval
vs
Diff + Code Graph
vs
Full Repository-aware Reviewer
```

## Definition of Done

1. benchmark dataset 固化；
2. evaluation command 可重复运行；
3. 结果可追踪到具体 task/change/component；
4. 失败案例可分类；
5. 完成主要 ablation comparison；
6. 有成本、延迟和成功率数据；
7. Code Review benchmark 含 No-Issue cases 并统计 false positive；
8. 对高频失败点完成 hardening；
9. 可以明确说明 Repository Intelligence、Code Graph、Knowledge Lifecycle、Context Builder 和 Agent Runtime 各自的增益或限制。

# 10. Phase Dependency

```text
P0 Engineering Foundation
        ↓
P1 Repository Intelligence
        ↓
P2 ArkUI Code Graph
        ↓
P3 Task / Change Retrieval & Context Builder
        ↓
P4 Agent Runtime
        ↓
P5 Engineering Capabilities
   ├─ Code Review
   └─ UT Development & Repair
        ↓
P6 Evaluation & Hardening
```

这不是绝对禁止并行开发。

Evaluation fixture、benchmark 标注、文档与测试基础可以提前并行建设，但核心能力依赖必须保持：

- P2 不绕过 P1 自己重新解析 repository facts；
- P3 不绕过 P1/P2 直接依赖 LLM 猜上下文；
- P3 Knowledge Manager 不复制 P1/P2 semantic/index/graph implementation；
- P4 不绕过 P3 长期依赖无约束 Prompt stuffing；
- P5 Code Review/UT 不各自复制 P1-P4 基础设施；
- GitCode 私有协议不泄漏到 P3 retrieval 或通用 review reasoning；
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

P3-P6 的细粒度 milestone 在接近对应 Phase 开发时再进入 `docs/exec-plans/active/`；本次长期路线修订不创建新的 active plan，也不改变当前 P2 milestone 状态。
