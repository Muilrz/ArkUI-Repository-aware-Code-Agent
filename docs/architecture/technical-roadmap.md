# ArkUI Repository-aware Code Agent 技术路线

## 1. 项目目标

面向 OpenHarmony ArkUI Ace Engine 大型 C++ 代码库，构建 Repository-aware Engineering Agent，为源码分析、在线代码检视、问题定位、单元测试开发与修复等工程任务提供自动化支持。

项目名称继续使用 **ArkUI Repository-aware Code Agent**。Repository-aware 是系统的核心：Agent 的判断应建立在可追溯、可重建、与目标仓库 revision 对齐的 repository facts 上，而不是只依赖关键词搜索、单次 Prompt 或长期 LLM memory。

P1 Repository Intelligence、P2 ArkUI Code Graph、P3 Task / Change Retrieval & Context Builder 和 P4 Agent Runtime 是多个 Engineering Capabilities 共享的基础设施。Code Review 与 UT Development / Repair 是第一批上层能力。

整体技术链路：

```text
User Task / PR / Commit / Scheduled Trigger
                    ↓
          Repository Knowledge
        ┌───────────┴───────────┐
        ↓                       ↓
Repository Intelligence    ArkUI Code Graph
        └───────────┬───────────┘
                    ↓
         Knowledge Snapshot
                    ↓
      Task / Change Retrieval
                    ↓
           Context Builder
                    ↓
           Agent Runtime
        + Skill / Tool Framework
                    ↓
      ┌─────────────┴─────────────┐
      ↓                           ↓
Code Review Capability     UT Development / Repair
      ↓                           ↓
Review Findings            Patch / Build / Test / Repair
      └─────────────┬─────────────┘
                    ↓
                Evaluation
```

核心原则：

- Repository Intelligence 不依赖 LLM。
- 通用 C++ facts 与 ArkUI domain knowledge 分层维护。
- Repository-derived persistent knowledge 沉淀在 index / graph / metadata 中，而不是长期 LLM memory。
- Task / Change candidate retrieval 与最终 context selection 分离。
- Agent Runtime 与具体 Engineering Capability 分离。
- Skill 描述工程任务策略；Tool 执行受控动作；外部系统通过 provider / adapter 集成。
- Evaluation 从底层能力开始持续建设。

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

重点支持：

### Component Creation Trace

```text
ArkTS
→ Bridge
→ Model
→ FrameNode
→ Pattern
```

### Property Update Trace

```text
ArkTS Property
→ Bridge
→ Model::SetXXX
→ LayoutProperty / PaintProperty
→ Pattern / Render
```

### Measure / Layout Trace

```text
Pattern
→ CreateLayoutAlgorithm
→ Measure
→ Layout
→ LayoutProperty
```

### Overlay Trace

```text
Show
→ OverlayManager
→ Node
→ Pattern
→ Animation
→ Close
```

### Lifecycle Trace

```text
Create
→ Attach
→ Modify
→ Layout
→ Detach
```

P2 提供通用、可追溯的 framework-aware graph relation；根据具体 Task 或 Change 抽取任务级 subgraph 属于 P3。

---

## 4. Repository Knowledge Lifecycle

Repository Knowledge 是 P1/P2 派生事实的版本化运行时视图，不等同于 LLM memory。它是多个 Engineering Capabilities 共享的平台能力，而不是 Code Review 私有知识库。

长期知识主要由以下内容组成：

- target repository identity / revision metadata；
- P1 Symbol / Text / Test Index；
- P2 Code Graph；
- ArkUI component / framework metadata；
- snapshot / freshness / refresh metadata。

“全仓知识”表示对 P1/P2 已支持 repository facts 的全仓范围、版本一致、可重建组织，不意味着静态分析能够穷尽所有 runtime state、并发行为或内存状态。无法从现有 facts 证明的行为仍应显式保留 unknown / insufficient evidence。

### 4.1 Knowledge Snapshot and Freshness

系统维护逻辑上的 `KnowledgeSnapshot`，至少能够追溯：

