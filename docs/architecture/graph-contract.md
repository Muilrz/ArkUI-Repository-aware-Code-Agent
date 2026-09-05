# P2-A Graph Model & Query Contract

实现位置：`src/arkui_agent/graph/`。本契约消费 P1 类型，独立于 semantic
provider、SymbolIndex、retrieval 和任何 storage backend。

## Identity 与 P1 追溯

- 一个 graph snapshot 对应一个 repository 和一套 P1 identity。
  identity 不是跨 repository 的全局 ID；后续持久化层必须隔离 repository/snapshot。
- `NodeIdentity(namespace, key)` 与 `display_name`、`NodeKind`、source range 分离。
  `symbol` namespace 的 key 原样复用 `SymbolIdentity.value`，包含 overload 的区别；
  `file` namespace 原样复用 `RepositoryFile.path`。不得从同名结果猜 identity。
- Domain entity 使用调用方显式提供的 namespace/stable key。P2-A 只定义类型词汇，
  不生成 Component identity、不识别 role。同一 symbol 改变 kind 不改变 identity。
- `value` 是带 `v1` 前缀的紧凑 JSON 数组，采用 ASCII escaping；不用 Python hash、
  自增序号、display name 或不带转义的分隔符拼接。排序直接使用结构化 identity。
- `GraphNode.anchors` 引用原有 `SymbolIdentity` / `RepositoryFile` / `SourceRange`，
  可保留 declaration 和 definition 等多个位置。range 自动关联其 file，冲突报错。
  symbol/file namespace 的 node 必须有相符的 anchor。
- 每个 node 至少有一个 P1 anchor。仅 symbol 或 file 已知时允许 range 缺失；
  不伪造位置。坐标直接沿用 P1 的 1-based、half-open range。

## Relation identity、dedup 与 provenance

- `EdgeIdentity(source, target, relation)` 表示有向语义关系。
  反向 edge、不同 relation type 是不同 identity；self-loop 合法。
- 同一端点间多次 CALL/REFERENCE 属于一条 relation，各 occurrence 放在 evidence 中。
  display name、source range、producer 和 evidence description 不参与 relation identity。
- 每条 edge 必须有非空 `RelationEvidence`：`provenance` 标识 producer/fact/rule，
  `anchor` 指向 P1 事实，`description` 说明证据含义和精度。
  例如 P1 `DirectCallRelation.source_range` 是 caller definition/declaration，
  并非精确 call-site；consumer 必须保留该区别。
- 相同 identity 的 edge 合并 evidence 的集合，保持所有不同 producer/occurrence。
  合并具有交换性、结合性和幂等性；不同 identity 合并时报错。
- anchors 按其 canonical JSON key 排序去重；evidence 按
  `(provenance, anchor.sort_key, description)` 排序去重。所有记录使用 frozen dataclass
  和 tuple，不受输入集合顺序影响。

## Query semantics

`GraphQuery` 是 read-only structural Protocol。后端只需实现协议，无须继承内存实现。

- `node` 精确查 identity；缺失返回 `None`。未知节点的其他查询返回空结果。
- `incoming_edges` / `outgoing_edges` 返回唯一 edge，按
  `(source.namespace, source.key, target.namespace, target.key, relation.value)` 排序。
- `relations=None` 表示所有类型，空 frozenset 表示不匹配任何类型。
- `neighbors` 支持 incoming/outgoing/both，按 `(namespace, key)` 排序并去重。
  自环返回节点本身；BOTH 不翻转 edge，也不重复返回同一 edge。
- `traverse` 是通用 FIFO BFS：seed 深度为 0；逐节点按 edge 顺序检查相邻关系；
  每个 node 只访问一次，visits 保持发现顺序并携带最短 hop depth。
  返回的 edges 是已检查并接纳的唯一关系，按全局 edge 顺序排序，包括环和 cross-edge。
- `max_depth` 必填且非负；到达该层后不展开，因此结果不是 induced subgraph，
  也不是 domain trace。filter 和 direction 在每一跳生效。
- `max_nodes` 默认 100（包含 seed），`max_edges` 默认 1000；两者限制结果规模，
  不承诺后端加载成本/运行时间上限。检查新 edge 时先检查 edge budget，再检查新
  endpoint 的 node budget。超限前停止，同时不接纳该 edge 和新 node。
- `stopped_by` 显式报告 `NODE_LIMIT` / `EDGE_LIMIT`。仅当预算阻止了下一项时设置，
  恰好达到上限但没有更多内容不算截断；达到指定 depth 是正常完成。
