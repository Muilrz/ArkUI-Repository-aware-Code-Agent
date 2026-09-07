# Graph Model and Query Specification

对应 P2-A。实现位于 `src/arkui_agent/graph/model.py`、`query.py` 和 `memory.py`。本规范消费 P1 类型，独立于 semantic provider、SymbolIndex、retrieval 和 storage backend。

## Identity and P1 traceability

- 一个 graph snapshot 对应一个 repository 和一套 P1 identity；identity 不承诺跨 repository 全局稳定。
- `NodeIdentity(namespace, key)` 与 display name、NodeKind 和 source range 分离。
- `symbol` namespace 的 key 原样复用 `SymbolIdentity.value`，保留 overload 区别；`file` namespace 原样复用 `RepositoryFile.path`。不得从同名结果猜 identity。
- Domain entity 使用调用方提供的 namespace 和 stable key。P2-A 只定义类型词汇，不识别 Component 或 role。
- `NodeIdentity.value` 使用带 `v1` 前缀的 canonical JSON 表示；不用 Python hash、自增序号或 display name 构造 identity。
- `GraphNode.anchors` 复用 P1 `SymbolIdentity`、`RepositoryFile` 和 `SourceRange`，可以同时保留 declaration、definition 等位置。range 必须与其 file 一致。
- 每个 node 至少有一个 P1 anchor。P1 仅知道 symbol/file 时允许 range 缺失，不伪造位置。坐标沿用 P1 的 1-based、half-open 约定。

## Node and relation vocabulary

Graph model 为 Symbol、Function/Method、Class、Component、ArkTS API、Bridge、Model、Pattern、LayoutProperty、PaintProperty、LayoutAlgorithm、OverlayManager、TestFixture 和 TestCase 提供统一 NodeKind。

RelationType 统一表示 DECLARE、DEFINE、CALL、REFERENCE、INHERIT、OVERRIDE、CREATE、UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW、CLOSE、TEST 和 MOCK。关系是否当前可生产由 projection/framework specification 决定；类型存在不表示已具备证据。

## Relation identity, merge, and provenance

- `EdgeIdentity(source, target, relation)` 表示有向关系。反向 edge、不同 relation 和 self-loop 都有独立语义。
- 同一端点之间的多次 CALL/REFERENCE 共享 relation identity，各 occurrence 放入 evidence。
- 每条 edge 必须包含非空 `RelationEvidence`。provenance 标识 producer/fact/rule；anchor 指向 P1/source；description 说明证据含义和精度。
- P1 `DirectCallRelation.source_range` 是 caller definition/declaration 时，必须原样说明，不能冒充精确 call-site。
- 相同 identity 的 edge 合并 evidence 集合；合并具有交换性、结合性和幂等性。不同 identity 不能合并。
- anchors 和 evidence 按 canonical sort key 排序去重。所有 records 使用 immutable dataclass 和 tuple，结果不依赖输入集合顺序。

## Query semantics

`GraphQuery` 是 read-only structural Protocol，后端无须继承参考实现。

- `node` 按完整 identity 查询；缺失返回 `None`。未知 node 的其他查询返回空结果。
- `incoming_edges` / `outgoing_edges` 返回唯一 edge，并按结构化 edge identity 排序。
- `relations=None` 表示所有 relation；空 frozenset 表示不匹配任何 relation。
- `neighbors` 支持 incoming、outgoing 和 both，按 node identity 排序去重。BOTH 不翻转 edge。
- `traverse` 是通用 FIFO BFS。seed 深度为 0；每个 node 只访问一次；visits 保持发现顺序并携带最短 hop depth。
- traversal 返回已检查并接纳的唯一 edge，按全局 canonical edge 顺序排列，包括 self-loop、cycle edge 和 cross-edge。
- `max_depth` 必填且非负；到达该层后不再展开。结果不是 induced subgraph，也不是 domain trace。
- `max_nodes` 默认 100（包括 seed），`max_edges` 默认 1000。预算限制返回结果规模，不承诺后端加载成本或运行时间。
- 检查新 edge 时先检查 edge budget，再检查新 endpoint 的 node budget。被预算拒绝的 edge/node 不进入结果。
- `stopped_by` 仅在下一项被 `NODE_LIMIT` 或 `EDGE_LIMIT` 阻止时设置；恰好达到上限且没有更多内容不算截断。
- 参数错误抛 `TypeError` / `ValueError`；后端错误抛 `GraphQueryError`，不能表示成空结果。一次 query 必须基于一致 snapshot。

## Reference implementation

`MemoryGraph` 只消费已构造的 node/edge，并提供无写接口的内存查询实现和 contract tests：

- 精确重复 node 去重；相同 identity 但内容冲突时报错。
- 重复 edge 合并 evidence。
- dangling edge 明确报错。
- 未解析 symbol 可以用 symbol-only anchor 显式表示。

`MemoryGraph` 不负责 P1 projection、持久化、ArkUI role recognition、framework extraction 或 task-aware expansion。相关行为分别见其他 P2 specs。