```text
KnowledgeSnapshot
├─ repository identity / revision
├─ symbol index identity / revision
├─ code graph identity / revision
├─ metadata identity / revision
├─ built_at
├─ refresh reason / result
└─ freshness / build status
```

具体字段和存储 schema 不在 roadmap 冻结，未来实现后进入对应 spec。

同一 snapshot 中的 P1/P2 派生数据应对应同一 target repository revision，或明确记录可接受的兼容关系；不得把 old index、new graph 和 unknown repository revision 静默组合成“当前全仓知识”。

freshness 至少保留以下语义：

- `fresh`：与目标 revision 对齐，可以直接使用；
- `stale`：目标 repository 已变化，需要 refresh/rebuild；
- `building`：正在构建，不应被视为完整 fresh snapshot；
- `failed`：最近一次 refresh 失败；
- `unknown`：无法证明 snapshot 与目标 revision 的关系。

Context Pack、ReviewFinding 和 Agent Observation 等上层结果应能够追溯所使用的 repository revision、knowledge snapshot 以及关键 P1/P2 evidence。

### 4.2 Refresh Triggers and Strategy

需要支持：

- **周期刷新**：scheduler 周期检查 repository revision，例如每天检查一次；revision 未变化时不要求无条件重复 rebuild；具体时间/周期可配置。
- **手动刷新**：提供明确、可测试的 command/service entry point，并预留 force refresh。
- **任务前 freshness check**：Code Review 等能力在构建上下文前确认当前 snapshot 与目标 change/revision 兼容。

第一版优先保证正确性：repository revision 变化时允许全量 rebuild P1/P2 派生知识，再原子地发布新的 KnowledgeSnapshot。changed-file incremental indexing、partial graph rebuild、snapshot reuse 等属于真实性能数据驱动的后续优化。

refresh 失败时不得把 partial data 静默发布为 `fresh`；应保留最后一个已知可用 snapshot 的 identity/status，并让上层 capability 明确知道当前知识是否 stale/failed。是否允许基于 stale snapshot 继续执行由具体 capability policy 决定，并必须在结果中显式反映。

Repository Knowledge 属于 target repository 的可重建派生数据：不进入 Git，不 vendor target repository，运行时数据遵守项目现有 `var/` / generated-data 边界。

### 4.3 Phase Ownership

- **P1**：提供可重建的通用 repository facts 与 index。
- **P2**：提供可重建的 ArkUI Code Graph 与 domain facts。
- **P3**：正式引入共享 Knowledge Snapshot / freshness contract、refresh orchestration entry point，并让 Task/Change Context Pack 记录 snapshot identity；P3 不负责长期 daemon。
- **P4**：以 Tool 形式暴露受控 knowledge query / freshness 能力，Agent 不直接操作底层数据库文件。
- **P5**：Code Review、UT Development / Repair 等 capability 共用 Knowledge Lifecycle，不维护私有全仓知识副本；scheduled watcher 只调用共享 refresh entry point。

---

## 5. Task / Change Retrieval

P3 的输入同时支持自然语言 Task 和代码 Change。

### Task Input

例如：

```text
给 MenuItem 的 selected 属性补 UT
```

解析：

```text
Component = MenuItem
Property = selected
Task Type = UT
```

关注：

- Component
- Target Symbol
- Property
- Action
- Test Intent

### Change Input

Code Review 等能力可以从 PR / Commit / Diff 得到平台无关的 Change seed：

- base / head revision
- changed files
- changed hunks / ranges
- changed symbols
- change provenance

GitCode 私有字段由 Code Host adapter 转换，不进入 P3 retrieval contract。

### Multi-channel Retrieval

Task / Change 共享：

- Text Retrieval
- Symbol Retrieval
- Declaration / Definition / Reference Retrieval
- Caller / Callee / inheritance / override Retrieval
- Test Retrieval
- ArkUI Code Graph Expansion

最终得到与当前 Task / Change 相关的候选代码和关系集合，而不是把整个 Repository Graph 输入 LLM。

---

## 6. Task / Change Context Builder

将 Retrieval 得到的大量 repository facts 整理为任务级或变更级上下文。

