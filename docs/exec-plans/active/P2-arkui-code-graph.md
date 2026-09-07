# P2 — ArkUI Code Graph

- **Phase Status:** In Progress
- **Phase Goal:** 在 P1 Repository Intelligence 提供的通用 C++ repository facts 之上，构建 ArkUI framework-aware Code Graph，使系统能够表达并查询 Component、Model、Pattern、Layout、Overlay、Test 等领域实体及关系，并稳定分析典型 ArkUI framework trace。
- **Source of Truth:** `docs/architecture/technical-roadmap.md`
- **Phase Boundary:** `docs/exec-plans/phase-map.md`

## Phase Boundary

P2 消费 P1 已提供的：

- File / Symbol
- Declaration / Definition
- Reference
- Caller / Callee
- Test Fixture / Test Case
- Text Search

P2 新增：

- Graph node / edge model
- Symbol Graph
- Test Graph
- ArkUI Component Graph
- ArkUI framework role
- Framework-aware relation
- Domain Trace

P2 不负责：

- Task Parser
- Multi-channel Retrieval
- Task-driven Graph Expansion
- Context Ranking
- Token Budget
- Context Pack
- Agent Planner / Runtime
- Source Code Modification
- Build / Test / Repair Loop

这些能力分别属于 P3、P4、P5。

---

# P2-A — Graph Model & Query Contract

- **Status:** Completed

## Goal

建立 P2 统一图数据模型和查询边界，使后续 Symbol Graph、Component Graph、Test Graph 与 Framework Relation 使用相同的数据契约。

## Scope

定义至少包括：

### Graph Node

支持：

- Symbol
- Function / Method
- Class
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
- TestCase

节点需要能够关联回 P1 symbol/file/source location。

### Graph Edge

至少为以下关系预留统一表示：

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

每条 edge 至少保存：

- source node
- target node
- relation type
- source provenance
- source location / evidence
- relation identity

### Query Contract

至少支持：

- node lookup
- incoming edges
- outgoing edges
- relation type filtering
- direct neighbor query
- bounded graph traversal

## Non-goals

- ArkUI role recognition
- Framework relation extraction
- Trace algorithm
- Task-specific graph expansion
- Graph ranking
- LLM context generation
- 引入复杂专用 Graph Database

## Dependencies

- P1 completed

## Acceptance Criteria

1. Graph node / edge 有稳定统一的数据模型。
2. Graph identity 与 display name 分离。
3. Graph entity 可以追溯到 P1 symbol/file/source range。
4. Edge 可以记录 relation provenance。
5. 同一 relation 可以稳定去重。
6. 图查询结果顺序确定、可重复。
7. Graph contract 不绑定具体 storage backend。
8. 有完整 model / contract unit tests。

## Deliverables

- `src/arkui_agent/graph/model.py`：不可变 node/edge、稳定 identity、P1 source anchor、relation evidence。
- `src/arkui_agent/graph/query.py`：storage-independent 查询 Protocol、bounded traversal 输入/结果契约。
- `src/arkui_agent/graph/memory.py`：仅消费显式 graph records 的只读参考实现，用于验证 contract。
- `tests/unit/graph/`：model / query contract unit tests。
- `docs/architecture/graph-contract.md`：identity scope、dedup、provenance、排序与 traversal 语义。

## Tests / Validation

- Graph unit tests：`$env:PYTHONPATH = 'src'; py -3 -W error::ResourceWarning -m unittest discover -s tests/unit/graph -t . -v`。
- Repository validation：`py -3 -W error::ResourceWarning scripts/run_tests.py`。
- Diff validation：`git diff --check` 与 `git diff --cached --check`。
- 保持既有 Stop Hook，由其自动执行 repository validation。

验证结果（2026-09-04）：graph unit tests **26/26 passed**；repository validation
**175/175 passed**（包括真实 clangd synthetic integration 与 8/8 synthetic baseline cases）；
两个 diff checks 均通过。未配置 `ARKUI_REPO_ROOT`，runner 按既有规则未选择 5 个可选
真实 ArkUI tests；它们不属于 P2-A 必需验收。P2-A Acceptance Criteria 1–8 已满足。

## Known Limitations

- identity 在单个 repository / P1 identity scope 内稳定；不提供跨 repository 全局身份。
- P1 尚未提供的精确 call-site 不伪造；允许 symbol/file 级 anchor，并说明 evidence 精度。
- 只读内存 snapshot 不承担 repository facts projection、持久化与 rebuild；这些属于 P2-B。
- bounded traversal 仅为通用 BFS primitive，node/edge budget 不代表后端工作量或时延上限。

---

# P2-B — Symbol Graph & Test Graph Projection

- **Status:** Completed

## Goal

把 P1 Repository Intelligence 已经获得的 repository facts 投影为基础 Code Graph。

## Scope

消费 P1：

- symbol index
- declaration / definition
- references
- caller / callee
- inheritance / override（backend 能提供时）
- test fixture / test case
- symbol ↔ test mapping

构建基础关系：

- DECLARE
- DEFINE
- CALL
- REFERENCE
- INHERIT
- OVERRIDE
- TEST

建立：

```text
P1 Repository Facts
        ↓
Graph Builder
        ↓
Symbol Graph
        +
Test Graph
```

同时建立最小：

- graph build
- graph rebuild
- graph query
- generated graph data lifecycle

## Non-goals

- ArkUI Component recognition
- Model / Pattern role recognition
- CREATE / UPDATE_PROPERTY 等 framework relation
- Task-driven graph expansion

## Dependencies

- P2-A completed
- P1 completed

## Acceptance Criteria

1. synthetic repository 可以生成 Symbol Graph。
2. declaration / definition relation 正确。
3. direct caller / callee 可以转换为 CALL edge。
4. reference 可以转换为 REFERENCE edge。
5. TestFixture / TestCase 可以进入 graph。
6. symbol ↔ test mapping 可以形成 TEST relation。
7. graph 可以删除后重新构建。
8. graph generated data 不进入 Git。
9. graph edge 不通过同名字符串猜测 symbol identity。
10. graph facts 可以追溯到 P1 provenance。
11. 有 unit tests 和 synthetic integration tests。

## Deliverables

- `graph/projection.py`：P1 index → P2-A records，规范化 `GraphSnapshot`，不重新解析源代码。
- `graph/storage.py`：隔离 repository/snapshot 的 JSON adapter，原子保存、加载、删除和全量 rebuild。
- P1 仅新增 `SymbolIndex.test_fixtures()` 只读枚举及对应 storage query，无 schema/model 改动。
- `tests/unit/graph/test_projection.py`、`test_storage.py` 与 `tests/integration/test_graph_projection.py`。
- `docs/architecture/graph-contract.md` 补充 projection 语义、调用示例与生成数据生命周期。