- 输入参数错误抛 `TypeError` / `ValueError`；后端操作失败抛 `GraphQueryError`，
  不能冒充没有匹配结果。每次查询必须基于一致 snapshot。

## Reference implementation 与边界

`MemoryGraph` 仅接收调用方已经构造好的 node/edge，形成无写接口的轻量 snapshot，
用于运行真实查询及可复用的 contract tests。精确重复 node 被去重；相同 identity
但内容冲突的 node 报错，避免任意 last-write-wins。重复 edge 合并 evidence。
悬空 edge 明确报错；未解析的 symbol 可由 symbol-only anchor node 显式表示。

P2-A 不包含 P1 facts projection、graph build/rebuild/lifecycle、数据库 schema、
ArkUI role recognition、framework extraction 或 task-aware expansion。
投影和持久化生命周期留给 P2-B；Task Subgraph 与 Context Pack 留给 P3。

## P2-B：P1 index projection

`project_index(index, repository_key=..., snapshot_key=...)` 只消费已构建的 P1 index。
通过 `files()` / `symbols_in_file()` 枚举 symbol，使用 `ReferenceCallRetriever`
获取 reference/call；新增的通用只读 `test_fixtures()` 枚举全部 fixture，包括没有 case
的 fixture，随后复用 `test_cases_for_fixture()` / `tested_symbol_mappings_for_case()`。
不启动 semantic provider、不读 C++ 源码、不执行 test discovery。

| P1 fact | Graph projection | Evidence 精度 |
| --- | --- | --- |
| Symbol.declaration / definition | file → symbol，DECLARE / DEFINE | 原始 P1 source range |
| references(target identity) | reference file → target symbol，REFERENCE | 原始 reference occurrence；不推断 enclosing function |
| callers / callees | caller → callee，CALL | caller definition，回退到 declaration；未知 caller 保留 symbol-only anchor |
| TestFixture / TestCase | 同一 P1 identity 的 TEST_FIXTURE / TEST_CASE node | fixture/case token range，case 另保留已有 body range |
| TestCase.fixture_identity | fixture → case，TEST | case source range；表示 fixture membership |
| TestedSymbolMapping | case → symbol，TEST | P1 已保存的 body 内 direct references；不表示测试覆盖率 |

TEST 两种用途由端点 kind 和 provenance 明确区分。不推导 fixture → tested symbol
的传递边，不把 test discovery token 当作 C++ declaration/definition。相同 P1 identity
同时存在于 Symbol 和 test entity 时，test kind/name 优先并合并原有 anchors；不同
identity 的同名实体保持独立。无法解析的 CALL endpoint 是 symbol-only node，名称显示
opaque identity，不伪造 symbol 名称或位置。

`INHERIT` / `OVERRIDE` 当前没有 P1 API/facts 支持，列于
`GraphSnapshot.unavailable_relations`，不从 parent_identity、名称或文本推断。
没有新增 semantic resolution、ArkUI role recognition 或 framework relation。

## P2-B：Generated snapshot lifecycle

`GraphSnapshot` 是 P2-A records 的规范化快照封装，不替代 node/edge model；通过
`MemoryGraph` 校验冲突、复用 edge merge，再按既有顺序保存 records。
`snapshot.query()` 返回独立的 P2-A `MemoryGraph`。

```python
from arkui_agent.graph import GraphStore, NodeIdentity, TraversalBounds

# index 已由 P1 构建；scope keys 由调用方显式绑定到该 repository/P1 snapshot。
store = GraphStore("var", repository_key="ace-engine", snapshot_key="p1-snapshot-id")
snapshot = store.rebuild(index)  # 首次 build 与全量 rebuild 使用同一接口
query = store.load().query()
result = query.traverse(NodeIdentity.for_symbol(symbol_identity), bounds=TraversalBounds(2))
store.delete()  # 仅删除此 scope 的派生文件；之后可从 P1 index 重建
```

- 路径为 `<runtime>/graph/<sha256(repository_key)>/<sha256(snapshot_key)>/code-graph.json`。
  使用 UTF-8 scope keys 的 SHA-256 确定路径并隔离 repository/snapshot，避免把 key 当路径。
  内容仍保存并校验完整 scope keys；node/edge identity 不变。
- JSON 使用显式 schema/projection version、固定字段和 canonical record 顺序，无时间戳。
  同一 P1 snapshot 重建产生相同 bytes；加载后保留全部 source anchors/evidence。
- `save` 使用同目录临时文件并原子替换；`rebuild` 先完整投影再保存，失败不发布部分 graph。
  全量替换清除旧节点/边；`delete` 幂等且只删除该生成文件，已加载 query 不受影响。