### Tier 1：Must-have Context

- Task / Change summary
- Target / Changed Symbol
- Function / Class Definition
- changed hunks（Change 场景）
- Direct Dependency

### Tier 2：Task / Change Related Context

- Caller / Callee / Reference
- Property / Pattern / Layout / Model
- framework-aware relation / trace
- Test Fixture / Existing Test

### Tier 3：Optional Context

- Similar Implementation
- Similar Test
- Mock
- Neighbor Component

最终形成统一 Context Pack：

```text
Context Pack
- Input Task / Change
- Target / Changed Symbols
- Related Symbols
- Call / Framework Relations
- Source Snippets
- Existing Tests
- Similar Cases
- Mock Dependencies
- Provenance
- Knowledge Snapshot Identity
```

Context Builder 负责 candidate ranking、context tiering 和 Token Budget，并保留每个 snippet / relation 的 provenance。

---

## 7. Agent Runtime、Skill 与 Tool

在 P1-P3 基础上构建通用 Agent Runtime。

执行流程：

```text
Planning
→ Skill / Tool Selection
→ Tool Call
→ Observation
→ State Update
→ Re-plan
→ Stop
```

### Agent Runtime

负责：

- Planner
- Agent State
- Observation
- Retry / Error Handling
- Stop Condition / Iteration Limit
- Tool execution
- Skill invocation
- Execution Trace

### Tool

Tool 执行受控动作，例如：

- repository text / symbol / graph query
- knowledge snapshot / refresh
- file read / patch application
- build / test
- code host read / review publish

外部工具与平台必须隐藏在 provider / adapter 边界后。

### Skill

Skill 描述如何组合 Tool 完成一种工程任务，例如：

- ArkUI source analysis
- ArkUI code review
- ArkUI UT development / repair

Skill 不负责长期轮询线程，也不使用 LLM memory 保存全仓知识。

P4 第一阶段仍优先验证 read-only source analysis；具体 Code Review / UT workflow 属于 P5。

---

## 8. Code Review Capability

详细设计见 [`code-review-architecture.md`](code-review-architecture.md)。

GitCode 是第一目标平台，但上层通过通用 `CodeHostProvider` 工作。

核心链路：

```text
Polling / Manual / Future Webhook Trigger
                ↓
        GitCodeProvider
                ↓
      PR / Change Metadata
                ↓
       Author / Repo Filter
                ↓
   Head Revision Deduplication
                ↓
   Knowledge Freshness Check
                ↓
       Review Context Pack
                ↓
       ArkUI Review Skill
                ↓
       Structured Finding
                ↓
        GitCode Publisher
```

第一版需求：

- 轮询间隔可配置，例如每 10 分钟；
- 可按 PR 作者用户名筛选；
- 同一 PR 同一 head revision 避免重复 review/comment；
- 检视前确认 Repository Knowledge freshness；
- 至少检视 Stability、Memory/Lifetime、Functional Correctness、Test Impact；
- 内部使用结构化 ReviewFinding，再由 publisher 转换为平台评论；
- 允许合法的 zero findings，不要求每个 PR 强行找问题。

GitCode authentication、HTTP schema、pagination、comment positioning 等平台细节留在 provider 内。

---

## 9. UT Development & Repair Capability

UT 编写继续采用 Test-first Retrieval：

```text
Target Function
→ Test Mapping
→ Existing Fixture
→ Similar Test
→ Mock Dependency
→ Coverage Gap
→ Generate UT
```

Agent 首先确认：

- 测试文件位置
- Test Fixture
- Component 初始化方式
- 必要 Mock
- 同类测试写法
- Assert Pattern

生成 patch 后进入验证闭环：

```text
Patch
→ Compile
→ Minimal Test
→ Failure Classification
→ Root Cause Retrieval
→ Context Update
→ Patch
→ Re-run
```

失败类别包括但不限于：

- Compilation Error
- Link Error
- Missing Mock
- API Misuse
- Assertion Failure
- Runtime Crash

Code Review 与 UT Development / Repair 是 sibling capabilities。Code Review 可以发现 Test Gap，后续由 UT capability 负责生成/修复测试。

