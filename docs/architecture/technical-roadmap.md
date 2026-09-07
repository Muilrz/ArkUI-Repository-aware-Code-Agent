# ArkUI Repository-aware Code Agent 技术路线

## 1. 项目目标

面向 OpenHarmony ArkUI Ace Engine 大型 C++ 代码库，构建 Repository-aware Code Agent，为组件源码分析、问题定位以及单元测试编写提供自动化支持。

Agent 不仅基于关键词搜索源码，而是通过源码符号索引、Code Graph、ArkUI 架构知识和任务级上下文构建，理解组件从 ArkTS / Bridge 到 Model、Pattern、Layout、Overlay 等模块的跨目录调用关系，并在此基础上完成代码定位、修改、编译、测试及失败修复。

整体技术链路：

Task
→ Repository Intelligence
→ Text / Symbol / Test Retrieval
→ Code Graph Expansion
→ Task Context Builder
→ Agent Runtime
→ Code Modification
→ Build / UT
→ Failure Repair
→ Evaluation

---

## 2. Repository Intelligence

首先对 ArkUI Ace Engine 工程建立结构化代码认知能力。

扫描整个代码仓库，提取并组织：

- Component
- File
- Namespace
- Class / Struct
- Function / Method
- Field
- Enum
- Test Fixture
- Test Case

等代码实体。

为每个 Symbol 记录：

- Symbol 名称与类型
- 所属文件及代码范围
- Namespace / Parent Class
- Declaration
- Definition
- Caller / Callee
- Reference
- Test Mapping

形成统一的 Symbol Index。

支持基础查询能力：

- 在 repository 边界内按文本 / 正则搜索源码内容
- 根据组件定位源码目录
- 根据类 / 函数定位声明与实现
- 查询函数 Reference
- 查询 Caller / Callee
- 定位对应 Test Fixture / Test Case
- 查找相似实现或相似测试

文本检索用于字符串、宏、测试写法、错误文本等非 Symbol 场景；Symbol identity、Declaration、Definition、Reference、Caller / Callee 等 C++ 语义关系由 semantic retrieval 提供，namespace、class member、overload 等语义不通过纯文本匹配推断。

Repository Intelligence 作为整个 Agent 的底层基础设施，不直接依赖 LLM。

---

## 3. ArkUI Code Graph

P2 的当前层次、边界与规范索引见 [`code-graph-architecture.md`](code-graph-architecture.md)。本文只保留长期架构方向。

在 Symbol Index 之上构建面向 ArkUI 框架的代码关系图。

节点包括：

- Component
- ArkTS API
- Bridge
- Model
- Pattern
- LayoutProperty
- PaintProperty
- LayoutAlgorithm
- OverlayManager
- TestFixture
- Function
- Class

边类型包括：

- DECLARE
- DEFINE
- CALL
- REFERENCE
- INHERIT
- OVERRIDE
- CREATE
- UPDATE_PROPERTY
- MEASURE
- LAYOUT
- SHOW
- CLOSE
- TEST
- MOCK

相比普通 Call Graph，更强调 ArkUI Framework Architecture。

重点支持几类 Domain-aware Trace：

### Component Creation Trace

ArkTS
→ Bridge
→ Model
→ FrameNode
→ Pattern

### Property Update Trace

ArkTS Property
→ Bridge
→ Model::SetXXX
→ LayoutProperty / PaintProperty
→ Pattern / Render

### Measure / Layout Trace

Pattern
→ CreateLayoutAlgorithm
→ Measure
→ Layout
→ LayoutProperty

### Overlay Trace

Show
→ OverlayManager
→ Node
→ Pattern
→ Animation
→ Close

### Lifecycle Trace

Create
→ Attach
→ Modify
→ Layout
→ Detach

最终根据用户任务，从整个 Repository Graph 中动态抽取 Task Subgraph。

---

## 4. Task Retrieval

根据用户输入的开发任务解析：

- Component
- Target Symbol
- Property
- Action
- Test Intent

例如：

“给 MenuItem 的 selected 属性补 UT”

首先解析：

Component = MenuItem
Property = selected
Task Type = UT

然后进行多路检索：

### Text Retrieval

检索：

- Source Text
- String Literal
- Macro
- Test Assertion Pattern
- Error Text
- Non-symbol Code Pattern

### Symbol Retrieval

检索：

- MenuItemModel
- MenuItemPattern
- MenuItemLayoutProperty
- SetSelected
- UpdateSelected

### Reference Retrieval

查询：

- Declaration
- Definition
- Caller
- Reference
- Override

### Test Retrieval

检索：

- MenuItemTestNg
- Test Fixture
- Existing Case
- Similar Property Test
- Mock

### Code Graph Expansion

从目标 Symbol 沿 ArkUI Code Graph 向上下游扩展。

最终得到与任务相关的候选代码集合。

---

## 5. Task Context Builder

将 Retrieval 得到的大量代码进一步整理为任务级上下文，而不是直接将所有搜索结果输入 LLM。

Context Builder 按优先级组织：

### Tier 1：Must-have Context

- 用户任务
- Target Symbol
- Function Definition
- Class Definition
- Direct Dependency

### Tier 2：Task Related Context

- Caller / Callee
- Property Definition
- Pattern / Layout / Model
- Test Fixture
- Existing Test

### Tier 3：Optional Context

- Similar Implementation
- Similar Test
- Mock
- Neighbor Component

最终形成统一的 Task Context Pack：

