# Changed Range → Symbol Mapping v1 (P3-C2)

本规范定义 C2 的 range 映射与 C1 integration，依赖 [input v1](input-v1.md)、[Knowledge Snapshot v1](knowledge-snapshot-v1.md) 和 [candidate retrieval v1](candidate-retrieval-v1.md)。不定义 P3-D expansion、ranking、token selection 或 Context Pack。

## API and output models

公共入口在 `arkui_agent.retrieval.change_mapping`：

```python
mapper = ChangedRangeMapper(bounds=MappingBounds())
mapping = mapper.map(change, base=base_session, head=head_session)
old_request = mapping.request(Side.OLD, channels=...)
envelope = mapper.retrieve(change, base=base_session, head=head_session,
                           retriever=candidate_retriever, channels=...)
```

`base` / `head` 均为必填 keyword，值可显式为 None。调用方通过 B 准备/绑定 session；C2 不构造、刷新 snapshot 或切换 checkout。不接受 Task、raw diff 或没有有效 Change 的 ParseResult；抛 `CandidateInputError`，调用方保留 A 的原始 rejected result。binary/combined 输入没有可信文件模型时，不能从原文猜文件和 ranges。

| Model | Contract |
| --- | --- |
| `ChangeRangeAnchor` | file/hunk/block ordinal、old/new side、该侧 path（可空）、change kind、LineRange（metadata-only 可空）、file 与 hunk provenance |
| `ExtentMatch` | 真实 P1 declaration/definition 的字段名、完整 SourceRange、`enclosing / intersecting / point_interior` |
| `MappedSymbol` | 绑定该侧 snapshot/revision/generation 的 `SymbolSeed` + 全部匹配 extent proofs |
| `RangeMapping` | anchor、可用 BindingReference、status、symbol candidates、typed diagnostics、ambiguity；没有 symbol 时仍保留 anchor |
| `ChangeMappingResult` | 完整 A Change、全部 RangeMappings 和 bounds；原始 diff/hunk body/revisions 因此不丢失 |
| `ChangeRetrievalResult` | mapping envelope + 各侧独立的可选 C1 result；缺侧 result 为 None，不冒充空成功 |

输出全部为 frozen dataclasses。canonical JSON 输出分别标识 `p3-c2-mapping-v1`、`p3-c2-retrieval-v1`，沿用 C1 的 type tags、POSIX paths 和稳定键编码；包含 status、typed reason、binding/freshness 和全部 provenance。C2 不新增动态反序列化或冻结最终 Context Pack schema。

## Changed blocks and range coordinates

`changed_anchors(Change)` 对每个 hunk 顺序扫描：连续 ADD/DELETE 构成一个 edit block，CONTEXT 分隔 blocks 且只推进两侧坐标，不产生 changed range；NO_NEWLINE 不消耗行，也不切开 block。每个 block 均输出 old/new 两个 anchor，保留该侧零长度 range。所有 hunk 和 blocks 按 A 顺序保留；不把 hunk context lines 当作修改，不跨 hunk 合并。

坐标统一为 A/P1 **1-based line/column、end exclusive**；A changed ranges 是整行区间 `[(start_line,1),(end_line,1))`。匹配计算使用完整 `(line,column)`，不是仅比较行号或把 P1 end 变成 inclusive。

Change 仍是调用方声明的变更输入。C2 验证绑定 revision/path/source 坐标与 P1 extent，不重新生成 Git diff 或验证每条 DiffLine 文本能否作为 patch 应用；source-reviewed real fixture 的 diff/base/head 正确性由独立验收保证。

非零 changed range：

- P1 extent 完整包含 changed interval → `enclosing`。
- 否则有严格非空交集 → `intersecting`。
- 仅边界相接不匹配；P1 零长度 extent 不构成范围证据。

零长度 changed range 表示该侧插入/删除边界点：**仅当 `extent.start < point < extent.end` 时**映射 `point_interior`。不吸附前一行、后一行、最近函数；在 extent 起点/终点均不映射。整行起点位于同一行函数名列之前时，也不能猜测属于该函数。EOF 或函数边界无法证明归属时保持 unresolved。