- 缺失、损坏、版本不兼容、scope mismatch 和 I/O 失败抛 `GraphStorageError`；不冒充空图。
  P1 查询失败原样传播，不生成部分结果。
- 默认示例使用 ignored `var/`；`.gitignore` 另忽略 `code-graph.json`。运行目录必须放在
  target repository 之外。生成数据不提交 Git，源代码路径没有本地 ArkUI 硬编码。
- 最小实现全量加载/重建，不提供增量更新、自动 freshness 检测或并发 P1 snapshot 捕获。
  调用方负责正确提供 repository/P1 snapshot keys，且 projection 期间不可并发 rebuild index；
  原子文件替换不代表跨进程 writer 锁或 crash-durability 保证。

## P2-C：ArkUI domain metadata

`default_role_mapper().map(index, graph)` 返回独立、不可变的 `DomainMap`，包含原有
repository/snapshot scope、规则集 fingerprint、逐 symbol 的 role decision 及 Component
节点。它不修改 P1 identity/model，也不改变 P2-B generic nodes/edges。
`lookup(NodeIdentity.for_symbol(...))` 查 decision；`members(component_identity)` 只返回
确定归属的 symbol。`to_dict()` 可保存到 ignored `var/`，保留全部 rule/source evidence。

首版为经源码核对的有界 catalog，定义于 `graph/arkui_rules.py`，不是任意组件发现器。
每条 rule 必须同时匹配 P1 `CLASS`、完整 qualified name、精确 repository-relative
header path；只有名称或目录前缀匹配不够。Component key 由 catalog 显式声明，使用
`NodeIdentity("arkui.component", key)`。至少有一个确定成员才生成该 Component 节点，
其 anchors/evidence 来源于成员的已验证 rule matches。规则表按 ID 排序，并对完整配置
计算 versioned SHA-256 fingerprint；P1 graph、rule 和 evidence 输入顺序不影响结果。

Source path 以 P1 definition 为准，缺失时回退到 declaration。真实 TextPattern 的
declaration 在 `frameworks/core/common/ai/data_detector_adapter.h` 前置声明处，definition
在自己的 `text_pattern.h`；两者 identity 一致，前置声明完整保留，但不覆盖 definition
的归属。已知 definition 不在登记文件时，即使 declaration 匹配也保持 unknown。

| Component | 首版角色 | 明确的目录/文件边界 |
| --- | --- | --- |
| Button | ButtonModelNG / ButtonPattern / ButtonLayoutProperty / ButtonLayoutAlgorithm / ButtonBridge | `pattern/button/button_*.h` 中逐文件登记；Bridge 在 `pattern/button/bridge/arkts_native_button_bridge.h` |
| Text | TextModelNG / TextPattern / TextLayoutProperty / TextLayoutAlgorithm / TextBridge | `pattern/text/text_*.h` 中逐文件登记；Bridge 在 `frameworks/bridge/declarative_frontend/engine/jsi/nativeModule/arkts_native_text_bridge.h` |
| Menu | MenuModelNG / MenuPattern / MenuLayoutProperty / MenuLayoutAlgorithm / MenuPaintProperty / MenuBridge | `pattern/menu/menu_*.h` 中逐文件登记；Bridge 在 `pattern/menu/bridge/menu/arkts_native_menu_bridge.h` |
| 共享服务 | OverlayManager | `pattern/overlay/overlay_manager.h`，没有 component 归属 |

表内 `pattern/` 前缀为 `frameworks/core/components_ng/pattern/`，`*.h` 仅为展示简写，
实现采用精确文件路径。全部已登记 class namespace 为 `OHOS::Ace::NG`。
ToggleButtonPattern、MenuItemPattern、InnerMenuPattern、未登记的同名/近名 class
均不自动归入 Button/Menu；不传播 role 到 member functions 或派生类。

