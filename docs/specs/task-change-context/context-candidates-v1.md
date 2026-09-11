# Task Subgraph / ContextCandidateSet v1 — P3-E

公开入口 `arkui_agent.context.materialization.materialize_context`，输入为 D 的 `ExpansionResult`（Task）或完整 `ChangeExpansionResult`（Change）。依赖 [C1](candidate-retrieval-v1.md)、[C2](change-range-mapping-v1.md)、[D](graph-expansion-v1.md) 及 [B binding](knowledge-snapshot-v1.md)。不重新检索、扩展 graph、访问 semantic backend，也不进行 ranking、tiering、token selection、Context Pack 或 refresh。

```python
from arkui_agent.context.materialization import materialize_context, ContextCandidateSet

task_candidates = materialize_context(task_expansion, target=original_session)
change_candidates = materialize_context(change_expansion, base=base_session, head=head_session)
restored = ContextCandidateSet.from_json(task_candidates.to_json())
```

session 可缺失，此时仍可提取任务视图，但不会把旧观察中的 matched text 当作本次已验证 snippet。传入错误 session 返回 `binding_mismatch`；混合 input、candidate 或 expansion scope 是 `MaterializationError`。Change 单侧 expansion 不接受为独立 Task，必须保留双侧 envelope 及未映射范围。

## Immutable ranking input

所有输出 records 为 frozen dataclass，集合使用 tuple；没有可变 dict/list 字段。`ContextCandidateSet` 包含：

| 字段 | 用途 |
| --- | --- |
| input / input_id | 完整 Task/Change 与 canonical SHA-256 input reference；包括 diff/hunk provenance |
| bindings | 原 B BindingReference，含 revision、generation、source fingerprint、artifact identity、scope/freshness；解码不证明当前 fresh |
| upstream | 完整 typed C1/C2/D 观察、query reports、bounds/policy、seed/trace request、summary、gap、unavailable/unsupported/unresolved/truncation；不改写 P2 status |
| candidates | 统一 ContextCandidate records；不丢弃可用或不可用候选 |
| subgraph | candidate-ID 索引的 Task/Change 视图及明确非 induced 边界 |
| snippets / backings | range 的 materialization 状态与共享源码块 |
| snippet_bounds | 本次 I/O 和单 backing 大小限制；不是 token budget |

`ContextCandidate` 含 candidate_id、kind、repository、revision、snapshot（未绑定 Change 范围可为 None）、side、typed observations、origins、source_hashes、source_ranges、dependencies、limitations。

- scoped ID 对 `(snapshot, repository, revision, side, fact key)` 做 canonical SHA-256。沿用 C1 fact key：Symbol 与 GraphNode 是不同视图；DirectCallRelation 与相同 P2 CALL identity 合并 observations，保留两种证据精度。range 以精确 SourceRange 区分；其他 evidence/association 使用完整 typed structural identity。不按展示名合并，不跨 revision/generation/side 合并。
- kinds 区分 node、fact、range、relation、trace_association、property_binding、supporting_evidence、change_range。fact payload 保留 Symbol/RangeFact/test/domain 的原类型；纯文本命中没有被补造 SymbolIdentity。test mapping 与按名称找到的 test 仍可区分。
- origins 引用 C1 candidate ID/C2 anchor ID/D query ID、query IDs、seed、reason 和原 observation 字段路径。BFS `NodeVisit.depth` 另存 query-local distance；trace 架构顺序不转换为 hop。C1 原始 channel/selector/QueryOrigin 与 D trace_request/seed reason 通过 upstream 可查。没有 query 的距离为 None。
- limitations 保留 ambiguity/unresolved/truncated 和原始说明；结构化 gap、unsupported、status、animation、exhaustive 以 observations/upstream 为权威。查询级 ambiguity 可保守地传播到该观察的 supporting candidates，不把相关证据说成唯一确定。
- dependencies 引向真实已物化 candidate IDs。父记录引用其嵌套 endpoints、ranges、supporting relations/evidence。支持同一 endpoint 共享、self-loop 关系；不让 candidate 依赖自己。node reference 只链接观察到的源码 ranges，避免 node/symbol 双向依赖。

## Subgraph extraction boundary

E 只抽取已接纳的 retrieval/expansion observations 和 C2 输入范围；不补充 seed 邻居、不为“同组件”纳入成员、不补全 visited nodes 之间未观察的 edges。被 D 省略的观察保持 None 与完整 summary，不能重新 materialize 被预算拒绝的正向事实。

`TaskSubgraph.nodes/relations/associations/bindings/supporting` 分别引用 candidates。完整 snapshot/side 在 candidate 上，Change 双侧不会拼成一个跨 revision graph。完整性只相对于已观察范围，boundary 固定说明 `not induced`。

所有真实关系端点均有显式 NodeIdentity candidate；可用的 Symbol/GraphNode 范围作为依赖复用。上游只有 opaque endpoint 时保留 `endpoint_not_observed`；GraphNode 仅有 identity anchor 时保留 `endpoint_source_unresolved`。这是 E 的未解析引用，不生成假的 P2 GraphNode、SourceAnchor、relation 或 source range。没有额外 node lookup/graph traversal。

按原 [P2 evidence/query](../code-graph/graph-model-and-query.md) 与 [trace specs](../code-graph/README.md) 分开表达：

