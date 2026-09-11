# P3-E subgraph / snippet evidence gold — frozen

状态：**Frozen，2026-09-10**。Human approver：本任务用户，在审阅现有 smoke observation 后明确授权于 BFS provenance 修复后 Hook 通过时按 required / required negative / optional 边界冻结。整理者 Codex；修复后 trusted Hook 已通过（turn `01a08aa8-9f23-7422-a966-f6849d974bfc`，12/12、76.592 秒）。本文件冻结经用户批准的语义范围，不把 implementation-derived inventory 回填为 expected。实际结果与修复记录见 [E smoke / 最终验收](p3-e-materialization-smoke.md)。P3-D [frozen gold](p3-d-expansion-annotations.md) 及其 P2 source anchors/revision 均保持不变。

## Scope and validation inputs

使用原 D scope、输入、policy 和原始 live B sessions，D 返回 typed result 后调用 `materialize_context(result, target=session)`。Change 传完整 ChangeExpansionResult 和原 base/head sessions。不要从 runtime JSON 拼装假的 session，不运行 refresh 或全仓 build。已有 D JSON 可用于比对 provenance，但 C1/D 没有 production deserializer，不能作为新的 live query 结果直接加载。

Task repository/revision 继续引用 D gold：`OpenHarmony/arkui_ace_engine` / `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。既有 smoke 复用 C1/D artifacts，在 live B session 中执行 C1/D → E；未运行 preparation/rebuild。四类五个核心 cases 与 Button text 补充检查通过；真实审计发现的 origin 路径缺陷已修复，修复后 Hook 与真实 smoke 均通过。本次冻结只更新文档，不重跑查询或测试。

| 场景 | E 必需正向核验 | 必需保留 / 禁止推断 |
| --- | --- | --- |
| Button creation | D gold required CALL 的两端均解析到 scoped candidate；PatternArgument 单独 association，supporting evidence 闭包；entry/Model/FrameNode/Pattern 的可得 range/hash/snippet 对照原 source | 原 complete 保留；不能生成 FrameNode → Pattern CALL；可选 padding/theme helper 不自动升级 required |
| FontWeight property | Button native 与 stack；native 关键 CALL，stack UPDATE_PROPERTY/PropertyBinding 各自独立；宏/source evidence 与语义关系可区分；Text 不在本次 E 真实冻结范围 | native missing_update_binding；stack missing_entry_call/missing_property_writer；不造 writer/state/field，不把文本 snippet 当成恢复的 relation |
| Menu layout | MenuLayoutAlgorithm、MultiMenuLayoutAlgorithm、SubMenuLayoutAlgorithm 三个候选 identity/evidence 均保留；stage、operation bindings 与 type dependency 分开；所有可得 ranges 可核验 | 原 ambiguous、ambiguous_algorithm_identity、missing_create_binding；不选择 runtime/default algorithm，不生成 CREATE 或 Measure → Layout CALL |
| Overlay | 1 Show + 2 Close 的原三条 required paths、CALL 与 SHOW/CLOSE binding、source/provenance、managed type/animation 状态；shared endpoint/backing 可复用 | Show incomplete、Close ambiguous、ambiguous_paths、各路径 unsupported_manager_body、animation unresolved；不丢路径，不推断没有动画或同实例 |

每类都检查：

1. subgraph relation identity 集合是实际已接纳 C1/D 关系的并集；不会新增 visited nodes 之间的未观察边；端点缺原始 source 时必须明确 unresolved。
2. candidate ID scope 含 repository/revision/generation/side；每个 dependency/backing 引用均存在；C1 query / D seed / observation 字段路径能回查。
3. 手工抽查可得 semantic 与 text range：raw file SHA-256、P2 normalized-newline hash（若有）、精确坐标和 snippet slice 一致；overlap 共享 backing，不混合语义 provenance。
4. 不可得 source/range、原 uncertainty/unsupported/truncation 仍显式存在；降低 E bounds 时只改变 snippet 状态，不删除候选、不改 P2 status。
5. JSON round-trip 后 identities、relations、associations、依赖、原 negative evidence 与 snippet 坐标保持一致。没有 ranker 或 LLM。

真实 Change 双侧 E smoke 不在现行 P3-E 的必需真实验收清单内，本次不扩大 scope、不作为 Completed blocker；保留为未验证项，由 P3-I 综合验证时复用原 C2 frozen pair/diff。双侧隔离、错误 session/缺 base 和 round-trip 已由 temporary Git targeted tests 验证，但不冒充真实 Change E 验收。既有契约仍禁止拿 head 同行号替代 old 或跨侧合并相同 opaque identity。

## 指标范围与确认门槛

### Required / optional semantic gold

以下为用户批准的语义单位，沿用 D 已冻结的 required/optional 边界；不冻结本次所有 candidates、hash、generation 或 precise count。E 的无丢失/闭包契约适用于全部已接纳 observation，但“必须保留输入”不等于“每个输入都已人工标为 relevant”。本次不新增 relevance 分母。

| 场景 | Required | Optional / 未标注 |
| --- | --- | --- |
| Button creation | 原关键 CALL、PatternArgument 及成立所必需的 supporting identity/range/evidence；原 complete；association 非 edge；range/hash/origin/dependency 可回查 | D 已批准的 UpdatePadding/GetPadding helper 继续 optional；补充 TEXT 保持独立文本证据，不作为额外语义 identity；其他 helper 不自动升级 required 或 irrelevant |
| FontWeight native / stack | native 到精确 setter overload 的关键 CALL；stack 的 UPDATE_PROPERTY/PropertyBinding、FontWeight syntax token 和原支持证据；两个 overload 不合并；missing update/entry/writer 等原 negative evidence | 不影响任务视图成立的辅助 CALL 为 optional；同类 REFERENCE 的其他 occurrence 保持 unannotated，不自动变成 state-flow required；宏展开原文不能证明新 writer/state |
| Menu layout | 三个 algorithm candidates 全部 required，保持各自 identity/evidence 与 ambiguous/missing_create_binding；不得选择 default/runtime algorithm；可得 factory snippet 准确 | 不影响候选/证据成立的辅助 CALL 为 optional；其他同文件 REFERENCE 的相关性未逐项标注，不冻结完整 relation/range inventory |
| Overlay | 原 1 Show + 2 Close 路径、SHOW/CLOSE binding、关键 CALL、signature/managed-type supporting evidence；每条 gap/animation unresolved；Show/Close 配对不证明 runtime instance | 不影响路径成立的辅助 CALL 为 optional；manager 文件中其他 FrameNode reference occurrences 保持 unannotated，不自动构成 required 上下文；不补出 animation relation |
| 全部 cases 的 E 不变量 | scoped identity、依赖/端点 ID 闭包、精确 revision/side/range/hash、origin 回查、round-trip、重叠共享 backing；unknown/ambiguity/gap/unsupported/unresolved/truncation、source/range unavailable 全为 required negative evidence | snippet/backing/occurrence/candidate/overlap 总数和 snapshot generation 只是 observation；没有 scope 支持的 metadata 不补造；file/symbol endpoint 缺 observed range 可显式 unresolved |
| 专用 limits | E source bound 只改变 snippet 状态，不删除候选或重排；D node cut 的原 negative summary 保留 | 不要求任意小 materialization limit 仍提供全部源码；不冻结临时 limit 值为生产默认，不引入 token selection |

必要 supporting evidence 不可因为它表现为辅助 CALL/REFERENCE 而降为 optional。“endpoint 可解析”遵循既有 E spec：scoped candidate ID 闭包，允许上游无源码范围的显式 unresolved，不能声称 source metadata 完整。source drift/hash mismatch/错误 revision-side、缺 source/range 时必须拒绝或返回原显式限制，不补造 snippet。专用 limit 的截断/省略不能消除已有 ambiguity 或 negative summary。

E 仅记录 provenance/source/range 正确性、dependency closure、negative evidence 保留、无新增 relation 和 overlap backing 行为。不引入 ranking/relevance/selection 分母；recall、RCR、token cost 均 N/A。精确 candidate/backing 数是运行观察，不从 actual 升级为长期 expected。

本次按用户授权冻结后逐项对照既有 actual、修复后 Hook 与 E AC，未发现新缺口，P3-E Completed。运行时 JSON 的历史 `gold_status=proposed-not-human-frozen` 保持原样，不伪装为执行前已冻结；当前批准状态以本文件为准。P3-F 保持 Not Started，未运行 strict full。