源码结构核对基于真实 revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885`：
ButtonPattern/MenuPattern 继承 Pattern；TextPattern 为多继承（包括 virtual Pattern）；
各 ModelNG 继承对应 Model；LayoutProperty/PaintProperty 对应各自基类；
Button/MenuLayoutAlgorithm 继承 BoxLayoutAlgorithm，而 TextLayoutAlgorithm 继承
MultipleParagraphLayoutAlgorithm/TextAdaptFontSizer。P1 当前没有 inheritance fact API，
因此这些是规则审查依据，runtime 不把文本声明伪装为语义继承边，不新增 C++ parser。

Decision 语义：

- `recognized`：联合证据只得到一个 `(role, component)`，相同候选的多条规则合并 evidence。
- `unknown`：缺 P1 symbol、非 class、无 qualified-name rule 或权威源文件不匹配；
  保留明确 reason 和现有 graph anchors，不分配 Component。
- `ambiguous`：完整匹配多组 role/component，保留全部候选及各自证据，`resolved=None`；
  不选第一个候选，不加入 Component membership。
- 输入 P1/class 与 graph 的名称/range 不一致时明确报 snapshot mismatch，不能静默套用旧图。

每个候选 evidence 带 versioned rule ID、精确 P1 identity/range，以及 class qualified
name、文件和显式 association 的解释。Component membership 是 domain metadata；
本阶段不新增 CREATE/UPDATE_PROPERTY/MEASURE/LAYOUT/SHOW/CLOSE 或其他 framework edges。

P2-C 必需验证为 `tests.integration.test_arkui_role_mapping.RealArkUIRoleSmokeTests`，
需显式配置 `ARKUI_REPO_ROOT`。缺配置直接执行该测试会失败，不能以通用 runner 未选择
external tests 代替 milestone 验收。Static expectations 在 `tests/fixtures/arkui_role_cases.py`，
独立于实现 catalog；真实 source → 现有 clangd provider → P1 index → P2-B graph → mapper。
smoke report 保存到 `var/validation/p2-c-role-smoke.json`，包含 revision、工具版本、source
hash、expected/actual role、identity 和 domain evidence。验证使用仓库 BUILD.gn 中的
`interfaces/inner_api/ace_kit/include` 等实际 include 路径，不伪造源码或 stub header。

## P2-D：Framework relation primitives

`extract_framework_relations(index, generic, domain, workspace)` 消费相同 scope 的
P1 index、P2-B projection、P2-C DomainMap 和只读 target workspace，返回
`FrameworkExtraction(graph, diagnostics, ruleset_identity)`。`graph` 是原有 GraphSnapshot，
nodes/identity 不变；typed edges 与原始 generic edges 共存，继续使用 endpoint/type dedup、
evidence union、canonical query order。没有新 graph model、parser、database 或 trace API。

首版规则 `arkui.framework.v1` 的边含义和必要证据：

| Relation | endpoints / 规则 | 必要 supporting facts |
| --- | --- | --- |
| CREATE | Pattern 的简单工厂方法 → 同 Component 的 LayoutProperty/PaintProperty/LayoutAlgorithm class | P1 method parent 指向 recognized Pattern；DEFINE；完整单条 `return MakeRefPtr<T>();` 函数体；模板参数精确位置的唯一 P1 REFERENCE；真实 CALL 指向 `OHOS::Ace::Referenced::MakeRefPtr`，其声明/定义文件为 `ui/base/referenced.h`，且源码模板确实执行 `new T` |
| UPDATE_PROPERTY | Model 的简单更新方法 → 同 Component 的 LayoutProperty/PaintProperty class | P1 parent、DEFINE、唯一目标 REFERENCE；完整单条 `ACE_UPDATE_LAYOUT_PROPERTY` 或 `ACE_UPDATE_PAINT_PROPERTY` 函数体；逐一验证 `view_stack_processor.h` 中入口宏和 NODE 宏，后者必须调用 `Update##name` |
| MEASURE | LayoutAlgorithm class → Measure / MeasureContent method | P1 semantic parent、DECLARE、recognized role，以及带 LayoutWrapper / LayoutConstraintF 类型和 `override` 的受支持完整声明 |
| LAYOUT | LayoutAlgorithm class → Layout method | 同上，完整 `void Layout(LayoutWrapper* layoutWrapper) override;` 声明 |
| SHOW / CLOSE | 共享 OverlayManager class → ShowMenu / HideMenu method | P1 semantic parent、DECLARE、recognized OverlayManager，以及经源码审查的完整 FrameNode/menu 参数契约 |
| TEST | 保持已有 test case → tested symbol | 只增强 P1 tested-symbol mapping 产生的 TEST evidence；目标 class 或其 P1 semantic parent 必须有确定 role；不增强 fixture membership，不声称 coverage |
| MOCK | 无新边 | 当前 P1 没有可靠 mock mapping fact，返回 `unsupported_p1_mock_facts` |

MEASURE/LAYOUT/SHOW/CLOSE 表示**声明的框架操作入口绑定**，不表示发生了调用；实际
CALL 仍独立保留。CREATE/UPDATE_PROPERTY 只覆盖上述完整简单函数体，复杂 lambda、
多语句 setter、条件分支、任意构造表达式保持 unsupported，不能外推完整创建/更新链。
符号由 P1 identity/parent 和精确 REFERENCE 决定；文本只检查已定位符号处的框架模板。
2048 字符窗口内必须匹配完整模板；不会扫描附近方法或用名称选择 overload。
宏证据是受支持源码模板的解释，不是新增的 preprocessor/semantic resolution backend。

