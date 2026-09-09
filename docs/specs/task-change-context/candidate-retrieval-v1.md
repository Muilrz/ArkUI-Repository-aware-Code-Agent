# Multi-channel Candidate Retrieval v1 (P3-C1)

本规范定义 C1 当前可调用的候选读取行为。输入沿用 [input v1](input-v1.md)，知识绑定沿用 [Knowledge Snapshot v1](knowledge-snapshot-v1.md)。候选是已有事实的临时聚合，E 才收敛候选全集，H 才冻结 Context Pack；此处没有 changed-range mapping、graph expansion、ranking 或 token selection。

## Public entry points and typed data

从 `arkui_agent.retrieval.planning` 导入 `task_request` / `change_request`，从 `arkui_agent.retrieval.service` 导入 `CandidateRetriever`，从 `arkui_agent.retrieval.candidates` 导入以下类型。P1 原有 package exports 保持兼容。

- `RetrievalRequest(input, side, queries, diagnostics)` 保留完整 typed Task/Change。
- `CandidateQuery(channel, selector, origins)` 使用 `Channel`、`NameSelector` 或显式 `SymbolSeed` / `GraphSeed`，每条 query 至少一个 `QueryOrigin`（A provenance + label）。
- `SymbolSeed` / `GraphSeed` 必须携带已有 opaque identity、完整 `SnapshotIdentity` 和 `EvidenceSide`，没有按名称构造 identity 的入口。
- `RetrievalBounds` 使用正整数限额，拒绝 bool、零、负值和非整数。
- `Candidate` 携带 scoped candidate ID、snapshot、side、typed observations、全部命中 query/provenance、涉及文件的 snapshot hashes、ambiguity 与 unresolved。
- `QueryReport` 保留状态、返回 candidate IDs、diagnostics、facade calls、observed records、ambiguity/unresolved/truncated 独立标志。
- `CandidateRetrievalResult` 保留完整 `BindingReference`（含 manifest artifact generations、scope 和 freshness）、request、bounds、candidates、reports、整体 diagnostics。

`CandidateRetriever(bounds=...).retrieve(request, session)` 接受调用方已绑定的 P3-B `SnapshotSession`。`adapter_factory` 是薄 adapter 的依赖注入入口，默认使用 `PublicChannelAdapter`；替换实现必须遵守同一知识来源和只读契约。

## Query planning and revision boundary

Task 只允许 `target`，Change 只允许 `old` / `new`。Task target revision 或 Change 所选侧 revision 必须与 session 的 repository 和完整 Git revision **精确一致**；缺失、branch 名称未解析、repository/revision 不一致均返回 `unresolved`，不调用 retrieval，不隐式 resolve HEAD。Change 另一侧不会被拿来替代所选侧。每个显式 seed 的 snapshot（含 generation）和 side 也必须一致，否则该 query 零次调用、返回 `unresolved`。

Task planner 是有限映射：非空原文行成为 literal text queries；每个现有 hint 的原值成为 text query；component/symbol/property hint 可进入所选名称通道，包含 `::` 时使用 qualified-name lookup。action/test-intent 不生成 symbol query。component hint 可以查询现有 domain component 的准确 display name/key。保留原文、hint kind、来源和原始 span；不新增自然语言 parser，不拆解 overload signature，不推断同义词、路径归属、symbol identity 或 runtime branch。

默认 Task channels 包含 text、symbol/declaration/definition、references/calls、tests、graph node 和 domain lookup/component。直接 incoming/outgoing 等通道可显式选择；不自动把结果再作为新 seed。`change_request` 只使用调用方提供的已有 scoped seeds，默认 new side；无 seeds 明确 `change_seeds_unresolved:C2_required`。显式 `RetrievalRequest` 可以选择适用的任意通道。

同一 channel + selector 的 query 只执行一次，合并并排序全部 origins；query 排序由 channel 和 selector 的 canonical structural encoding 决定，与调用方顺序无关。

## Channels and public providers