## Tests / Validation

- `$env:PYTHONPATH = 'src'; py -3 -W error::ResourceWarning -m unittest discover -s tests/unit/graph -t . -v`
- `$env:PYTHONPATH = 'src'; py -3 -W error::ResourceWarning -m unittest tests.integration.test_graph_projection -v`
- `py -3 -W error::ResourceWarning scripts/run_tests.py`
- `git diff --check`、`git diff --cached --check`；保留既有 Stop Hook。

验证结果（2026-09-04）：graph unit tests **46/46 passed**（本次新增 20 个）；
synthetic graph integration **1/1 passed**；repository validation **196/196 passed**，
synthetic retrieval baseline **8/8 passed**；两个 diff checks 均通过。
当前未配置 `ARKUI_REPO_ROOT`，runner 按既有规则未选择 5 个可选真实 ArkUI tests；
P2-B 必需的真实 clangd synthetic integration 已执行。Acceptance Criteria 1–11 已满足。

## Acceptance Coverage

| Criteria | 验证依据 |
| --- | --- |
| 1–4 | 真实 clangd synthetic fixture → P1 index → graph，逐项校验 DECLARE / DEFINE / CALL / REFERENCE 与 range |
| 5–6 | 复用 P1 discovery/index 和 tested-symbol mappings，校验 fixture/case node、membership 和 direct TEST evidence |
| 7 | 删除后重新生成 byte-identical snapshot；空 P1 rebuild 清除 stale graph records |
| 8 | ignore test 验证 `var/` 与 `code-graph.json`；不提交生成数据 |
| 9–10 | 同名 identity 分离、unresolved endpoint、多个 occurrence、call provenance 精度和 evidence merge tests |
| 11 | projection/storage unit tests 与真实 clangd synthetic integration test |

## Known Limitations

- P1 当前不提供 INHERIT/OVERRIDE，显式列为 unavailable，不伪造关系。
- REFERENCE 只证明 file → target；CALL 保留 caller definition/declaration 精度，不声称精确 call-site。
- TEST 是 fixture membership 或 case 内 direct reference，不推断传递映射或覆盖率。
- 显式 scope keys 由调用方与 P1 snapshot 绑定；projection 要求 index 无并发 rebuild。
- JSON 全量加载/替换，不实现增量 graph、并发 writer 锁、自动 freshness 检测或 P2-C framework recognition。

---

# P2-C — ArkUI Component & Framework Role Mapping

- **Status:** Completed

## Goal

在通用 Symbol Graph 上识别 ArkUI framework entity，使普通 C++ symbol 开始具备 ArkUI domain identity。

## Scope

建立 deterministic ArkUI role mapping，至少识别：

- Component
- Bridge
- Model
- Pattern
- LayoutProperty
- PaintProperty
- LayoutAlgorithm
- OverlayManager

并为后续扩展预留：

- ArkTS API
- FrameNode
- Animation-related node

Role mapping 可以综合使用：

- qualified symbol identity
- class inheritance
- repository-relative source path
- class / method structural facts
- P1 text search 提供的非 symbol evidence

所有 mapping 必须记录 evidence / provenance。

示意：

```text
ButtonPattern
    ↓
Role = Pattern
Component = Button

ButtonModelNG
    ↓
Role = Model
Component = Button
```

## Non-goals

- 根据用户任务识别 Component
- LLM-based classification
- Context ranking
- Domain trace traversal
- 修改 P1 symbol identity

## Dependencies

- P2-B completed

## Acceptance Criteria

1. synthetic ArkUI-like fixture 可以识别主要 framework role。
2. 同一个 Component 的 Model / Pattern / Property 等可以关联。
3. role mapping 与 P1 Symbol 分离，不污染通用 symbol model。
4. 每个 domain mapping 有 provenance。
5. 无法确定的 symbol 不静默强制分类。
6. classification 结果稳定、确定。
7. Button / Text / Menu 至少完成真实 repository smoke validation。
8. 有错误分类与 unknown role tests。

## Deliverables

- `graph/domain.py`：独立 domain metadata、Component node、role candidate/decision、deterministic mapper 和 JSON-compatible evidence export。
- `graph/arkui_rules.py`：基于真实 source 核对的 Button/Text/Menu + shared OverlayManager 精确规则表。
- `tests/unit/graph/test_domain.py`：联合证据、unknown/ambiguous、前置声明、scope 一致性、顺序和不变性测试。
- `tests/fixtures/arkui_role_cases.py`：独立于 mapper output 的 17 个正例和 3 个负例 smoke expectations。
- `tests/integration/test_arkui_role_mapping.py`：synthetic 与真实 repository 的 P1 → P2-B → domain 链路。
- `docs/architecture/graph-contract.md`：规则、source 优先级、association、evidence 与局限。

## Tests / Validation

- 配置用户显式提供的 `ARKUI_REPO_ROOT`，target repository 只读。
- `$env:PYTHONPATH = 'src'; py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_domain tests.integration.test_arkui_role_mapping -v`
- `py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui`
- `git diff --check`、`git diff --cached --check`，保留既有 Stop Hook。
- 真实 smoke report：`var/validation/p2-c-role-smoke.json`（ignored runtime data）。

验证结果（2026-09-04）：本次 unit + synthetic + real smoke **11/11 passed**；
完整 `--require-arkui` repository validation **212/212 passed，0 skip**（121.283s），
包括既有真实 ArkUI tests；synthetic retrieval baseline **8/8 passed**，diff checks 通过。
真实 revision：`0096f5bd943ed1f7fa56883aed0e2379f13c2885`；Button **5/5**、Text **5/5**、
Menu **6/6**、shared OverlayManager **1/1**，3 个近名/派生负例均为 unknown。
19 个选定 source 文件 hash 验证不变，target Git worktree 保持干净。Acceptance Criteria 1–8 已满足。

## Acceptance Coverage

| Criteria | 验证依据 |
| --- | --- |
| 1–2 | synthetic class facts 覆盖 7 种 framework role；生成 Button/Text/Menu Component 并验证成员 |
| 3–4 | 独立 DomainMap，P1 identity 和 generic graph 不变；全部 candidate/component 带 rule ID 和 P1 anchor |
| 5–6 | unknown/ambiguous 无 resolved candidate、不加入 membership；重复运行和规则重排保持一致 |
| 7 | 必须显式执行真实 Button/Text/Menu smoke；未通过时维持 In Progress |
| 8 | 错 namespace/file/kind、近名 class、冲突规则、权威 definition 错位、未解析 symbol 等负例 |

## Known Limitations