每条新增边保存原始 P1 evidence、supporting generic EdgeIdentity、P1 parent identity、
role rule evidence/fingerprint、framework rule version、精确源码 range 及 source SHA-256
（UTF-8、换行规范为 LF）。CALL 原本的 caller-range 精度保持不变，不冒充 call-site。
文本读取按一次 build 缓存，返回前确认已读文件未变；I/O 失败原样抛出，不能变为空图。

缺 parent/definition/reference/factory CALL、unknown/ambiguous role、冲突 reference、跨
Component、未支持的源码模板或宏定义都不出边，并返回排序去重的 diagnostic。入口拒绝
scope mismatch、不匹配的 P1 generic projection，以及含旧 domain edges 的输入。调用方
仍须提供同一不可变 P1/source snapshot 和匹配 DomainMap；不自动创建新的 P1 facts。

完整 rebuild 为 `project_index → mapper.map → extract_framework_relations → store.save`。
`GraphStore.rebuild(index)` 本身仍仅生成 generic graph；不要把旧 domain graph 追加到新结果。
既有 JSON schema / `p1-index-v1` base projection 格式可保存全部 typed edges；framework
version 在 evidence/result 中。diagnostics 是 extraction report，不是 graph edge；可另存
ignored `var/`。同样输入重复构建的 graph JSON bytes 一致，替换存储清除旧派生边。

必需 smoke：`tests.integration.test_framework_relations.RealFrameworkSmokeTests`；配置
`ARKUI_REPO_ROOT`，执行真实 clangd → P1 index → generic graph → role map → extractor。
Button/Text/Menu 各验证 CREATE、UPDATE_PROPERTY、MEASURE，Menu 另验证 LAYOUT；
共享 OverlayManager 验证 SHOW/CLOSE，共 12 条边。Text 用实际 MeasureContent 入口，
不虚构继承而来的 Layout 边。报告在 `var/validation/p2-d-framework-smoke.json`，包含
revision、检查结果、source hashes、完整边 evidence 和 diagnostics。synthetic integration
走同一 provider 链路，并验证逆序 rebuild、canonical JSON bytes 和持久化往返。

## P2-E：Component Creation Trace

`trace_component_creation(index, graph, domain, workspace, seed=..., component=..., bounds=...)`
返回 `CreationTrace`。seed 是调用方显式选择的 P1 NodeIdentity，component 是已知的
`arkui.component` identity；不解析自然语言、不按名称猜入口或 overload。
输入可为 P2-B generic 或 P2-D framework graph。先核验 scope、节点与 P1 evidence；
允许 partial graph，**不从 index 补回传入 graph 缺失的关系**。

Traversal 只沿 graph 中存在、可由 P1 核验的 outgoing CALL。P2-D operation bindings、
property CREATE 和文件 REFERENCE 不充当 CALL hop。以同组件 Model 和经核验的 FrameNode
factory 为目标做反向可达过滤，排除已知其他组件分支；保留必要 supporting functions。
随后按 canonical edge 顺序枚举简单路径，用 per-path visited 保留 diamond 的不同路线。
到达 FrameNode factory 后停止 CALL 展开，核验 Pattern 参数；缺 relation/role、cycle 或
预算上限均显式报告，不排序挑选“最佳”路线。

`CreationBounds(max_depth=8, max_paths=32, max_states=1000)` 限制 CALL 深度、返回候选数和
forward path states。达到上限且仍有工作时 `exhaustive=False`；反向过滤/index 读取成本
不受这些输出/枚举预算限制。canonical 顺序只用于稳定输出，不表示优先级或置信度。

数据契约：

- `CreationTrace`：repository/snapshot scope、seed、component、status、paths、exhaustive、
  diagnostics 和 `p2.creation.v1` ruleset identity。
- `CreationPath.nodes`：有序 `CreationNode`，包装既有 GraphNode、trace-local stage 和 evidence。
  stage 为 Entry/Bridge、support、Model、FrameNode、Pattern；不修改 graph/P1 symbol kind。
- `relations`：按路径排列的连续真实 CALL edges，保持原 endpoints/evidence；P1 caller range
  仍是声明/定义精度，不冒充精确 call-site。