这只是已存 source extent 的几何关系，不是 changed-range 的语义影响结论。token-only declaration/definition 若与签名修改行相交，可产生 intersecting seed；函数体修改没有相交 token 时不能把该 token 扩成整个函数体。仅有 intersecting、没有 enclosing/point-interior 时保留 `intersection_only_no_enclosing_extent` diagnostic。不选择最内层/最外层、首个或最小范围；namespace/class/function 等所有合法已存 extents 都按 identity 保留，不宣称找到了唯一 enclosing function。

## Revision, side and file semantics

- old 只使用 Change.base_revision + FileChange.old_path；new 只使用 head_revision + new_path。
- 每侧 repository/revision 必须精确等于其 session identity。revision 缺失、session 缺失或不匹配分别诊断；不 resolve HEAD、branch，不从另一侧借源码/identity。
- 两个 session 在一次映射中同时受 B read guard 保护，退出时两侧都验证。任何 dirty/source/artifact drift 或已关闭 session 触发 B `SnapshotReadError`，整次映射不发布结果。普通缺侧可返回另一侧已证明结果并明确缺失；运行中的一致性失败不能包装成这种普通缺侧。
- ADD 的 old_path / DELETE 的 new_path 为 None，输出 `not_applicable` + `file_absent_on_side`，不查询另一侧路径。该侧 revision 缺失等诊断仍保留。
- rename 两个 path 分别查询各自 snapshot；即使 backend 在两侧返回同一个 opaque identity，scoped seeds 仍不同。C2 不证明 rename 前后语义身份相同。
- mode-only / rename-only / 空文件 add-delete 没有 changed block 时，每侧保留 file-only anchor；存在路径的一侧为 unresolved/no_edit_range，缺路径的一侧 not_applicable。不会因此映射整文件所有 symbols。
- 合法 Change 无法映射的每个 file/range anchor 都保留在 mapping envelope 中，属于输入范围候选，**不是 repository fact**；不能把未绑定的 path 说成存在的源码。部分不支持的语言/没有 index facts 同样不会丢弃原 Change。

## Public P1 read boundary and ambiguity

默认 `PublicSymbolRangeReader` 使用公开 `classify_repository_path` 检查现有 P1 C/C++ scanner 类型，再调用 `SymbolIndex.symbols_in_file(RepositoryFile)`。它不扫描目录、不访问 SQLite 表、不调用 clangd、不做全文搜索，也不按 filename/文本相似度或名称猜 SymbolIdentity。

该 path 必须属于绑定 manifest 的 **semantic_files**，仅有 text/test scope 或 source fingerprint 不足以证明 semantic coverage；不足时为 unresolved/semantic_scope_insufficient。source fingerprint 必须覆盖被映射 path。P1 同一 symbol 的 declaration/definition 只有位于该侧当前 path 的 range 才参与匹配，不用另一文件的同坐标 extent。

通过 B bound workspace 读取该文件，仅用于校验行数/列界；changed range 越界返回 unresolved/range_outside_bound_source，P1 extent 越界则排除该 extent 并诊断。允许 `(最后一行+1,1)` 作为半开 EOF 边界，空文件只有 `(1,1)` 边界。不从源码内容提取或猜测 symbol。文件内容读取成本按该文件大小计，不承诺流式或 token budget 上限；B guard 仍在退出时检查 source drift。

外部 adapter 可通过 `reader_factory` 提供相同只读协议；不支持的 backend 应抛 `MappingUnsupportedError`，显式 unsupported，不能以空 tuple 假装查询成功。默认未知语言为 unsupported；已支持文件但零 symbols / 没有足够 extents 为 unresolved/no_proven_symbol_extent，不推断仓库无此符号。

每个 file/side 查询最多一次并缓存；按 SymbolIdentity 排序。相同 identity 的 declaration 与 definition 证据合并为一个候选，不增加 ambiguity；不同 identity 一律保留。多个合法候选时 ambiguous=True，即使随后因 candidate budget 只保留一个，也不将它描述为唯一解析结果。截断时没有观察到第二个 identity 不等于证明唯一。