- 首版是精确 reviewed catalog，仅登记 Button/Text/Menu 的 16 个角色类和共享 OverlayManager；未登记类保持 unknown。
- 不把 ToggleButton、MenuItem、InnerMenuPattern 自动归属 Button/Menu，也不自动传播至成员函数/派生类。
- P1 没有 inheritance fact API；继承结构仅用于人工规则核对，不新增 parser/继承边或 P2-D framework relation。
- definition 优先于跨文件 forward declaration；缺 definition 时才回退 declaration，保留原始证据精度。
- DomainMap 是带 scope 和规则 fingerprint 的 metadata；不自动把 annotations 写入 P2-B generic JSON，也不提供增量/freshness 更新。
- 实际 smoke 用真实 include 路径补齐 ace_kit 头文件，不构造 stub；它验证源码身份/映射，不能替代完整 OpenHarmony build。

---

# P2-D — ArkUI Framework Relation Extraction

- **Status:** Completed

## Goal

在基础 CALL / REFERENCE / INHERIT 图关系之上，提取具有 ArkUI framework 语义的 relation。

## Scope

至少支持 framework relation：

- CREATE
- UPDATE_PROPERTY
- MEASURE
- LAYOUT
- SHOW
- CLOSE

并完善：

- TEST
- MOCK

Relation extractor 应组合：

- P1 semantic facts
- Symbol Graph
- ArkUI role mapping
- source structural evidence
- repository text evidence（仅用于非 symbol pattern）

形成：

```text
Generic C++ Relation
        +
ArkUI Role
        +
Framework Evidence
        ↓
ArkUI Framework Relation
```

例如普通：

```text
CALL
```

经过 ArkUI domain interpretation 后可以进一步表达为：

```text
Model → Pattern : CREATE

Model::SetXXX → LayoutProperty : UPDATE_PROPERTY

LayoutAlgorithm → Measure : MEASURE
```

## Non-goals

- 完整 Creation Trace
- 完整 Property Trace
- 完整 Layout Trace
- 完整 Overlay Trace
- Task-specific graph
- Relation ranking

## Dependencies

- P2-C completed

## Acceptance Criteria

1. framework relation 使用独立 typed edge。
2. framework edge 保留底层 semantic evidence。
3. relation 不仅依据 class/function 同名判断。
4. unsupported / ambiguous relation 不静默伪造。
5. relation extractor 可单独测试。
6. graph rebuild 后 relation 稳定。
7. relation 有明确 provenance。
8. Button / Text / Menu 有 framework relation smoke validation。

## P2-D Implementation Notes

- 新增 `graph/framework.py`，公开 `extract_framework_relations` / `FrameworkExtraction` /
  `FrameworkDiagnostic`。输入 P1 index、matching generic GraphSnapshot、DomainMap 和只读
  workspace；复用现有 GraphEdge/EdgeIdentity、去重、排序和 GraphStore，不修改 P1。
- CREATE：recognized Pattern 的简单工厂方法 → 同 component 的 property/algorithm class；
  必须同时有 P1 parent、DEFINE、目标类型精确 REFERENCE、指向真实 Referenced::MakeRefPtr
  的 CALL，以及已核验的简单工厂和 `new T` 源码模板。
- UPDATE_PROPERTY：recognized Model 方法 → 同 component 的 LayoutProperty/PaintProperty；
  要求 P1 parent、DEFINE、唯一类型 REFERENCE、完整单条更新宏函数体及两层宏定义证据。
  不重建 macro-generated method identity，不把当前 backend 的粗粒度 CALL 当精确调用点。
- MEASURE/LAYOUT 为 LayoutAlgorithm → 已声明 operation；SHOW/CLOSE 为共享 OverlayManager
  → ShowMenu/HideMenu。依赖 P1 semantic parent、DECLARE 和完整框架参数/override 契约。
  这是 operation binding，不声称实际发生调用，也不生成完整 trace。
- TEST 保留 P1 tested-symbol mapping 的既有 identity 和 references，增加 target role evidence；
  fixture membership 不变。MOCK 缺可靠 P1 mapping，显式返回 unsupported，不伪造边。
- unknown/ambiguous role、多个 reference identities、跨 component、缺事实、复杂函数体、
  不支持/重复定义的宏都不出边，并返回 deterministic diagnostic；同一行的 overload 也必须
  精确匹配 P1 selection。scope/index mismatch 或 build 期间已读源码变化直接失败。
- provenance 含原始 semantic evidence、supporting generic EdgeIdentity、P1 parent、role rule
  fingerprint、framework version、source range/hash。重建从 generic projection 开始全量替换；
  不把旧 domain edges 追加到新 graph。报告/graph JSON 均为 ignored runtime data。

## P2-D Acceptance Evidence

| AC | 验收证据 |
| --- | --- |
| 1 | 六种独立 RelationType；不改变 generic edge 的类型，TEST 同 identity 合并 evidence |
| 2 / 7 | 每条 framework edge 保留 P1、generic、parent、role、rule 和源码 evidence；smoke 检查并导出完整 provenance |
| 3 | 语义 identity/parent + 精确 source template + role/component 联合约束；名称、宏文本或 CALL 单独均不够 |
| 4 | unknown/ambiguous、缺 reference/CALL、no-op factory/macro、复杂 body、重载及跨 component 的 unit 负例；MOCK 明确 unsupported |
| 5 | 独立 unit tests；synthetic C++ 通过真实 clangd/provider/index/projection/mapper/extractor 链路 |
| 6 | 逆序 P1 rebuild 得到相同结果，canonical JSON bytes 一致；GraphStore save/load/delete 验证 |
| 8 | 实际 ArkUI revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885`：Button 3、Text 3、Menu 4、共享 OverlayManager 2，共 12 条边 |

真实覆盖：三组件各有 CreateLayoutProperty → LayoutProperty、SetFontWeight → LayoutProperty
以及 measure operation；Text 使用 MeasureContent。Menu 另有 Layout；OverlayManager 有
ShowMenu/HideMenu。Button/Text 的继承 Layout 未推断。报告保留 3 个 unsupported body、
4 个缺 semantic parent 的 backend endpoint 诊断及 MOCK unavailable；不将它们强制分类。
source 文件 hashes 在 smoke 前后保持一致，target repository 只读。

实际命令（真实测试通过进程环境配置用户提供的 `ARKUI_REPO_ROOT`）：

```powershell
$env:PYTHONPATH = 'src'
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_framework -v
py -3 -W error::ResourceWarning -m unittest tests.integration.test_framework_relations -v
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
git diff --check
git diff --cached --check
```

Unit：14/14；synthetic + real integration：2/2。最终全量 validation：228/228（199.049s），
baseline 8/8；无 skips、expected failures 或 ResourceWarning。必需验收项全部通过。
real report：`var/validation/p2-d-framework-smoke.json`；全量日志：
`var/validation/p2-d-final-validation.log`；独立 review diff：`var/review/p2-d.patch`。
Stop Hook 及固定 repository validation 未修改、未绕过。

---

# P2-E — Component Creation Trace

- **Status:** Completed

## Goal

实现第一条完整 ArkUI domain trace：

```text
ArkTS / Entry
      ↓