| Channel | Public provider / evidence | Completeness and limits |
| --- | --- | --- |
| text | `RepositoryTextSearch.search(TextSearchQuery)`；typed range、matched text、原行文本 | literal、case-sensitive；仅逐个读取 manifest `scope.text_files`；没有全文 snippet materialization，也不把文本测试命中变成语义 test mapping |
| symbol | `DefinitionDeclarationRetriever.candidates_by_name / candidates_by_qualified_name`；显式 seed 经 `SymbolIndex.get` 核实 | 所有 overload 按 identity 保留到 bounds；不调用 resolve_unique、不默认选首项 |
| declaration / definition | 同 facade 的 `declaration / definition` | 已知 symbol 缺 range 为 unresolved |
| reference | `ReferenceCallRetriever.references` | 保留 reference identity/range；已知 seed 无记录为 empty |
| callers / callees | `ReferenceCallRetriever.callers / callees` | 仅已存 direct calls；保留 dangling endpoints；range 是 caller definition/declaration，**不是 call-site** |
| test_fixtures / test_cases | `SymbolIndex.find_test_fixtures / find_test_cases` | 名称找到的 tests 与 tested-symbol mapping 分离 |
| tests_for_fixture | `get_test_fixture / test_cases_for_fixture` | 精确 fixture seed，未知 seed unresolved |
| tests_for_symbol / test_mapping | `test_cases_for_symbol / tested_symbol_mappings_for_symbol` | 保留 test identity 和 references；空 mapping 不推断无测试覆盖 |
| graph_node / graph_incoming / graph_outgoing | `GraphSnapshot.query()` 的 `node / incoming_edges / outgoing_edges` | 仅显式 seed 的直接查询，不调用 neighbors/traverse/trace；保留 P2 typed edge/evidence，以及 unavailable_relations，即使发生截断 |
| domain_lookup / domain_members / domain_component | `DomainMap.lookup / members / components` | 仅已存 role/component facts，保留 unknown/ambiguous、rule evidence；members 使用已存在 component identity |
| inherit / override / mock | 当前无可靠 production relation provider | 明确 unsupported、零调用；不返回假成功空集 |

text facade 延迟到 text query 内创建；rg 缺失只使 text query failure，不影响可用 symbol 通道。C1 不直接访问 SQLite 表、不拼 rg 命令、不启动 clangd、不准备或刷新 artifacts。

直接 graph edge 的两个端点通过公共 `node` 读取验证（也计入 call budget）。缺失或只有 symbol identity、无 fingerprint 内源码的端点使该 edge candidate 保持 unresolved；不会因 edge 自身具有 caller range 就宣称双端都已解析。端点不会自动成为额外候选，也不继续查询其邻接关系。

## Snapshot/source invariants

全部通道在**一次** `session.read()` 内执行，复用同一个 index/graph/domain/workspace view。后续请求可以复用同一 session；不会逐通道寻找最新 generation。

只有 P1/P2 公共 API 返回的 facts 才能成为 observations。任何 observation 涉及的已知源文件必须包含在绑定 source fingerprint 中，否则排除该 observation 并标记 unresolved。此检查包含 call 内嵌 caller/callee 源码、test body、domain evidence 和 graph anchors；名字解析出的 symbol 在成为后续 seed 前也检查源文件。没有源范围的上游 dangling/unknown facts 可保留，但必须标记 unresolved，不制造范围/hash。每个 candidate 同时保留 query provenance 和 artifact/snapshot provenance；缺 source 与缺 query provenance 不能混同。

开始和退出读取时由 B 验证 workspace 与 artifact observation。关闭 session、artifact replacement、dirty/source drift 等触发 `SnapshotReadError`，整个 retrieval 不返回候选结果，不把 drift 包装成某个通道 empty。异常附带 B typed freshness diagnostics。验证沿用 B 的前后采样限制，不实现 watcher，不保证发现两次采样之间变化后又还原的内容。允许的 degraded read 由 B 显式 binding policy 决定；C1 原样保留 freshness/limitations，不提升为 fresh。

## Identity and coordinate semantics

candidate ID 为 snapshot identity + side + fact key 的稳定 SHA-256。不同 repository/revision/generation/side 永不合并，同名不同 identity 永不合并。

fact key 分别使用 symbol identity、range role + 可选 identity + 精确 SourceRange、graph node identity、test kind + identity、test mapping 双端 identity、domain identity。P1 direct call 与 P2 CALL edge 统一使用 source/target NodeIdentity + relation type；同一关系合并 observations/provenance，保留所有原始 evidence。symbol payload 和 graph node payload 属于不同事实视图，不强行相互覆盖。其他类型不做语义等价推断，不按裸名称或重叠范围合并。