## Bounds and failure semantics

| MappingBounds | Default | Meaning |
| --- | ---: | --- |
| max_ranges | 512 | 按输入顺序的 paired anchors ordinal 上限，超过后不作 symbol 查询；仍保留全部 anchors 和 truncation 状态 |
| max_files_per_side | 128 | 各侧最多查询的不同文件数，失败/unsupported 的查询也占预算 |
| max_symbols_per_file | 10000 | identity 排序后最多参与 extent 匹配的 symbol 数 |
| max_candidates_per_range | 128 | 单 range 的不同 symbol 候选上限；先记录已知 ambiguity 再截断 |

bounds 必须是正整数，bool/零/负值/浮点拒绝。P1 public API 会 materialize 文件 symbols，故此处不承诺数据库内部扫描行数或单次调用内存上限。保留全部输入 anchors 不等于全部进行语义查询，元数据体积不属于 token selection。

每个 RangeMapping 状态：`mapped` 表示至少一个具有 extent 依据的 seed；`unresolved` 表示 revision/session/scope/extent 不足；`unsupported` 表示语言/backend 能力缺失；`not_applicable` 表示该侧文件不存在；`truncated` 表示 bounds 阻止完整映射；`failure` 表示 public P1 backend error。状态与 `MappingDiagnostic(reason, detail)` 分离；可映射不等于完整函数体/完整影响范围，须同时读取 diagnostics。

只捕获显式 `MappingUnsupportedError`、public `SymbolIndexError` 及文件读取 `OSError/UnicodeError` 并记录原错误信息，失败缓存避免反复执行；不吞掉编程异常，不用 broad exception 隐藏失败。B consistency error 始终向上传递并废弃整个操作结果。

## C1 integration

`mapping.request(Side, channels=...)` 只把该侧已证明 `SymbolSeed` 作为 C1 query selector，保留 file/hunk provenance 及 `file_index/hunk_index/block_index/side` 标签。多范围命中同一 symbol 时 C1 合并 query origins；完整 changed-range 与 extent proofs 仍在 mapping envelope，可通过这些 ordinal 追溯。C2 没有独立的按裸名字去重。

默认 channels 与 C1 SEED_CHANNELS 相同。`mapper.retrieve` 在 mapping 完成后，以各侧原 session 调用 C1；双侧外层 read guards 覆盖整个 retrieval 生命周期，防止 old retrieval 完成后 source 漂移却继续返回混合结果。没有可用侧 binding 时该侧 C1 result 为 None；无 seeds 时 C1 result 保持空/诊断，而 mapping envelope 仍包含 file/range 候选。

C1 仍独立执行其 source fingerprint 与 bounds 检查，例如 symbol 的其他文件 extent 未被 fingerprint 覆盖时，后续 channel 可以 unresolved；C2 不为此扩大 scope。没有跨 revision 合并，不做 changed symbol → dependency traversal；D 才负责 expansion。

## Tests and real acceptance boundary

新增 unit tests 覆盖 block/context/no-newline 坐标、半开范围、零长度边界、metadata-only rename 与 input/bounds 拒绝。temporary Git fixture 从 base clone 出 head 再提交，保留两个 clean checkouts、两个真实连接的 commit IDs 和独立 P3-B manifests；使用公共 P1 index 存储 synthetic extents，测试行移动、add/delete/rename、同 identity 跨侧隔离、多 symbol/nested ambiguity、token-only/macro 不可映射、decl/def、scope/unsupported/backend failure、bounds、C1 provenance/canonical output 和 source drift。

这些测试不证明真实 clangd 的 extent 完整性。按 execution plan，真实 ArkUI Change pair / hunks 尚需人工确认并显式授权 smoke，不能用两个相同 revisions 伪造验收，也不能复用 C1 单 revision Task smoke 冒充 C2。该项完成前 milestone 保持 In Progress；不运行 P3-D。