Bridge
      ↓
Model
      ↓
FrameNode
      ↓
Pattern
```

## Scope

支持从 Component creation 入口查询：

- Bridge
- Model creation method
- FrameNode creation
- Pattern creation
- direct supporting call chain

提供 creation trace query API。

Trace 返回至少包括：

- ordered nodes
- ordered relations
- source location
- evidence
- incomplete / ambiguous state

## Non-goals

- Property Trace
- Layout Trace
- Overlay Trace
- 用户自然语言 Task 解析
- 自动上下文构建

## Dependencies

- P2-D completed

## Acceptance Criteria

1. synthetic fixture 可以生成完整 creation trace。
2. trace 顺序稳定。
3. trace 每一步都能追溯 source location。
4. graph 缺失 relation 时返回 incomplete，而不是虚构链路。
5. 多候选路径不会被静默随机选择。
6. Button / Text / Menu 至少有真实 creation trace validation。
7. trace query 不依赖 LLM。

## P2-E Implementation / Acceptance Evidence

- `graph/creation.py` 提供 typed trace contract 和 creation-specific query；复用 P1 identity、
  GraphNode/GraphEdge、P2-C role evidence 和 P2-D 只读源码 evidence accessor。
- seed 为显式 identity，component 为显式已知 component identity。按真实 CALL 枚举有序
  supporting paths，在 FrameNode factory 停止并检查 caller 构造的 Pattern 参数关联。
  FrameNode 只增加 trace-local stage，不改 P1 model 或通用 role catalog。
- `relations` 是连续 CALL 主链；`PatternArgument` 单独保存 Model/caller → FrameNode factory
  的参数关系及底层 CALL/REFERENCE/source evidence，不伪造 FrameNode → Pattern CALL。
- 多路线、role/reference/allocation identity 歧义显式保留；缺边/unknown/unsupported callback
  返回 incomplete。partial graph 不从 index 回填；bounded enumeration 截断不声称唯一完整。
- `creation_cases.py` 在运行 query 前冻结真实源码预期：具体 entry/model 行、调用表达式、
  qualified name、目标 Pattern 和 expected status。与程序 actual output 分离。

| AC | 验收证据 |
| --- | --- |
| 1 | synthetic Button/Text/Menu 由真实 clangd → index → generic graph → role map → framework graph → query 产生完整 trace |
| 2 | canonical CALL 顺序，per-path visited；逆序 P1 rebuild 返回相同结果 |
| 3 | 每个 node 有原始 source anchors 和 role/parent evidence；CALL 精度如实保留；参数关联有精确 REFERENCE 和源码 hash |
| 4 | 移除 graph CALL/REFERENCE/node 的 unit 负例返回 incomplete；不从 index 补回缺边 |
| 5 | diamond 保留两条 complete candidate paths 并标 ambiguous；role/reference 歧义保留候选，cycle/limits 不静默选路 |
| 6 | 真实 Button/Text complete，Menu 为源码审查预先确定的 incomplete；记录实际链路与缺口，并非跳过测试 |
| 7 | query 不依赖 LLM；不包含 ranking、Task-driven Expansion、Context Pack 或其他 trace |

真实 revision：`0096f5bd943ed1f7fa56883aed0e2379f13c2885`。

| Component | 实际主链 / 证据位置 | 预期结果 |
| --- | --- | --- |
| Button | `CreateButtonFrameNodeForCustom`（button_dynamic_modifier.cpp:970/972）→ `ButtonModelNG::CreateFrameNode`（button_model_ng.cpp:659/661）→ FrameNode::CreateFrameNode；直接 MakeRefPtr<ButtonPattern> 参数 | complete |
| Text | `ViewModel::createTextNode`（view_model.cpp:113/115）→ `TextModelNG::CreateFrameNode`（text_model_ng.cpp:90/92）→ FrameNode::CreateFrameNode；直接 MakeRefPtr<TextPattern> 参数 | complete |
| Menu | `CreateMenuFrameNode`（menu_dynamic_modifier.cpp:445/447）→ `MenuModelNG::CreateFrameNode`（menu_model_ng.cpp:25/30）→ GetOrCreateFrameNode；29 行回调创建 InnerMenuPattern | incomplete：callback binding 未支持，InnerMenuPattern 在 P2-C 为 unknown |

三条入口 → Model 边由 P1 callers/callees 支撑，Model → FrameNode 边来自 P1 callees；
Button/Text 的参数证明还包含 FrameNode method 与 Pattern 的精确 REFERENCE，以及已核验的
Referenced::MakeRefPtr CALL/new T 源码。Menu 不替换成 MenuPattern，不推断 callback CALL。

实际 validation 命令（显式配置用户提供的 `ARKUI_REPO_ROOT`，target 只读）：

```powershell
$env:PYTHONPATH = 'src'
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_creation tests.integration.test_creation_trace.SyntheticCreationTests -v
py -3 -W error::ResourceWarning -m unittest tests.integration.test_creation_trace -v
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
git diff --check
git diff --cached --check
git apply --reverse --check var/review/p2-e.patch
```

最新 targeted unit + synthetic：16/16；真实 + synthetic integration：2/2（95.099s）。
最终 repository validation：245/245（296.509s），baseline 8/8；无 skips、expected failures 或 ResourceWarning。
报告：`var/validation/p2-e-creation-smoke.json`；全量日志：
`var/validation/p2-e-final-validation.log`；独立 diff：`var/review/p2-e.patch`。
未修改/绕过 Stop Hook，未修改 P2-F 及后续 milestone 状态。

---

# P2-F — Property Update Trace

- **Status:** Completed

## Goal

支持 ArkUI property 从 API / Bridge 到最终 property state 的更新链分析。

目标结构：

```text
ArkTS Property
      ↓
Bridge
      ↓
Model::SetXXX
      ↓
LayoutProperty / PaintProperty
      ↓
