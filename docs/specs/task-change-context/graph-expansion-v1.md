# Task / Change-driven Graph Expansion v1 (P3-D)

入口为 `arkui_agent.retrieval.expansion`。依赖 C1 candidate result、C2 Change retrieval envelope 与 B 的原始 `SnapshotSession`。只消费 [P2 graph/query](../code-graph/graph-model-and-query.md) 和四类 [trace contracts](../code-graph/README.md)，不修改 P2 ruleset、relation 或 frozen expected。

```python
expander = GraphExpander(ExpansionPolicy())
observations = expander.expand(c1_result, session, traces=(...))
change_observations = expander.expand_change(
    c2_result, base=base_session, head=head_session,
    old_traces=(), new_traces=(),
)
```

## 输入、选择与身份

Task 从 C1 Symbol、带 identity 的语义 RangeFact、GraphNode、RoleMapping、TestFixture/TestCase 取 seed，合并同 identity 的 candidate/query IDs、reason 与 uncertainty。文本命中不产生 symbol identity；不把 relation endpoint 或组件全体成员自动提升为 seed。C1 request 中显式 `SymbolSeed/GraphSeed` 也保留，因此 C2 已证明的 selector 不受 C1 candidate 输出截断影响。C2 mapping 的完整 hunk/extent/ambiguity/unresolved 在 Change envelope 中保留，不据 changed symbol 声称行为影响范围。

seed 使用完整 snapshot identity、revision、generation、side。Task 默认 outgoing，Change 默认 both；只沿实际 graph edge 扩展跨组件依赖，不用同名、同目录或同组件生成关系。默认 relation family 为 CALL、CREATE、UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW、CLOSE、TEST；可配置精确集合，包括空集。DECLARE/DEFINE/REFERENCE 需显式开启，避免默认经 file 节点扩大召回。

自动 trace planning 只识别显式 action hint 值：create/creation/创建 对有 P1 semantic parent 且 parent 有无歧义 Bridge/Model role 的候选调用 creation；layout/measure/布局/测量 对有无歧义 Pattern role 的候选调用 layout。role/component 来自 P2 metadata。不能适用时保持 seed 和诊断，不猜测未知自然语言或 runtime 分支。

四类 trace 均支持显式 `TraceRequest(family, seed, component, reason, ...)`。Property 必须提供 setter；Overlay 必须提供 manager 和非空 Close seeds，seed 为 Show entry。辅助 symbol 必须出现在同侧 C1/C2 seeds 并存在于 graph；component 必须存在于 domain catalog。参数仍由 P2 校验，不表示 P3 已证明完整 trace。Overlay 配对只是调用方任务意图，不能证明同一 runtime instance。自动 planner 不猜 setter overload 或 Show/Close 配对。所有请求保留原参数与 reason；辅助参数的 provenance 可通过结果中的 scoped seeds 查回上游。

## Policy、预算和确定性

`ExpansionPolicy.version=p3.expansion.v1`，未知 version 拒绝。完整配置参与稳定 `policy_id`；方向/relation/family 必须为 typed enum，限额不接受 bool/float。所有结果是 frozen dataclasses；canonical JSON 标识 `p3-d-expansion-v1` 或 `p3-d-change-expansion-v1`，不提供最终 Pack/deserializer。

| 配置 | 默认值 | 边界 |
| --- | ---: | --- |
| max_depth | 2 | P2 BFS hop scope；path trace 的 CALL depth。零深度跳过 path trace，layout 是独立阶段查询 |
| max_nodes_per_seed / max_edges_per_seed | 100 / 200 | 同主 seed 的已接纳观察 identity 并集；亦传入 P2 traversal |
| max_queries_per_seed | 8 | 同主 seed 的 traversal/trace 尝试数 |
| max_paths_per_seed | 32 | 同主 seed 所有 trace 的 path occurrences；亦传入 P2 各 path family |
| max_states_per_trace | 1000 | P2 path trace forward states；Overlay 按其 contract 分 leg |
| max_layout_candidates | 32 | P2 layout 各阶段候选限额；calls 限额使用 max(1, max_edges_per_seed) |
| max_queries | 64 | traversal/trace 操作尝试数，包含失败/缺参数的尝试；不含 identity/metadata/source guard lookup |
| max_nodes / max_edges / max_paths | 500 / 1000 / 128 | 已接纳扩展观察的全局 identity 并集 / edge identity 并集 / path occurrences |

seed 按完整 identity 排序。先按 seed 执行一次遍历，再按 TraceRequest canonical key 去重和排序执行 trace；这是查询调度顺序，不是 ranking。多个查询可保留同一关系的原始观察及各自 provenance，全局计数只计一次 identity。路径按 query 内 occurrence 计数，不把不同 trace 的路径当作语义等价。