- Task
- Target
- Related Symbols
- Call Chain
- Source Snippets
- Existing Tests
- Similar Cases
- Mock Dependencies

并通过 Token Budget 控制上下文规模。

Context Builder 是 Agent 与代码库之间的核心中间层。

---

## 6. Agent Runtime

在 Repository Intelligence 和 Context Builder 基础上构建 Agent Runtime。

执行流程采用：

Planning
→ Tool Call
→ Observation
→ State Update
→ Re-plan

Agent State 保存：

- Current Task
- Current Plan
- Retrieved Symbols
- Relevant Files
- Current Patch
- Build Result
- Test Result
- Error State

工具包括：

- text_search
- search_symbol
- search_file
- find_definition
- find_reference
- find_caller
- find_test
- build_context
- read_file
- edit_file
- run_build
- run_test

Runtime 负责根据任务动态选择 Tool，而不是直接依赖单次 LLM 推理完成代码修改。

---

## 7. UT Generation Pipeline

UT 编写采用 Test-first Retrieval，而不是直接让 LLM 根据目标函数生成测试。

流程：

Target Function
→ Test Mapping
→ Existing Fixture
→ Similar Test
→ Mock Dependency
→ Coverage Gap
→ Generate UT

Agent 首先确认：

- 测试文件位置
- Test Fixture
- Component 如何初始化
- 必要 Mock
- 同类测试写法
- Assert Pattern

然后生成新的测试 Case。

这样避免生成与项目测试框架不一致的 UT。

---

## 8. Build / Test Repair Loop

代码修改后进入自动验证闭环。

Agent 执行：

Patch
→ Compile
→ Run Minimal Test Target

如果失败，对错误进行分类：

- Compilation Error
- Link Error
- Missing Mock
- API Misuse
- Assertion Failure
- Runtime Crash

随后执行：

Failure
→ Error Parsing
→ Root Cause Retrieval
→ Context Update
→ Patch
→ Re-run

形成自动 Repair Loop。

优先执行最小 Test Target，避免每轮重新编译整个 ArkUI 工程。

---

## 9. Memory 设计

Memory 不作为项目核心卖点，而作为 Agent Runtime 的辅助能力。

主要划分：

### Working Memory

保存当前 Agent Loop 的：

- Task
- Plan
- Observation
- Intermediate Result

### Task Memory

保存当前开发任务相关的：

- Symbols
- Files
- Call Chain
- Patch
- Test Result

### Repository Knowledge

长期稳定信息不直接存储为 LLM Memory，而主要沉淀在：

- Symbol Index
- Code Graph
- Component Metadata
- Test Mapping

减少长期 Memory 与源码版本不一致的问题。

---

## 10. Execution Trace

每次 Agent 执行记录完整 Trace：

- Task
- Plan
- Tool
- Tool Arguments
- Observation
- Retrieved Context
- Patch
- Build Result
- Test Result
- Iteration
- Token Cost
- Latency

用于：

- Agent Debug
- Failure Analysis
- Evaluation
- Prompt / Skill 优化

---

## 11. Agent Evaluation

Evaluation 从项目早期同步建设，而不是最后补充。

### Retrieval 指标

- Recall@K
- MRR
- Target File Recall
- Target Symbol Recall
- Call Chain Accuracy

### Context 指标

- Relevant Context Ratio
- Missing Dependency Rate
- Context Token Cost

### Agent 指标

- Tool Success Rate
- Invalid Tool Call Rate
- Average Tool Calls
- Average Iterations

### Coding 指标

- Compile Pass Rate
- UT Pass Rate
- Task Success Rate
- Repair Success Rate

### Cost 指标

- Token Usage
- Latency
- Tool Call Count

最终进行 Ablation Comparison：

LLM Only
vs
Keyword Search
vs
Symbol Retrieval
vs
Code Graph Retrieval
vs
Code Graph + Agent

---

## 12. 开发阶段

### Phase 1：Repository Intelligence

完成：

- Repo Scanner
- Repository Text Search
- Symbol Extractor
- File / Class / Function Index
- Test Index
- Definition / Reference Query

目标是实现：

- 在 repository 边界内执行受控文本检索
- 输入一个 ArkUI Function，可以返回：

- Declaration
- Definition
- References
- Caller
- Test Case

---

### Phase 2：ArkUI Code Graph

完成：

- Symbol Graph
- Component Graph
- Test Graph
- Framework Relation

重点支持：

- Component Creation
- Property Update
- Measure / Layout
- Overlay Show / Close

调用链分析。

---

### Phase 3：Task Context Builder

完成：

- Task Parser
- Multi-channel Retriever
- Graph Expansion
- Context Ranking
- Token Budget
- Context Pack

---

### Phase 4：Agent Runtime

完成：

- Planner
- Tool Executor
- State
- Observation
- Retry
- Stop Condition
- Execution Trace

---

### Phase 5：UT Agent

完成：

- Test Mapping
- Fixture Retrieval
- Similar Case Retrieval
- Mock Retrieval
- UT Generation
- Minimal Target Build
- Repair Loop

---

### Phase 6：Evaluation

选择 Button、Text、Menu、Dialog、Tabs、List 等典型组件建立 Benchmark。

任务覆盖：

- Component Creation
- Property Trace
- Layout Trace
- Source Analysis
- UT Generation
- UT Repair

最终统计：

- Retrieval Recall
- Call Chain Accuracy
- UT Pass Rate
- Agent Success Rate
- Iteration
- Token Cost