- `pattern_argument`：独立的 caller / frame_factory / pattern 参数关联，带 supporting
  CALL/REFERENCE、source range/hash、allocation 和 role evidence；**不是新 GraphEdge**。
  Pattern 是由 caller 构造后作为参数传给 FrameNode，不能伪造 FrameNode → Pattern CALL。
  节点展示顺序是架构顺序，不是 C++ 参数求值/执行时序。
- `pattern_candidates` / `issues` 保留已解析但不能确定归属的 identity 及原因。候选参数类型
  unknown/ambiguous 时可保留 source-proven association，但不把节点标为 Pattern stage。
- `complete`：穷尽预算内候选后恰有一条无缺口的 Entry/Bridge → Model → FrameNode + Pattern
  关联；`incomplete`：缺事实、未支持的源码模板或搜索截断；`ambiguous`：存在多条候选路径，
  或 role/reference/allocation identity 有歧义。每条 path 另有自身 status；ambiguous trace
  可以包含多条各自 complete 的 path。截断时即使已找到一条 complete path，也不宣称唯一完整。

FrameNode 仅作 trace-local 识别：P1 method 的真实 parent 必须为声明/定义在
`frameworks/core/components_ng/base/frame_node.h` 的 `OHOS::Ace::NG::FrameNode` class，
method 是同 header 中的 CreateFrameNode/GetOrCreateFrameNode。没有新增通用 role catalog。

首版 Pattern association 只支持 semantic caller definition 处第一条语句中的直接表达式
`FrameNode::CreateFrameNode(tag, nodeId, AceType::MakeRefPtr<T>())`。Frame factory method
和 T 都须有精确位置的唯一 P1 REFERENCE；真实 CALL 必须指向已核验源码确实 `new T` 的
Referenced::MakeRefPtr；T 的 role/component 须确定匹配。复用 P2-D 的只读 range/hash accessor，
不重解析 C++，不把 lambda/函数指针/变量数据流猜成新的语义边。

真实预期在 `tests/fixtures/creation_cases.py` 中于 query 运行前根据源码冻结（revision
`0096f5bd943ed1f7fa56883aed0e2379f13c2885`）；测试逐行检查关键表达式后再走真实 P1 链路。
Button：CreateButtonFrameNodeForCustom → ButtonModelNG::CreateFrameNode → FrameNode::CreateFrameNode，
参数为 ButtonPattern；Text：ViewModel::createTextNode → TextModelNG::CreateFrameNode → 同一
FrameNode factory，参数为 TextPattern。两者 complete。Menu：CreateMenuFrameNode →
MenuModelNG::CreateFrameNode → FrameNode::GetOrCreateFrameNode；源码回调构造 InnerMenuPattern，
该类在 P2-C 为 unknown，当前无 callback argument binding，故预期 incomplete。不得用
MenuPattern 替换，也不因真实验证通过而声称 Menu trace 完整。

真实收集器在加载实现与 header 后查询入口 outgoing 和 Model incoming/outgoing facts，
保留 P1 identity，并优先使用已有 document record 的 parent/range。无需修改 P1 adapter。
`var/validation/p2-e-creation-smoke.json` 导出 expected/actual、节点和 relation provenance、
candidate/缺口、源码审查位置和 hashes；这是 ignored report，不是新持久化 graph model。

## P2-F：Property Update Trace

`trace_property_update(index, graph, domain, workspace, seed=..., setter=..., component=..., bounds=...)`
要求显式的 entry 与 setter **完整 P1 NodeIdentity**，不接受 setter 名称作为 identity。
component 是已有 P2-C component identity。返回 `PropertyTrace`，不修改 P1、graph 或 role catalog。
seed 可直接为 setter，此时保留局部更新片段并报告 `missing_entry_call`。

先核验 scope、P1 nodes/edge evidence，只沿传入 graph 中已验证的 CALL 做反向可达过滤，
再按 canonical edge 顺序、per-path visited 枚举 entry → 指定 setter 的 direct supporting
call chains。不会跳到同名的另一个 overload，也不会把 operation binding 当成 CALL。
到达 setter 即停止 CALL traversal；role 冲突、缺边、cycle、预算耗尽均显式报告。
`PropertyBounds(8, 32, 1000)` 分别限制 CALL 深度、返回 paths、forward path states；
P1/source 核验、反向可达和局部读写证据枚举成本不受该输出预算限制。