Pattern / Render-related Consumer
```

## Scope

识别并查询：

- property entry
- Bridge setter
- Model setter
- LayoutProperty update
- PaintProperty update
- downstream consumer

重点利用 UPDATE_PROPERTY relation。

需要正确处理：

- LayoutProperty
- PaintProperty
- 同名 setter
- namespace / class member
- overloaded method

## Non-goals

- 自动判断用户想查哪个 property
- Context Ranking
- Render correctness analysis
- 修改 property 实现

## Dependencies

- P2-D completed

## Acceptance Criteria

1. synthetic property fixture 可以获得完整 update trace。
2. LayoutProperty 与 PaintProperty 可以区分。
3. setter identity 不通过纯字符串同名推断。
4. trace 支持 source provenance。
5. ambiguity 显式返回。
6. 至少为 Button / Text / Menu 选择真实 property 做 validation。
7. property trace 可重复运行并得到稳定结果。


## P2-F Implementation / Source-reviewed Expectations

新增 `graph/property.py`，在 graph/domain 层提供 `trace_property_update` 和 immutable typed
contract；复用 P1 opaque symbol identity、P2-A nodes/edges、P2-B projection、P2-C role map
及 P2-D UPDATE_PROPERTY。不修改 P1 parser/index/retrieval、framework extractor 或既有 identity。

Seed 与 setter 都必须显式指定完整 NodeIdentity。先沿真实 CALL 找到所选 setter，随后终止
CALL 扩展，核验 UPDATE_PROPERTY 的 source/宏、唯一 target REFERENCE、Model parent、
component 和 Layout/Paint role。property token 只是有来源的语法标签，不生成 P1 identity。
下游仅接受实际 CALL-resolved writer 的完整形参→FIELD 赋值、同 FIELD identity 的完整
reader 返回体及 consumer→reader CALL；不按 Get/Set 名字拼接，不推断 macro member/dataflow。

ordered nodes 保存 entry/bridge/support、model、property、writer/state/reader/consumer；
`calls` 连续，`support` 保留原方向，`binding` 保持 P2-D class binding 含义。候选 identity、
候选 evidence、gaps、每条 path status、整体 status/exhaustive 均显式。多个有效候选不排序
挑选一条；bounds/cycle 截断不返回唯一 complete。结果是静态成员读写关联，不证明同一
运行时实例/时序/渲染影响。没有进入 P2-G 或 P3。

### 冻结的真实 FontWeight 路径

在首次 query 前阅读并写入 `tests/fixtures/property_cases.py`；revision：
`0096f5bd943ed1f7fa56883aed0e2379f13c2885`。位置均为 repository-relative、1-based。

| Component | Native property entry → exact Model overload | 单参数 setter / property 定义 | 源码 downstream evidence |
|---|---|---|---|
| Button | `pattern/button/bridge/button_dynamic_modifier.cpp:317` SetButtonFontWeight，CALL :322 → `button_model_ng.cpp:885` SetFontWeight(FrameNode*, const Ace::FontWeight&) | `button_model_ng.cpp:39` → ButtonLayoutProperty；宏 :41；property 宏 `button_layout_property.h:97` | `button_pattern.cpp:437` UpdateTextLayoutProperty 读取 GetFontWeight().value() |
| Text | `frameworks/core/interfaces/native/node/node_text_modifier.cpp:627` SetFontWeightStr，CALL :631 → `text_model_ng.cpp:250` SetFontWeight(FrameNode*, Ace::FontWeight) | `text_model_ng.cpp:286` → TextLayoutProperty；宏 :288；property 宏 `text_layout_property.h:150` | `text_layout_property.h:298` InspectorGetTextFont 读取 GetFontWeight().value() |
| Menu | `pattern/menu/bridge/menu/menu_dynamic_modifier.cpp:177` SetMenuFontWithResource，CALL :191 → `menu_model_ng.cpp:505` SetFontWeight(FrameNode*, FontWeight) | `menu_model_ng.cpp:315` → MenuLayoutProperty；宏 :317；property 宏 `menu_layout_property.h:139` | `menu_pattern.cpp:206` UpdateMenuItemTextNode 读取 menuProperty->GetFontWeight().value() |

表中 `pattern/` 与 component 文件位于 `frameworks/core/components_ng/` 下对应目录；fixture
保存完整相对路径。不是 ArkTS property 到 native entry 的自动解析；这里 seed 是已选原生入口。

三组件各固定验证两个片段，共 6 个结果，均预期 **incomplete**：

- native：`entry → Model(FrameNode* overload)`，gap=`missing_update_binding`。
  源码下一步真实为 `ACE_UPDATE_NODE_LAYOUT_PROPERTY`，不属于 P2-D v1 的支持模板。
- stack-local：`Model(single-argument overload) → LayoutProperty`，gaps=
  `missing_entry_call`、`missing_property_writer`。UPDATE_PROPERTY 已核验；无 entry CALL，
  macro-generated FIELD/accessor 不满足本版显式成员规则，因此不虚构 writer/consumer。

两个 overload 的 P1 identity 必须不同，不能把 stack binding 借给 native setter。上表
consumer 是源码审查事实，**未作为已恢复 trace stage**。真实不完整结果与预先冻结的能力
缺口一致；验收通过不代表已恢复完整运行时 property pipeline。

### Acceptance Criteria 对照

| # | Criteria | 实现与证据 |
|---|---|---|
| 1 | synthetic 完整 update trace | 真实 clangd 原创 C++ fixture：3 条完整 entry→model→property→writer→state→reader→consumer 静态链 |
| 2 | LayoutProperty / PaintProperty | Button/Text 为 Layout，synthetic Menu 为 Paint；宏与 P2-C role 冲突返回 ambiguous |
| 3 | setter identity | 显式 opaque ID；真实 FrameNode*/单参数重载隔离；同名 overload/parent 负例 |
| 4 | source provenance | 原 GraphNode anchors、P1 CALL/REFERENCE、UPDATE_PROPERTY、parent/role、source range/hash、候选 evidence |
| 5 | ambiguity | 多 CALL 路径、多 consumer、冲突 FIELD/property identity、role ambiguity/conflict 保留候选；截断有 exhaustive=False |
| 6 | 真实三组件 property | FontWeight 六片段；query 前检查 21 个源码位置；与冻结 incomplete/gap 一致 |
| 7 | deterministic | canonical 候选顺序；逆序 P1 rebuild、GraphStore 往返与重复 query 结果相等 |

### Validation

开发期间只执行 P2-F unit/synthetic；基本定稿后执行真实 smoke，再补充 NODE macro、FIELD
ambiguity、错误赋值来源的负例。未在代码定稿前运行完整 repository suite。

```powershell
$env:PYTHONPATH='src'
# ARKUI_REPO_ROOT 使用用户已提供的外部仓库路径；不写入源码。
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_property tests.integration.test_property_trace.SyntheticPropertyTests -v
py -3 -W error::ResourceWarning -m unittest tests.integration.test_property_trace.RealPropertySmokeTests -v
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
git diff --check
git diff --cached --check
git apply --reverse --check var/review/p2-f.patch
```

最新 unit + synthetic：17/17（10.914s）；首次真实 smoke：1/1（97.672s）。
最终全量：263/263（406.175s），baseline 8/8；无 skips、expected failures 或 ResourceWarning。
代码/test freeze hashes：`var/validation/p2-f-code-freeze.json`；5 个文件校验一致，最终全量启动后无代码/测试修改。
报告：`var/validation/p2-f-property-smoke.json`；最终日志：
`var/validation/p2-f-final-validation.log`；独立可 review diff：`var/review/p2-f.patch`。
不修改/绕过 Stop Hook，所有派生数据只进入 ignored `var/`，不修改外部 ArkUI 仓库。

---

# P2-G — Measure / Layout Trace

- **Status:** Completed

## Goal

实现 ArkUI layout pipeline 的 domain trace。

目标结构：

```text
Pattern
   ↓