范围直接复用 P1 `SourceRange`：line/column 均 **1-based**，column 为 Unicode code point，end **exclusive**；side 在 candidate/request 上明确。C1 不转换 A 的 diff hunk 坐标，也不做跨侧 range mapping。文本内容为 P1 已返回的匹配与行文本；没有 snippet 扩展或源码改写。

## Bounds and deterministic completeness

| Bound | Default | Meaning |
| --- | ---: | --- |
| max_queries | 64 | canonical 去重后实际执行 query 数；省略数量记录在整体 diagnostic |
| max_calls_per_channel | 64 | 一个 retrieval 内该 channel 的公共 facade 调用总数，包含名称/seed lookup |
| max_name_candidates | 20 | 一次名称解析进入后续通道的 symbol 数；截断前记录 overload ambiguity |
| max_results_per_query | 100 | 单 query 不同 fact keys 的输出上限 |
| max_records_per_query | 500 | 单 query offer 检查预算；第一个超界记录只检测截断，不加入结果 |
| max_candidates_per_channel | 200 | 所有该 channel queries 合计的不同候选上限 |
| max_candidates | 500 | 最终 candidate 数量上限，canonical ID 前缀保留，受影响 report 同步标记截断 |
| max_query_characters | 4096 | 超长 selector 整条跳过，truncated、零调用，不静默裁短 query |

计数达到上限本身不证明 truncated：只有还有记录/调用需要执行时才标记；query 数超界可直接计数。一次 text facade 请求最多返回 per-query result limit + 1 个命中，用于判断截断；文件迭代也受 channel calls 约束。

这些是 C1 orchestration 的调用数、fanout、检查和输出边界；P1 的部分公共 API 先 materialize/sort 所有匹配，text 的 limit 也是 public facade 后处理。C1 **不承诺** backend 扫描行数、单次调用内存、总耗时的严格上限，不为实现这些保证绕过公共 API。query/input JSON 自身也不受 token budget 限制。candidate limit 不是最终 context selection，不表述为全仓检索完整性或最终上下文充分性。

## Status, diagnostics and serialization

`empty`：有效可用查询未得到记录。`unsupported`：通道/selector 形式不支持。`failure`：公共 backend/facade 错误。`unresolved`：缺 revision/seed/source/domain role 或已知上游 relation 不可得。`truncated`：预算阻止继续处理。`ok`：已执行查询在其 scope 内返回候选且无以上限制。

已知 symbol 的零 references/test mapping 为 empty；未找到 reference 查询的 symbol seed 为 unresolved；纯名称 symbol 搜索零命中为 empty。domain component 名称零命中为 empty，精确 domain lookup 缺 mapping 为 unresolved。multi-line 显式 selector unsupported；原 Task 多行由 planner 拆为独立 literal queries。

公共 provider 错误原类型名/消息进入 query diagnostics；该失败 query 不发布部分 facts，但其他通道可以继续。只捕获已定义 public errors，不吞掉编程错误。状态和原因分开；query report 的 ambiguity/unresolved/truncated 标志允许并存。整体摘要优先级为 failure > truncated > unresolved > unsupported > ok/empty；不能只看摘要推断每个通道状态。

`to_json()` 输出 `p3-c1-candidates-v1` envelope，包含整体 status 以及全部 dataclass 字段，typed observations 使用 type tag，Enum 使用 value，路径使用 POSIX，UTF-8/Unicode 不丢失，键和集合稳定排序。相同绑定、输入和预算在 query 顺序变化下输出相同 JSON。只提供可审计 canonical 输出；C1 不提供动态类型加载或最终 Pack deserializer，也不承诺跨未来 candidate schema 的 ID 稳定性。

## Verification and evaluation

`test_candidate_planning.py` 检验输入 provenance/有限 planning；`test_candidate_retrieval.py` 使用 temporary Git/C++ 源码、真实 P1 index/facades/rg 和 P2 projection/domain 预构建 artifacts，覆盖 overload、去重、共同 Task/Change 通道、空/失败/不支持/未解析/截断、直接 graph/domain/test、serialization 和 source/artifact drift。synthetic facts 在查询前独立编写，不从 actual 回填预期；不代表 clangd extraction 或 ArkUI 全仓质量。

首批真实 case 见 [C1 annotation draft](../../evaluation/p3-c1-annotation-draft.md)。人工冻结与显式真实 smoke 的验收状态以 execution plan 为准，不由 synthetic tests 替代。