setter 的 P2-C semantic parent 必须是同 component 的 Model。P2-D `UPDATE_PROPERTY`
仍只表示 method → property class；query 复用 extractor 重新验证其源码/宏语义与 evidence，
且必须在传入 graph 中实际存在，DEFINE/REFERENCE 也不能从 index 补回。单语句
`ACE_UPDATE_LAYOUT_PROPERTY/ACE_UPDATE_PAINT_PROPERTY(Target, Token, value)` 中的 Target
以精确 source range 的唯一 P1 REFERENCE 绑定；布局/绘制宏与 P2-C property role 必须一致。
Token 是带 source range/hash 的语法标签，不是编造的 P1 property/member identity。
同一 target 的 role 冲突或多个 reference identities 返回 ambiguous，unknown/跨 component
返回 incomplete。`ACE_UPDATE_NODE_*` 是 P2-D v1 的已知未支持模板，不在本 milestone 扩充。

下游首版只支持可验证的显式成员读写：macro 的真实 CALL endpoint 必须是目标 property
class 的 METHOD，`Update<Token>` 拼写仅核对该已解析 identity；完整 tiny body 将形参赋给
一个由精确 REFERENCE 指向的同 parent FIELD。reader 的完整 tiny body 返回同一 FIELD
identity，并有真实 consumer → reader CALL，才纳入 consumer。reader 不必叫 GetXXX；
同名 getter、其他 field、继承成员、复杂函数体、宏生成成员 artifact 都不能替代这些证据。
这是静态同一成员的更新/读取关联，不证明运行时对象相同、调用先后或渲染效果。

数据契约：

- `PropertyTrace`：scope、seed、setter、component、status、paths、exhaustive、diagnostics、
  `p2.property.v1` ruleset。
- `PropertyPath.nodes`：架构顺序的 Entry/Bridge/support → Model → LayoutProperty/PaintProperty
  → writer → state → reader → consumer；每项包装既有 GraphNode、stage、source/role/parent evidence。
- `calls` 仅为连续的 entry → setter CALL；`binding` 保存 class、具体 token、role、原始
  UPDATE_PROPERTY edge/evidence；`support` 保存读写关联涉及的真实 CALL/REFERENCE endpoints。
  特别是 consumer → reader 的方向不反转，不虚构 property → consumer graph edge。
- `candidates`、`candidate_evidence`、`gaps` 保留冲突 identity、源码/语义证据和未恢复阶段。
  class role evidence 与 macro source fingerprint 可追溯；P1 CALL caller-range 不冒充 call-site。
- `complete`：穷尽后仅一条无缺口的完整静态更新/读取链；`incomplete`：缺事实、unsupported
  模板/consumer 或截断；`ambiguous`：多条候选路径、identity 或 role 冲突。每条 path 另有
  status；路径排序不是 ranking，截断结果不宣称唯一 complete。

真实 source expectations 冻结在 `tests/fixtures/property_cases.py`。Button/Text/Menu 均选
FontWeight：native entry 调用 FrameNode* overload，因 NODE macro 尚未形成 P2-D binding，
预期停于 Model；另以单参数 stack overload 为 seed，验证已有 UPDATE_PROPERTY 能到达
LayoutProperty，同时报告缺入口与缺显式 property writer。两片段不得按同名合并。
源码已存在后续 GetFontWeight consumer，但宏生成 FIELD/accessor 不满足本版显式读写规则，
不得用源码中的名字替代 P1 identity。smoke 在 query 前检查入口、精确 overload 定义、宏、
property 声明和 consumer 源码位置，再执行真实 clangd → index → graph → role → framework
→ property query；报告 `var/validation/p2-f-property-smoke.json` 含真实 source checks、revision、
各片段完整结果与 evidence、文件 hashes，并检查逆序 rebuild、持久化往返和重复结果相等。

## P2-G：Measure / Layout Trace

`trace_measure_layout(index, graph, domain, workspace, seed=..., component=..., bounds=...)`
返回 immutable `LayoutTrace`。seed 为显式 Pattern P1 identity，component 为显式已知
component identity；不从自然语言或同名字符串选择入口、重载或目标 algorithm。
输入允许 partial graph：核验 scope、P1 nodes/evidence，并用 P2-D extractor 重验 binding
语义；只有输入中存在且 supporting generic edges 全部仍存在的 binding 才可采纳。
不会从完整 index 恢复 partial graph 缺失的 CALL、REFERENCE、DECLARE 或 DEFINE。