CreateLayoutAlgorithm
   ↓
LayoutAlgorithm
   ↓
Measure
   ↓
Layout
   ↓
LayoutProperty
```

## Scope

识别并查询：

- Pattern
- LayoutAlgorithm creation
- Measure
- Layout
- LayoutProperty dependency
- direct supporting calls

主要使用：

- CREATE
- MEASURE
- LAYOUT
- CALL
- REFERENCE

## Non-goals

- 实际执行 layout
- UI rendering
- 性能 profiling
- Task Context Builder

## Dependencies

- P2-D completed

## Acceptance Criteria

1. synthetic layout fixture 可产生 measure/layout trace。
2. CreateLayoutAlgorithm → LayoutAlgorithm relation正确。
3. Measure / Layout relation可以明确区分。
4. LayoutProperty dependency 可以进入 trace。
5. trace 每个节点和 relation 均有 provenance。
6. incomplete layout chain 可明确报告。
7. 至少选择具有 layout algorithm 的真实 ArkUI component 验证。

## P2-G Implementation / Frozen Expectations

实现 `graph/layout.py` 的 `trace_measure_layout` 与 immutable typed result，复用 P1
opaque identity、generic graph、role map 和 P2-D primitives。Pattern member、CREATE、
operation binding、implementation、property dependency 分别保存各自证据；不新增
Pattern → factory CALL 或 Measure → Layout CALL。规范详见 `graph-contract.md` P2-G。

源码审查 revision：`0096f5bd943ed1f7fa56883aed0e2379f13c2885`。预期已在第一次 query
前写入 `tests/fixtures/layout_cases.py`，包括 20 个独立 source checks。下面路径均以
`frameworks/core/components_ng/pattern/` 为前缀。

| Component | 冻结源码事实 | Expected trace / status |
|---|---|---|
| Button | `button_pattern.h:61/63` 简单创建 ButtonLayoutAlgorithm；`button_layout_algorithm.h:32` Measure；`.cpp:37/44` 实现与 ButtonLayoutProperty 类型引用；没有自身 Layout 声明 | Pattern → factory → algorithm → Measure → LayoutProperty；incomplete，`missing_layout_binding` |
| Text | `text_pattern.cpp:9080/9087/9089` 分支、有参创建 TextLayoutAlgorithm；`text_layout_algorithm.h:73` / `.cpp:164/171` 为 MeasureContent 与 TextLayoutProperty 引用；没有自身 Layout 声明 | Pattern → factory；incomplete，`unsupported_factory_body` |
| Menu | `menu_pattern.cpp:1447/1452/1455/1457` switch 返回 MultiMenu/SubMenu/MenuLayoutAlgorithm；`menu_layout_algorithm.h:108/110` 与 `.cpp:901/2105` 分别为 Measure/Layout；property 引用在 `.cpp:910/2120` | Pattern → factory；ambiguous，保留三个 algorithm identity，`ambiguous_algorithm_identity` + `missing_create_binding` |

Menu 的 switch 仅用于提供有精确 P1 REFERENCE 的候选；不取默认分支，不为复杂创建补
CREATE。MultiMenu/SubMenu 在现有 P2-C catalog 中为 unknown；未扩展 role catalog。
Text/Menu 的后续 implementation 是源码审查事实，未跨过缺失 CREATE 放入已恢复 trace。
Button 的 inherited Layout 留缺口，不能据此宣称完整运行时 pipeline。

Seed 为显式 Pattern identity 和 component identity。按 P1 METHOD parent 找 factory；
只有唯一、受支持且证据完整的 CREATE 才进入 algorithm。Measure/MeasureContent 与
Layout 分别找 parent 一致的 operation，核验 P2-D binding 和 DEFINE/source signature。
最终通过 definition 开头受支持 preamble 中目标 token 的唯一 P1 REFERENCE 关联
同 component LayoutProperty。直接 supporting CALL 只记录一跳，不递归追踪；循环也
仅保留原边一次。缺事实/unsupported 停止相关阶段；候选冲突返回 ambiguous；候选/
CALL 预算截断报告 gap 与 `exhaustive=False`，不能把截断后的一个候选当唯一完整。

### Acceptance Criteria 对照

| # | 实现 / 验证依据 |
|---|---|
| 1 | 原创 C++ fixture 通过真实 clangd → P1 → graph → domain → framework → trace 验证三个完整片段 |
| 2 | CREATE 必须是原 P2-D 边，且所有 supporting generic edges 仍在输入 graph；缺 CALL/REFERENCE/DEFINE 不从 index 补回 |
| 3 | MEASURE 与 LAYOUT 保持 algorithm → method 的不同 binding；两种 definition 独立核验；声明不能冒充实现 |
| 4 | 精确 token REFERENCE + operation source preamble + property role/component；synthetic 两操作各有依赖，真实 Button Measure 有依赖 |
| 5 | 原 GraphNode anchors、parent/role、binding/source hash、原方向 CALL/REFERENCE/DECLARE/DEFINE，以及 candidate evidence |
| 6 | 缺 stage/edge/definition/role、unsupported、identity/role conflict、预算截断均显式；逆序 rebuild/持久化往返结果稳定 |
| 7 | 只读真实 Button pipeline，以及 Text/Menu 的冻结失败边界；按源码预期验证，不用 actual 反填 expected |

### Validation

开发阶段仅运行 P2-G unit / synthetic；之后执行 real smoke，补齐相关负例，再冻结代码/
测试并执行一次最终 `scripts/run_tests.py --require-arkui`。

```powershell
$env:PYTHONPATH='src'
# ARKUI_REPO_ROOT 使用用户提供的外部路径，通过进程环境显式配置。
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_layout tests.integration.test_layout_trace.SyntheticLayoutTests -v
py -3 -W error::ResourceWarning -m unittest tests.integration.test_layout_trace.RealLayoutSmokeTests -v
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
git diff --check
git diff --cached --check
git apply --reverse --check var/review/p2-g.patch
```

最新 unit + synthetic：22/22（10.937s）；成功 real smoke：1/1（78.734s），20 个源码
位置检查，20 个文件 hashes 一致。首次 query 前冻结的三个 expected 均匹配。
完整代码/config freeze：`var/validation/p2-g-code-freeze.json`，共 95 个文件。
最终全量：286/286（535.325s），baseline 8/8，无 skips、expected failures 或 ResourceWarning。
95/95 freeze hashes 校验一致；最终 full validation 启动后无代码/测试/config 修改。
AC 1–7 全部满足；真实 incomplete/ambiguous 与冻结源码边界一致，不代表恢复了完整
运行时 layout pipeline。外部 target Git worktree 保持干净；Stop Hook 未修改/绕过，
P2-H 及其他 milestone 状态未改动。所有派生报告与 patch 仅写入 ignored `var/`。

报告：`var/validation/p2-g-layout-smoke.json`；最终日志：
`var/validation/p2-g-final-validation.log`；独立可 review diff：`var/review/p2-g.patch`。

首次 real smoke 与一次带 faulthandler 的诊断重跑因既有 P1 adapter 的 close-notification
管道阻塞而中止（栈为 `clangd.py:130 _write ← close:378`），不计作通过。P2-G 真实
采集切片限定 factory allocation CALL 与 operation DEFINE/REFERENCE/parent；synthetic
仍采集并验证 operation CALL。没有修改 P1 adapter、mock provider、跳过真实组件或
改变冻结 expected。真实 smoke 不声称已枚举 Measure/Layout 的完整 callee inventory。

---

# P2-H — Overlay Show / Close Trace

- **Status:** Completed

## Goal

支持 ArkUI Overlay 生命周期中 Show / Close 主链分析。

目标结构：

```text
Show
 ↓