node 计数保守地包含观察中所有 NodeIdentity（包括 component、未解析候选、association 参数与 edge endpoints），不只统计已解析 GraphNode。上游 C1/C2 envelope、seed/query 元数据、被拒绝观察的 summary 不计入新增 fact budget；它们不是最终 context，也没有 token budget 保证。

遍历直接调用 P2 `traverse`，保留 visits/depth、真实方向、typed edges 和 `stopped_by`，不重写 BFS。达到 max_depth 是查询范围边界，记录 `depth_scope`，不声称更深层不存在事实。P2 的 node/edge cut 原样保留，恰好达到限额不因计数本身标截断。

每个返回观察再进行 source 与全局/per-seed 总预算检查。只有超过限额才拒绝；原子接纳或省略整个观察，不剪断 trace、改写 association 或随意选择其中一条路径。省略时 observation=None，status=truncated，记录所有超限原因，并保留 `ObservationSummary` 的 P2 status/ruleset/exhaustive、所有嵌套 gaps/issues/diagnostics 及 node/edge/path 数量。因此即使不能接纳路径，已知 ambiguity/gap 不会成为 complete。上游完整候选仍保留，可用更大明确预算重新查询。

Change 在双侧外层 B read guards 内完成，默认先 head supporting context，再 base；base 使用剩余全局预算，分别记录有效 policy。节点/边跨侧不合并，即使 opaque identity 相同。任一侧缺失保留 None 与完整 C2 mapping；另一侧不借用其 identity/range。任一运行中漂移使整个 Change expansion 失败。

这些预算控制 P3 查询次数与新增输出，不保证 P1/P2 单次调用的扫描量、加载内存或耗时。P2 trace 会核验 projection/source；P3 不为严格 backend 成本改写 P2。不同 policy 的输出不承诺单调，也不以预算拒绝表示事实不存在。

## 观察与不确定性

`ExpansionResult` 保留完整 upstream、policy、所有 seeds、各 query report、unavailable relations、边界诊断与实际计数。每个 report 关联主 seed、显式 trace request（若有）、query ID、status、diagnostics、原始 typed P2 observation、summary 和绑定 source hashes。

完整 P2 trace 原样嵌套；creation Pattern argument、property state association、layout property dependency、Overlay manager association 均不转成 GraphEdge/CALL。Menu layout 多 algorithm 与 Overlay 多 Close paths 不通过 hint、canonical 顺序或预算裁剪消除。独立 graph evidence 即使命中，也不改变 trace 原 status、gap 或 ruleset；P3 不修复 frozen missing relation。

`ok` 仅表示该观察已接纳，仍须读取 diagnostics/seed uncertainty；`partial` 表示已接纳的 P2 trace 非 complete；`unresolved` 表示缺 seed/component/source；`unsupported` 表示 trace family 被 policy 关闭；`failure` 表示公共 provider 操作失败；`truncated` 表示预算阻止查询或接纳。P2 unavailable INHERIT/OVERRIDE 及当前无可靠生产者的 MOCK 全局保留；请求这些 relation 时另有 per-query unsupported_relation 原因，不把空边集当成能力支持。

summary 的 exhaustive 只相对于 P2 query，不是 repository completeness。truncated 摘要合并 C1 截断、D 拒绝以及 P2 limit/cycle cut；不能只看摘要判断上游是否充分。未知 role、dangling node/source 与 C1 reports 仍可追溯。缺 mapping 不表示没有测试覆盖。

## Source、失败与验证

result binding 必须等于传入原 session reference，input repository/revision 必须匹配；跨 generation/side 参数拒绝。整个操作在 `session.read()` 中，进入和退出都验证。查询/退出异常不能返回成功结果。

所有已知输出 source paths 必须包含于 manifest fingerprint；越界观察整体拒绝，保留 summary/原因，不补造 hash。P2 trace 可能读取超出返回 evidence 的源文件，因此调用前还检查 graph/domain source footprint、公开 P1 files 与其中 symbols 的范围均被 fingerprint 覆盖。缺范围的 identity 保留 unresolved，不能生成 snippet。P2 已有 source evidence 内的 hash/anchors 与 B binding 原样保留。

只将 GraphQueryError、SymbolIndexError、OSError、UnicodeError 转为失败 report；参数错误、P2 contract mismatch 和 B SnapshotReadError 向上传播，不 broad catch，不在失败时重新构建或从 index 补 graph edge。

新增测试见 `tests/integration/test_graph_expansion.py`、`tests/unit/retrieval/test_expansion_policy.py`；使用真实 temporary Git、P1 index、P2 graph/trace 与 B binding，只有错误/漂移注入在公共边界进行。真实 revision-bound annotations 见 [P3-D annotations](../../evaluation/p3-d-expansion-annotations.md)，实际验收状态以 execution plan 为准。本模块不实现 E subgraph/snippet、G ranking、H selection/Pack 或 F refresh。