最小 traversal 是有界的架构阶段选择：Pattern → factory → algorithm，然后分别核验
MEASURE 和 LAYOUT 操作及其 definition，最后收集实现中的 LayoutProperty dependency。
Pattern → factory 由 P1 METHOD parent identity 证明，没有虚构 class → method CALL。
factory → algorithm 严格使用 P2-D CREATE（简单完整 return、唯一目标 REFERENCE、真实
MakeRefPtr CALL/new T）；Measure/MeasureContent 与 Layout 分别使用 MEASURE/LAYOUT。
operation binding 是 algorithm → method，**不会生成 Measure → Layout relation**。
声明没有 definition 时保留 binding，报告缺 implementation，不把声明充作实现 stage。
未声明的 inherited Layout 不外推，当前 P1 没有可支持该推断的 inheritance/override facts。

对 P1 定位的 factory，额外允许完整有界 switch/case + MakeRefPtr return 模板提供精确
REFERENCE 候选；它只解释候选 identity，不解析条件、不选择默认分支、不新增 CREATE。
多 algorithm（例如真实 Menu）返回 ambiguous；任意参数/分支工厂不据此提升为可创建链。
其他 unsupported body 停在 factory。Text 的复杂有参工厂即为该能力边界。

LayoutProperty dependency 只接受 operation definition 开头受支持的直线语句序列，以及
`auto p = [AceType::]DynamicCast<T>(layoutWrapper->GetLayoutProperty());` 的目标 token
精确 P1 REFERENCE。允许的 preamble 为 GetHostNode/GetPattern、已审查的 null guard、
ACE_UINODE_TRACE 和 MenuDumpInfo 声明；不跨 branch、注释、字符串、预处理或邻近方法。
T 必须有同 component、无歧义的 LayoutProperty role；不根据 `*LayoutProperty` 名称
猜 identity，不把文件其他位置的 reference 借过来。它证明静态类型依赖，不证明 cast
成功、同一运行时实例或 property 值传播。缺失 reference/role 或不支持的 preamble 留 gap。

结果契约：

- `stages` 按 Pattern/factory/algorithm/Measure/Layout/LayoutProperty 的架构顺序保存
  存在的阶段；每阶段保留全部已接纳候选及原 GraphNode anchors、P1 parent/role evidence。
  缺阶段不补造占位 node；多 Measure/MeasureContent 或 Layout identity 显式 ambiguous。
- `bindings` 保存有序 CREATE/MEASURE/LAYOUT 和原 endpoints/evidence；`support` 保存
  原 file → symbol DECLARE/DEFINE/REFERENCE。`calls` 独立保留 factory/operation 的真实
  一跳 outgoing CALL，包括环；不递归展开、不把 operation binding 伪装为 CALL。
  P1 caller definition/declaration 精度不冒充 call-site，也不声称这些 CALL 连成连续路径。
- `dependencies` 显式记录 operation identity、property identity、原 file REFERENCE 和
  精确 preamble source range/hash；`source_evidence` 保存 factory 候选模板和 implementation
  起始签名核验的 source range/hash。`candidates` 保存未解决 identity 和所有 role evidence。
- `gaps` 是稳定排序的原因集合。完整唯一静态片段为 complete；缺事实/unsupported 为
  incomplete；多候选/identity/role 冲突为 ambiguous，优先于 incomplete。
- `LayoutBounds(max_candidates=32, max_calls=100)` 分别限制各阶段/未解决候选列表及
  总一跳 CALL 输出。超限时 `exhaustive=False` 且明确 gap，不能返回唯一 complete；
  已知歧义不会因截断为单候选而丢失。这些不是 P1/source 读取成本或时延预算。
- 不展开一跳 CALL 的目标，因此不存在递归 cycle 搜索；成员选择、binding 缺失、
  unsupported body、未解决 factory/algorithm、阶段结束或预算触顶均有确定终止条件。

真实预期在 `tests/fixtures/layout_cases.py` 的 `REAL_CHECKS/REAL_EXPECTED` 中于首次 query
前冻结。Button 恢复 Pattern → factory → ButtonLayoutAlgorithm → Measure，并取得
ButtonLayoutProperty dependency；其 inherited Layout 留 missing_layout_binding。
Text 停于 unsupported factory；Menu 保留 Menu/MultiMenu/SubMenu 三候选并 ambiguous。
synthetic 原创可执行 C++ 验证完整 Measure + Layout 及各自的 property reference。
真实采集切片包含 factory allocation CALL 与 operation DEFINE/REFERENCE/parent；
不枚举所有 operation callees，避免既有同步 adapter 的大量 didClose 通知管道阻塞。
synthetic 采集 operation CALL 并验证其保留；trace API 对输入中存在的 CALL 按同一规则处理。
报告为 ignored `var/validation/p2-g-layout-smoke.json`。不改变 P1/P2-B/C/D 语义、
不实现 Overlay、Task-driven Graph Expansion、Task Subgraph 或 Context Pack。