---

## 10. Memory 设计

Memory 不作为项目核心 repository knowledge 存储。

### Working Memory

保存当前 Agent Loop 的：

- Task / Change
- Plan
- Observation
- Intermediate Result

### Task / Review Memory

保存单次工程任务相关的：

- Symbols
- Files
- Context Pack
- Findings / Patch
- Build / Test Result

### Repository Knowledge

长期稳定信息主要沉淀在：

- Symbol Index
- Code Graph
- Component Metadata
- Test Mapping
- Knowledge Snapshot metadata

Repository Knowledge 的 freshness 由明确 lifecycle 管理。

---

## 11. Execution Trace

每次 Agent 执行记录完整 Trace：

- Task / Change
- Plan
- Skill
- Tool
- Tool Arguments
- Observation
- Retrieved Context
- Knowledge Snapshot Identity
- Iteration
- Token Cost
- Latency

UT workflow 可额外记录：

- Patch
- Build Result
- Test Result
- Repair Classification

Code Review workflow 可额外记录：

- PR / base / head revision
- Filter / dedup decision
- ReviewFinding
- publish result

用于 Agent Debug、Failure Analysis、Evaluation 和 Prompt / Skill 优化。

---

## 12. Agent Evaluation

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

### Code Review 指标

- Finding Precision
- Finding Recall
- False Positive Rate
- Category Accuracy
- Severity Accuracy
- Evidence / Provenance Validity
- Duplicate Comment Rate
- Review Latency

Code Review benchmark 必须包含 **No-Issue PR / Change**，避免形成“每次检视都必须找出问题”的偏差。

### Coding 指标

- Compile Pass Rate
- UT Pass Rate
- Task Success Rate
- Repair Success Rate

### Cost 指标

- Token Usage
- Latency
- Tool Call Count

通用 Ablation：

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

---

## 13. 开发阶段

### P0 — Engineering Foundation

建立 repository workspace、配置、测试 fixture 与运行时数据边界。

### P1 — Repository Intelligence

建立不依赖 LLM 的 Text / Symbol / Definition / Reference / Caller / Callee / Test repository facts。

### P2 — ArkUI Code Graph

建立 framework-aware graph relation 与 Creation、Property、Measure/Layout、Overlay 等 domain traces。

当前 P2 按既有 execution plan 收尾，不因未来 Code Review 需求扩 scope。

### P3 — Task / Change Retrieval & Context Builder

建立：

- Knowledge Snapshot / Freshness contract
- manual / scheduler-invokable refresh entry point
- Task / Change input model
- Multi-channel Retrieval
- Task / Change Graph Expansion
- Context Ranking / Token Budget
- Context Pack

P3 不负责长期 PR watcher，也不负责 Agent autonomous loop。

### P4 — Agent Runtime

建立：

- Planner
- Tool Contract / Registry / Executor
- Skill Contract / Registry / Invocation
- State / Observation
- Retry / Stop Condition
- Execution Trace
- read-only source analysis Agent

### P5 — Engineering Capabilities

第一批能力：

- **Code Review**：GitCode provider、PR/change ingestion、configurable polling、author filtering、revision dedup、knowledge freshness gate、review skill、ReviewFinding、publisher。
- **UT Development & Repair**：Test Mapping、UT Generation、Patch、Minimal Build/Test、Failure Classification、Repair Loop。

P5 的细粒度 milestone 在接近开发时再进入 active execution plan。

### P6 — Evaluation & Hardening

整合 P1-P5 持续建设的 evaluation，形成正式 benchmark、ablation、稳定性验证与 hardening，覆盖 Code Review（含 No-Issue cases）和 UT workflow。

---

## 14. Phase Dependency

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

核心依赖保持：

- P2 不绕过 P1 重建通用 C++ facts；
- P3 不绕过 P1/P2 直接依赖 LLM 猜 repository context；
- P4 不绕过 P3 长期依赖无约束 Prompt stuffing；
- P5 capability 不复制 P1-P4 基础设施；
- P6 不成为唯一存在 evaluation 的阶段。