OverlayManager
 ↓
Node
 ↓
Pattern
 ↓
Animation
 ↓
Close
```

## Scope

识别：

- Overlay entry
- OverlayManager
- overlay node creation / management
- Pattern
- show relation
- close relation
- animation-related direct path（存在明确 evidence 时）

重点 relation：

- SHOW
- CREATE
- CALL
- CLOSE

## Non-goals

- 通用 Lifecycle Trace
- 动画行为模拟
- Runtime UI execution
- Agent reasoning

## Dependencies

- P2-D completed

## Acceptance Criteria

1. synthetic overlay fixture 可以建立 Show / Close trace。
2. SHOW 与 CLOSE 是显式 domain relation。
3. OverlayManager 可以作为 framework entity 查询。
4. show / close source provenance 完整。
5. 不存在 animation evidence 时不虚构 animation node。
6. 至少选择真实 ArkUI overlay-related component 做 validation。
7. 多条 close path 可明确表达。

## P2-H Implementation / Frozen Expectations

实现 `graph/overlay.py` 的 `trace_overlay` 与 immutable Show/Close 独立结果，复用 P2-B
generic graph、P2-C OverlayManager identity、P2-D SHOW/CLOSE entry binding；不新增
operation relation、role catalog 或 P1 语义。contract 详见 `graph-contract.md` P2-H。
入口、manager、component 显式指定；这是静态 Menu API family 的配对，不证明同一 runtime
node、manager instance 或 Show/Close 执行先后。不存在源码创建证据时不补 CREATE。

首次 query 前审查并冻结 revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885` 的以下事实。
位置以 `frameworks/core/components_ng/` 为前缀；18 个 source checks 见
`tests/fixtures/overlay_cases.py`，每次在语义采集和 query 前校验。

| 场景 | 冻结源码路径 | Expected / actual |
|---|---|---|
| Menu Show | `base/view_abstract.cpp:5403` BindMenuWithItems，经 `:5446` 调用 OverlayManager::ShowMenu；manager `.cpp:1623/1630` 为实现及 modifier->showMenu | entry → manager → operation → managed_node_type；incomplete，`unsupported_manager_body` |
| Menu Close / view | `base/view_abstract.cpp:5385` CloseMenu，经 `:5399` 调用 OverlayManager::HideMenu；manager `.cpp:1684/1693` 为实现及 modifier->hideMenu | 同上，单 path incomplete |
| Menu Close / pattern | `pattern/menu/menu_pattern.cpp:1070` HideMenu(bool,...)，经 `:1113` 调用同一 manager HideMenu | 同上，单 path incomplete；Close 集合保留两条路径，ambiguous |

manager header `pattern/overlay/overlay_manager.h:198/199` 保留 SHOW/CLOSE domain binding
及同一 P1 method 声明参数的 FrameNode 精确 REFERENCE；node stage 表示静态参数类型。
MenuPattern::HideMenu 在 header 另有 inline overload，显式以预审 `.cpp:1070` definition
定位目标，不能按 qualified name 排序选择。所有真实 path animation 均为 unresolved，
总结果 ambiguous，两个 leg 在给定 seeds / graph 上 exhaustive=True。

独立下游源码观察：`pattern/menu/menu_manager.cpp:1195` GetPattern<MenuWrapperPattern>，
`:1263` ShowMenuAnimation，`:1416` PopMenuAnimation，`:1095` AnimationUtils::Animate；
`:1137/1154` HideAllMenusWithoutAnimation 及 RemoveChildWithService。动画存在和无动画关闭
分支均已记录，但不跨未解析 modifier dispatch 放入 trace。MenuWrapperPattern 为既有
catalog unknown，不用 MenuPattern 替代。另审查 DialogPattern::PopDialog → CloseDialog；
其 dispatch 与 operation 未被现有 P2-D 模板支持，本次不扩展 Dialog/Lifecycle 分析。

Traversal 对每个 leg 先反向可达过滤，再枚举显式 seed → manager semantic child method
的真实 CALL simple paths，到 ShowMenu/HideMenu 即停止入口 traversal。binding 独立核验，
有边/源码缺口仍返回已知片段。默认每个 leg 深度 8、paths 32、states 1000；cycle/预算
cut 明确 gaps 与 exhaustive=False。多路径或 identity/role 冲突为 ambiguous，未知或缺失
为 incomplete，不从完整 P1 index 补回 partial graph 缺边，也不将排序作为路径选择。

Pattern tail 限定完整 tiny body 的 GetPattern<T> / direct member CALL，并同时核验
REFERENCE、P2-C role、semantic parent。可选 Animate 还需精确 P1 METHOD identity、
权威声明位置及真实 CALL。没有直接动画的完整 tiny body 不造动画 stage；unsupported
body 则 unresolved，不宣称运行时无动画。original generic/domain evidence、source hashes、
候选、缺口和 ordered stages 均保留，P1 caller location 不冒充 call-site。