- GraphEdge 与 DirectCallRelation 进入 relations，关系方向和类型不变。UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW/CLOSE 等 GraphEdge 仍是原 binding relation，不转 CALL。
- PatternArgument、LayoutDependency 作为独立 association；PropertyBinding 独立保留 token/class/role/relation。
- CreationPath、PropertyPath、OverlayPath 保留为 trace-local association 容器，包含原路径顺序、state/read/write/support、managed node type、animation、candidate/gaps。它们不是新关系类型。Overlay Show/Close 配对声明与 trace/leg 状态保留于 upstream。
- 不把节点阶段顺序解释为执行顺序，不证明同 runtime instance，不以独立文本/宏片段恢复 P2 missing binding。

C2 RangeMapping 包括 binding、extent proofs、anchor、ambiguity 与诊断。即使没有 base，old range 与原 deletion hunk 仍存在；range candidate 是输入坐标，只有 snippet 校验成功才是可读取源码证据。无 path/无 range 保留 mapping candidate 与明确 `range_missing`，不会拿 head 代替。

## Snippet verification and overlap

只有 SourceRange candidates 执行 materialization；其他 candidate 通过 range dependency/source_ranges 消费共享文本。没有已观察 range 的候选有 `range_missing` 记录。源坐标沿用 P1 1-based Unicode code point、end-exclusive；验证行列、空文件、EOF，不能静默裁剪越界。

1. 使用原 B session reference，精确比较 repository/revision/generation/完整 binding；缺 session 不隐式使用当前 checkout。
2. 所有参与侧的 `session.read()` 在同一 ExitStack 保持开启，进入/退出都由 B 验证。只使用 bound workspace.resolve，在 repository 边界内以只读 binary 模式读取。
3. 按 scope/side/file 缓存一次读取，最多 `max_file_bytes + 1` bytes（默认 4 MiB + 1）。验证 raw SHA-256 与 B fingerprint 及每个 observation FileHash 一致，UTF-8 严格解码。另核验 P2 明确标注的 `normalized-newline source sha256=...`（LF 归一化 digest）；不把 raw/normalized hashes 混用，也不解析 description 推断语义。
4. 原始 UTF-8 文本保留 CRLF/LF，不改写源码。按声明坐标计算偏移。完全相同 range 合并来源；同 file/snapshot/side 的严格重叠范围合成最小 union backing，邻接范围不合并。每条 CandidateSnippet 保留原 range、backing ID、相对 Unicode start/end offsets。重叠不合并语义 identity 或 ambiguity。
5. backing 最大 `max_backing_characters=65536`，超出时整个 overlap group 为 `materialization_limit`，不选一条“最好”的范围、不截取前缀。所有候选和依赖保留。读取文件超限也显式返回 limit。

SnippetStatus：available、source_unavailable（含缺 session/未绑定/路径不可读/解码失败）、binding_mismatch、consistency_failure、source_hash_mismatch、range_invalid、range_missing、materialization_limit。失败记录没有 backing/offsets。文件删除通常在 B guard 进入时即失败为 consistency_failure，并保留 B `source_unavailable` 等 typed reason 的文字；不能伪装空 snippet。

任一参与侧 B guard 失败（包括退出时漂移），本次所有参与侧的 provisional backings 全部丢弃，range 记录改为 consistency_failure。已提取的历史观察仍保留，代表上游绑定时的事实；不得因为其中原 binding.freshness=fresh 声称本次源码读取 fresh。普通缺侧/错误 session 不借另一侧修复。B 的检测型一致性与检查点之间不可检测的变化限制仍然适用。

I/O bounds 只限制 E 单文件读取与输出 backing，不承诺 B artifact/source 验证、全部 upstream 元数据或 extraction 内存的全局上限。E 不计 token；超限不代表事实不存在。调用方可显式提高 bounds 重试原候选。

## Serialization and validation

`to_json()/from_json()` 使用 `p3-context-candidates-v1` envelope，闭合的 annotation-driven decoder 仅接受 ContextCandidateSet 及其 statically referenced dataclasses/enums，不按 JSON 字符串 import 类。tuple/frozenset、POSIX path、enum 与 optional 字段恢复原类型；type tags 不混用不同 payload。

拒绝未知版本/type/字段、重复 key、错误 scalar（含 bool 冒充 int）、错误 candidate/backing identity、悬空 dependency/subgraph/snippet reference、缺 relation endpoint、错 scoped backing 或 range/offset。构造/解码后保留 identity、关联和再次序列化文本；这不是 freshness revalidation。JSON 仍含完整 typed upstream，不是最终 Context Pack 序列化格式。

## Acceptance

新增行为测试在 `tests/integration/test_context_materialization.py`、`tests/unit/context/test_materialization.py`，由 trusted Stop Hook targeted 执行。测试不代替真实 ArkUI source/provenance 验收；修复后 Hook、已规划真实 smoke 与用户授权的 [E evidence gold](../../evaluation/p3-e-materialization-annotations.md) 冻结均完成，见 [验收报告](../../evaluation/p3-e-materialization-smoke.md)。P3-E Completed，F/G/H/I 不启动。真实 Change 双侧 E smoke 保留为未验证项，由后续 P3-I 综合验证，不扩为 E 新门槛。
