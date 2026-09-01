# P1 — Repository Intelligence

- **Phase Status:** In Progress
- **Phase Goal:** 建立不依赖 LLM 的 Repository Intelligence，使系统能够查询 C++ symbol、definition、reference、caller/callee 与 test mapping。
- **Source of Truth:** `docs/architecture/technical-roadmap.md`
- **Phase Boundary:** `docs/exec-plans/phase-map.md`

## P1-A — Repository Scanner

- **Status:** Completed

### Goal
在 `RepositoryWorkspace` 之上发现 target repository 中符合约定范围的文件，为后续数据模型与 semantic provider 提供稳定输入。

### Scope
- recursive file discovery
- normalized repository-relative path
- configurable include/exclude rules
- source/header/test file classification 的最小通用规则
- deterministic scan output

### Non-goals
- parsing C++
- extracting symbols
- clangd
- ArkUI component recognition
- indexing
- graph construction

### Dependencies
- P0 completed

### Acceptance Criteria
1. 可以扫描 temporary repository。
2. 输出稳定、可重复。
3. 路径统一为 repository-relative canonical form。
4. 可以忽略 `.git`、build、generated/runtime 目录。
5. 不读取 root 外文件。
6. 不解析源文件内容。
7. 真实 ArkUI repository 上可做受控 smoke scan。

### Tests / Validation
- nested directory scan
- ignored directory
- extension filtering
- deterministic ordering
- root boundary

## P1-B — File / Symbol Data Model

- **Status:** Not Started

### Goal
定义 P1 统一数据契约，使 scanner、semantic provider、index、retrieval 不通过私有结构互相耦合。

### Scope
至少考虑：
- File
- SourceLocation
- SourceRange
- Symbol
- SymbolKind
- Namespace / Parent relation
- Declaration / Definition location
- basic relation identity
- Test Fixture / Test Case 扩展兼容性

### Non-goals
- ArkUI domain node
- Code Graph
- database schema implementation
- retrieval ranking
- LLM context

### Dependencies
- P0 completed
- 可与 P1-A 小范围并行，但最终接口需收敛

### Acceptance Criteria
1. model 能表达 file、class/struct、function/method、field、enum、namespace 等 P1 基础实体。
2. symbol identity 与 display name 区分。
3. source location/range 表达清晰。
4. 支持 declaration 与 definition 分离。
5. model 不绑定 clangd 私有 response schema。
6. model 可序列化或转换为持久化表示。
7. 有 model contract tests。

## P1-C — C++ Semantic Provider Contract

- **Status:** Not Started

### Goal
定义可替换的 C++ semantic backend 接口，使上层 Repository Intelligence 不依赖 clangd/Clang 的具体协议。

### Scope
- provider protocol / abstract interface
- semantic query/result contracts
- provider error boundary
- fake/test provider
- contract tests

### Non-goals
- 真正启动 clangd
- build compile database generation
- index persistence
- retrieval facade

### Dependencies
- P1-B completed

### Expected Capabilities
Provider contract 至少为后续能力预留：
- symbols in file
- declaration
- definition
- references
- caller/callee 或 call hierarchy
- inheritance / override（若 backend 能提供）

不要求 P1-C 就一次性实现全部真实能力。

### Acceptance Criteria
1. 上层代码只依赖 provider contract。
2. provider result 使用 P1-B 统一模型或明确转换层。
3. fake provider 可以在 tests 中稳定模拟 semantic facts。
4. provider 生命周期与错误行为明确。
5. 没有 clangd-specific type 泄漏到 retrieval API。

## P1-D — Clang/clangd Semantic Backend

- **Status:** Not Started

### Goal
实现第一个真实 C++ semantic provider backend。

### Scope
- clangd 或 Clang backend adapter
- external process / protocol lifecycle
- source position conversion
- semantic result conversion
- controlled synthetic C++ fixture integration

### Non-goals
- Repository Index
- ArkUI Code Graph
- Task Context
- Agent
- 自动生成 compile_commands

### Dependencies
- P1-C completed
- P0-B completed

### Design Constraint
优先保证语义正确性和接口隔离，不要为了早期性能一次性构建复杂 daemon management。

compile database 应作为外部 repository/toolchain input 对待。

### Acceptance Criteria
1. synthetic C++ fixture 上可以获取真实 semantic data。
2. namespace/class member/overload 不靠 regex 猜测。
3. backend failure 有清晰错误。
4. backend-specific response 在 adapter 内转换。
5. integration tests 可明确 skip/报告缺失外部工具，而不是假通过。
6. 上层 provider contract 无需因 backend 细节改变。

## P1-E — Symbol Index

- **Status:** Not Started

### Goal
持久化 P1 repository facts，并提供稳定、可重建的基础 symbol query。

### Scope
- index schema
- file records
- symbol records
- semantic relation records
- rebuild/update strategy 的最小版本
- query interface
- generated-data path