### Acceptance Criteria 对照

| # | 实现 / 验证依据 |
|---|---|
| 1 | 原创可执行 C++ 经真实 clangd → P1 → generic graph → role → framework → trace；有/无直接动画均恢复完整静态片段 |
| 2 | SHOW/CLOSE 显式保存于每个 path.binding；入口 CALL 与 domain binding 分开，缺任一证据有独立负例 |
| 3 | 复用 P2-C shared OverlayManager entity 和 P1 opaque identity；unknown/role conflict 保留 candidate evidence |
| 4 | Show/Close 各自 nodes/calls/binding/support/source_evidence；验证 anchors、parent、原边 provenance、source hash、GraphStore 往返及逆序 rebuild |
| 5 | 无动画 fixture 不生成 animation stage；假名字、错误 identity、缺 REFERENCE/CALL、分支或附近源码均不能补造 |
| 6 | 真实 Menu Show 与两类 Close entry 使用冻结 source checks；modifier dispatch 边界与源码一致 |
| 7 | 同一 synthetic Close seed 的两条实际 CALL paths，以及真实两个 Close seeds，均保留并 ambiguous；depth/state/path/cycle 截断明确报告 |

### Validation

PowerShell：设置 `PYTHONPATH=src`，真实验证通过显式 `ARKUI_REPO_ROOT` 指向只读 target。

```powershell
py -3 -W error::ResourceWarning -m unittest tests.integration.test_overlay_trace.SyntheticOverlayTests -v
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_overlay tests.integration.test_overlay_trace.SyntheticOverlayTests -v
py -3 -W error::ResourceWarning -m unittest tests.unit.graph.test_overlay.OverlayTests.test_same_named_entry_overloads_keep_explicit_identities -v
py -3 -W error::ResourceWarning -m unittest tests.integration.test_overlay_trace.RealOverlaySmokeTests -v
py -3 -W error::ResourceWarning scripts/run_tests.py --require-arkui
```

开发 targeted：初版 synthetic 2/2；unit + synthetic 21/21，补例后 26/26（7.826s）。
单重载负例曾因测试使用不存在的 Symbol.name 字段失败，修正为 qualified_name 后 1/1。
前两次真实 smoke 分别暴露 seed 重载不唯一、definition 参数 REFERENCE 缺失，不计通过；
修正为冻结 definition anchor，以及同一 opaque method 的声明/实现参数证据后，真实 smoke
1/1（46.571s）通过。诊断观察到 FrameNode references 返回 997 条、包含声明参数而缺目标
实现参数；未修改 P1 adapter，也未反填 expected。增加声明/实现冲突与缺引用负例后重跑
相关 P2-H 小测试。18 个冻结 checks 全部吻合，真实 source 文件 hashes 与 target Git 未变。

最终全量仅执行一次：313/313（566.412s），真实 retrieval baseline 8/8；无 skips、
expected failures 或 ResourceWarning。启动后未修改代码/测试/config，104/104 会话内存
freeze hashes 复核一致；外部 target Git worktree 干净且 revision 未变。AC 1–7 与所有
必需验证通过，P2-H 标记 Completed。最终验证后仅更新本节状态和结果，不需要重跑 full。
仅保留测试消费的 ignored `var/validation/p2-h-overlay-smoke.json`；review 使用 Git diff，
不生成独立 patch、freeze 文件或逐命令日志。P2-I 保持 Not Started，不实现通用 Lifecycle/P3。

---

# P2-I — Real ArkUI Graph Validation & P2 Baseline

- **Status:** Not Started

## Goal

在真实 OpenHarmony ArkUI Ace Engine repository 上完成 P2 验收，并为 P3 Graph Expansion 与后续 Evaluation 建立稳定 baseline。

## Dependencies

- P2-E completed
- P2-F completed
- P2-G completed
- P2-H completed

## Representative Components

优先复用 P1 baseline 中已经人工验证过的组件：

- Button
- Text
- Menu

根据 trace 类型再增加适合的：

- Dialog
- Tabs
- List

P2 不要求所有组件覆盖所有 trace，而应选择真正具有对应 architecture path 的组件。

## Required Validation

至少覆盖：

### Graph

- Symbol Graph
- Component Graph
- Test Graph
- Framework Relation

### Domain Trace

- Component Creation
- Property Update
- Measure / Layout
- Overlay Show / Close

## Evaluation

至少记录：

- expected nodes
- expected relations
- missing node
- missing edge
- incorrect edge
- ambiguous path
- trace completeness
- Call Chain Accuracy
- query latency
- failure category

所有 expected trace 必须人工检查源码后冻结。

不得根据 graph actual output 反向填写 expected result。

## Acceptance Criteria

1. 使用外部只读 ArkUI repository。
2. Graph derived data 不进入 Git。
3. 至少 3 个代表性组件进入 P2 validation suite。
4. 四类 domain trace 均存在真实 repository case。
5. expected trace 经过人工源码确认。
6. Graph relation 可以追溯到底层 source evidence。
7. 记录失败案例，而不是只保存成功案例。
8. baseline command 可以重复执行。
9. Call Chain Accuracy 可以被统计。
10. P2 Definition of Done 全部满足。

---

# P2 Definition of Done

只有 P2-A 至 P2-I 全部 Completed，P2 才标记 Completed。

P2 完成后系统应具备：

```text
P1 Repository Intelligence
        ↓
Generic C++ Facts
        ↓
Symbol / Test Graph
        ↓
ArkUI Role Mapping
        ↓
Framework Relation
        ↓
ArkUI Code Graph
        ├─ Component Creation Trace
        ├─ Property Update Trace
        ├─ Measure / Layout Trace
        └─ Overlay Show / Close Trace
```

并能够针对已知 Component / Symbol 查询 ArkUI framework-aware graph relation。

P2 完成时仍然不应该存在：

```text
Natural Language Task
        ↓
Task Parser
        ↓
Multi-channel Retrieval
        ↓
Task-specific Graph Expansion
        ↓
Context Ranking
        ↓
Context Pack
```

以上能力属于 P3 — Task Retrieval & Context Builder。

## Deferred Capability

技术路线中还定义了：

```text
Create
→ Attach
→ Modify
→ Layout
→ Detach
```

Lifecycle Trace。

但当前 Phase 2 正式目标明确重点要求：

- Component Creation
- Property Update
- Measure / Layout
- Overlay Show / Close

因此 Lifecycle Trace 暂不作为 P2 Definition of Done 的硬性条件。

如果 P2-H 完成后发现所需 graph relation 已基本具备，可追加：

```text
P2-J — Lifecycle Trace
```

否则延后处理，避免扩大 P2 scope。