### Non-goals
- ArkUI domain graph
- vector database
- LLM memory
- complex incremental build optimization

### Dependencies
- P1-B completed
- P1-C/P1-D 已具备可消费 semantic output

### Acceptance Criteria
1. 可以 ingest 统一 model。
2. 可以按 symbol name / qualified name 查询。
3. 可以定位 file/range。
4. index 可删除后重建。
5. index 数据不进入 Git。
6. schema 不绑定单一 semantic backend。
7. 有 unit tests 和 small integration test。

## P1-F — Definition / Declaration Retrieval

- **Status:** Not Started

### Goal
建立稳定的 declaration / definition retrieval API。

### Scope
- search symbol candidate
- declaration lookup
- definition lookup
- ambiguity handling
- qualified symbol identity

### Non-goals
- reference retrieval
- caller/callee
- ArkUI trace
- ranking entire task context

### Dependencies
- P1-E completed

### Acceptance Criteria
1. synthetic fixture 返回正确 declaration。
2. synthetic fixture 返回正确 definition。
3. declaration/definition 分离时结果正确。
4. namespace/class member 可以正确区分。
5. overload ambiguity 不被静默错误解析。
6. 结果可追溯 source range。
7. 真实 ArkUI symbol 有 smoke validation。

## P1-G — Reference + Caller / Callee Retrieval

- **Status:** Not Started

### Goal
建立 symbol reference 与 call relation 查询能力。

### Scope
- references
- callers
- callees
- direct call relation
- result deduplication
- source provenance

### Non-goals
- ArkUI domain trace
- transitive task graph expansion
- context ranking

### Dependencies
- P1-F completed
- P1-D/P1-E semantic relation support

### Acceptance Criteria
1. fixture references 返回预期集合。
2. direct callers 正确。
3. direct callees 正确。
4. relation 可以定位到 source location。
5. symbol identity 不通过纯文本同名匹配。
6. 结果去重且顺序稳定。
7. 有真实 ArkUI smoke validation。

## P1-H — Test Fixture / Test Case Index

- **Status:** Not Started

### Goal
把 test fixture / test case 作为一等 repository entity，建立后续 UT Agent 所需 Test-first Retrieval 基础。

### Scope
- Test Fixture entity
- Test Case entity
- source location
- fixture-to-case relation
- tested-symbol 基础 mapping
- ArkUI 常见测试宏识别的最小适配

### Non-goals
- Similar Test ranking
- Mock Retrieval
- Coverage Gap
- UT generation

### Dependencies
- P1-E completed
- P1-G 可提供 reference facts

### Acceptance Criteria
1. synthetic fixture 中可以定位 Test Fixture。
2. 可以定位 Test Case。
3. Test Case 可以关联源文件与 range。
4. 可以建立基础 symbol ↔ test mapping。
5. 测试实体进入统一 index/query 边界。
6. 不通过 LLM 判断测试关联。
7. 真实 ArkUI test file 有 integration validation。

## P1-I — Real ArkUI Validation & Retrieval Baseline

- **Status:** Not Started

### Goal
在真实 OpenHarmony ArkUI Ace Engine repository 上验收 P1，并建立后续优化所需 retrieval baseline。

### Scope
- representative component selection
- real symbol query set
- expected result annotation
- retrieval metrics baseline
- known failure taxonomy
- performance/cost observations

### Candidate Components
优先从长期路线建议的代表性组件中选择：
- Button
- Text
- Menu
- Dialog
- Tabs
- List

P1 阶段不要求全部覆盖，可先选择 2-3 个完成 baseline，再扩展。

### Required Queries
至少覆盖：

```text
search_symbol
find_declaration
find_definition
find_references
find_callers
find_callees
find_tests
```

### Metrics
至少记录：
- Target File Recall
- Target Symbol Recall
- Recall@K（适用于候选查询）
- MRR（适用于 ranked symbol search）
- query latency
- failure category

Call Chain Accuracy 的正式 domain trace 主要属于 P2，但 P1 可以记录 direct caller/callee correctness。

### Acceptance Criteria
1. 使用外部只读 ArkUI repository。
2. 不提交 ArkUI 派生 index / compile database。
3. 至少 2-3 个代表性组件完成验证。
4. 每类核心 retrieval API 有真实案例。
5. 有人工确认的 expected result。
6. 记录失败案例，而不是只保留成功样例。
7. 形成可重复运行的 baseline command 或 evaluation entry point。
8. P1 Definition of Done 全部满足。

# P1 Definition of Done

只有 P1-A 至 P1-I 全部 Completed，P1 才能标记 Completed。

P1 完成后，系统应具备：

```text
C++ Repository
      ↓
Repository Intelligence
      ↓
Symbol / Definition / Reference / Caller / Callee / Test
```

并且整个链路不依赖 LLM。

P1 完成后才正式进入 P2 ArkUI Code Graph。
