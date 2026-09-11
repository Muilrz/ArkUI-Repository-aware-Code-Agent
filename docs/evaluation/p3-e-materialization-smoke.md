# P3-E real subgraph / snippet smoke — 2026-09-10

**P3-E Completed。** BFS provenance 修复后 trusted Hook 12/12；用户授权的 Button creation、FontWeight property（Button native/stack）、Menu layout、Overlay 共 5 个核心 cases 与 Button 纯文本补充检查通过。2026-09-10 用户明确授权按语义边界冻结 [E evidence gold](p3-e-materialization-annotations.md)，冻结复核未发现新 AC 缺口。P3-F 保持 Not Started，没有进入 ranking、token selection 或 Context Pack。

## Hook 与发现的修复

最终验证读取 BFS provenance 修复后的 trusted Stop Hook `var/validation/latest.json` 和 `latest.log`，未手动调用 Hook/测试：

- turn `01a08aa8-9f23-7422-a966-f6849d974bfc`；targeted / passed，returncode 0。
- UTC `2026-09-10T09:42:51.874149+00:00` 至 `09:44:08.980104+00:00`。
- `tests.integration.test_context_materialization` 9 项、`tests.unit.context.test_materialization` 3 项：**12/12，76.592 秒，无 skip/failure**；含新增的所有 origin 路径逐段回查断言。

历史背景：最初 Hook 通过后开始真实 smoke，首轮四个 family 的独立 provenance 审计均发现同一问题：BFS distance origin 的 observation_path 少了 NodeVisit 的 `node` 字段，无法解析到实际 payload（`NodeVisit` 没有 `anchors`）。此前的 round-trip/ID 检查无法证明路径真正可回查，首轮不能计 PASS，也没有发布成功报告。

修复仅在 E：`materialization.py` 将该路径设为 `(*path, "node")`；已有 integration test 增加对所有 retrieval/expansion origin 路径的逐段解析和 payload 比较，不降低断言、不绕过真实行为。随后继续用户已授权的 smoke，所有 origin/query/seed 回查通过。

以上最终 Hook 在该修复与回归断言加入后执行，与修复后的真实 smoke 共同支持验收；不再引用修复前通过结果作为最终验证。本次冻结只修改文档，production/tests 未再变化，未重跑 smoke、测试或 strict full。

## Scope、source 与执行方式

Repository `OpenHarmony/arkui_ace_engine`；Task revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。目标 checkout 运行前后 clean、只读；路径通过 CLI 提供。复用已验证 C1/D manifests/index/graph/domain，无 preparation、refresh、rebuild 或新 semantic collection。

| Family | Generation | Fingerprint files | UTC start–finish |
| --- | --- | ---: | --- |
| Creation | c1-835a2e2db8caa6a7 | 30 | 09:36:22–09:37:09 |
| Property | d-property-79ccf692ad0b5722 | 22 | 09:36:22–09:37:24 |
| Layout | d-layout-a0c55875c9dc2243 | 21 | 09:36:22–09:36:56 |
| Overlay | d-overlay-9baef0b0e6d80904 | 10 | 09:36:22–09:37:14 |

`scripts/run_e_smoke.py` 复用 D source-anchored request 和原 public C1 → D 查询，在同一 B session 调用 E。D `ExpansionPolicy` 默认 depth=2 等配置不变。P2 fixtures 只提供既有 source anchors，不把 expected 当作生产查询结果。E trace 与同 session 独立 public P2 trace 完整 typed equality；E graph relations 同时对照实际 C1/D observations 与绑定 P2 graph/evidence。P2 implementation/frozen fixtures、D gold 无 diff。

所有源文件 SHA-256 与 binding/candidate hashes 对照。审计使用独立按行切片的 oracle 比较每条可得 snippet 和 backing，未调用 E 的 offset helper 自证；原 CRLF 保留。所有 scope/revision/side、candidate dependency、origin 字段路径/query/seed、raw 和 P2 normalized-newline hash、JSON typed round-trip 均通过。

## Actual inventory（不是新的 gold）

N/R/A/B/S 分别为 TaskSubgraph 的 nodes / relations / associations / bindings / supporting candidate 数。B 专指独立 `PropertyBinding` wrapper；UPDATE_PROPERTY、SHOW/CLOSE 等原 GraphEdge 保留在 R 中，**B=0 不表示没有 operation binding**。S 包含 fact/range/supporting_evidence；单列 evidence 是 `RelationEvidence` candidates 数。计数跨 case 不去重，不作为长期 expected。

| Case | Candidates | N/R/A/B/S | Evidence | Available ranges / backings | range_missing | 结果 |
| --- | ---: | --- | ---: | --- | ---: | --- |
| creation-button | 165 | 32/28/2/0/103 | 29 | 46/42 | 5 | PASS |
| property-button-native | 42 | 10/5/1/0/26 | 11 | 7/7 | 4 | PASS |
| property-button-stack | 228 | 8/5/1/1/213 | 108 | 99/97 | 3 | PASS |
| layout-menu | 77 | 14/10/0/0/53 | 32 | 15/11 | 9 | PASS |
| overlay-menu | 550 | 12/10/3/0/525 | 274 | 240/232 | 5 | PASS |

核心 cases 共 **407 个 available range snippets、389 个 backings**；22 对严格重叠范围正确共享 backing，26 个无 observed range 的候选显式 range_missing。没有 range_invalid、source_hash_mismatch、binding_mismatch 或 consistency_failure。没有悬空 dependency/provenance，新增无依据 relation 为 0。

relation inventory：Creation 26 CALL + 2 REFERENCE；Property native 5 CALL；Property stack 4 CALL + 1 UPDATE_PROPERTY；Menu 5 CALL + 3 REFERENCE + 1 DEFINE + 1 DECLARE；Overlay 3 CALL + SHOW + CLOSE + 2 DEFINE + 2 DECLARE + 1 REFERENCE。这是 observation，并非将所有辅助关系认定 relevant/required。

所有 relation endpoints 有 scoped node candidate 引用；**不宣称每个 endpoint 都有完整 source metadata**。Creation 的 1 个 file endpoint、Menu 的 2 个 file + 5 个 symbol endpoints、Overlay 的 2 个 file endpoints 没有已观察的 node source range，保留 unresolved/range_missing；Property 两例的关系端点均有范围。E 不为补 metadata 扩展 graph，也不捏造整文件/函数范围。Menu 三个 algorithm candidates 及各自原 evidence 完整保留；其他辅助 endpoint 的缺范围不能掩盖为全图完整。

Button 补充 TEXT query 使用原 C1 text scope，精确查询 `ButtonModelNG::CreateFrameNode`。结果为 169 candidates、48 available ranges、6 对 overlaps；两个 RangeFact 保留 identity=None，原语义 relation 集合仍为 28。该补充与原 symbol-only核心 case 分开记录，没有把文本命中变成 symbol seed 或修复 relation。

## 原语义、源码抽查与限制

| Case | 已确认的 observation | 保留的 negative evidence |
| --- | --- | --- |
| Button creation | 原 complete；CreationPath 与 PatternArgument 分别保留，两端/supporting evidence 可回查；CreateFrameNode 的 source snippet 覆盖 model/factory/Pattern argument | association 不是 FrameNode → Pattern CALL；不证明 runtime instance |
| FontWeight native | 原 entry → 精确 FrameNode* setter CALL 保留，native 与 stack identity 分开；现有 snippet 多为 token 精度 | incomplete、missing_update_binding；不能把 native macro 文本变成 UPDATE_PROPERTY |
| FontWeight stack | PropertyBinding(token=FontWeight)、UPDATE_PROPERTY 及 source/macro evidence 保留；不与 native 合并 | incomplete、missing_entry_call、missing_property_writer；没有 writer/state identity |
| Menu layout | MenuLayoutAlgorithm、SubMenuLayoutAlgorithm、MultiMenuLayoutAlgorithm 全部保留，原候选 source/evidence 不变 | ambiguous、ambiguous_algorithm_identity、missing_create_binding；没有凭 switch/default 新增 CREATE、MEASURE、LAYOUT 或选分支 |
| Overlay | 1 Show + 2 Close 的三条 OverlayPath、SHOW/CLOSE 与真实 CALL 独立保留，signature/managed type evidence 可回查 | Show incomplete、Close ambiguous；ambiguous_paths、每条 unsupported_manager_body、animation=unresolved；不推断无动画/同 runtime instance |

源码/完整 JSON 只读审阅与独立核验示例（Codex 执行，非人工 approval；source coordinates 只是本次 observation）：

- Button model：`button_model_ng.cpp` `[659:34,661:111)` 原文包含 `CreateFrameNode` 和 `MakeRefPtr<ButtonPattern>()`；raw file SHA-256 `5e423a593b059e7a80e343656d2c24a56c5f176ea181a2792e55dce2a3d70667`，包含原 CRLF。
- Menu factory：`menu_pattern.cpp` `[1447:38,1459:2)` 原文列出三种 return；raw SHA-256 `52204f9fa7c1c511956ea76f58470bf65ba0adcaedf21a93b7a61942216bfe23`。文本可见 default 不构成 runtime branch 选择证明。
- FontWeight：只读审阅 stack `[39–42]` 和 native `[885–888]` 以及 bridge `[317–323]` 的两种宏/调用形态；stack E 结果保留 `view_stack_processor.h` 的宏 source evidence。native 的 token-only snippet 没有虚构为完整函数体。
- Overlay：`overlay_manager.h` `[199:1,200:60)` 保留 HideMenu 的原声明/参数文本；raw SHA-256 `56bf541fdc0312e8634ced19bf871757054b656b6aee5fe3a9e466fb05686fb6`。声明证据不证明 manager body/animation 已解析。

Property stack/Overlay 产生较多同类 REFERENCE range，是保留原 supporting edges 的全部 occurrence，并非 E 新扩展或 relevant ranking。不能将全部 99/240 范围自动冻结为 required，也不能借 E 删除它们以伪装最终 selection。

每个核心 case 另执行 E `max_backing_characters=1`：所有 ranges 明确 materialization_limit，candidate/subgraph 完全不变；D `max_nodes=1` 后再 E，D truncated 与原 P2 negative summary 完整保留。INHERIT/OVERRIDE/MOCK unavailable 全保留。没有实现新的扩展 policy、ranking 或 token budget selection。

## P3-E AC 对照

| Acceptance Criterion | 当前结论 | 证据 / 限制 |
| --- | --- | --- |
| 所有 relation endpoints 可解析 | PASS：scoped ID 闭包；source metadata 可显式 unresolved | 全部 relation endpoints 引用存在；上述无 range endpoints 未伪造 metadata |
| 文本命中和语义 evidence 可区分 | PASS | Button 补充 TEXT 的两个 RangeFact identity=None，与 symbol/P2 evidence 分开 |
| snippet 来自声明 revision/range | PASS（本次 target revision） | 所有 407 core + 48 supplemental ranges 的独立 slice/hash/side 校验；supplemental 与 core 重复，不加成唯一语义证据数 |
| 缺 source/range 返回明确限制 | PASS（已有 Hook + 真实 range_missing） | Hook 覆盖缺 session/source 删除/漂移/范围错误；真实 26 range_missing，未主动破坏真实 checkout |
| 无悬空 candidate dependency | PASS | 全部 dependency/endpoint/backing IDs 校验与 constructor/round-trip |
| unknown/ambiguous/truncation 不消失 | PASS | 原 typed upstream/trace 保留、Menu/Overlay negative evidence、E source limit、D node cut |
| 序列化/反序列化身份关联保持 | PASS | 所有核心/补充输出 typed equality + canonical 再输出相等；provenance 修复后 Hook 回归断言通过 |
| 不依赖 ranker 或 LLM | PASS | 只调用公开 C1/D/P2/B 与 E source materializer；未执行 ranking/token selection |
| 必需 targeted tests | PASS（修复后） | turn `01a08aa8-9f23-7422-a966-f6849d974bfc`，12/12、76.592 秒、returncode 0 |
| 真实 smoke | PASS | 四 family、五核心 case + 同 Button text 补充，无 source/P2 frozen 变更 |
| 新 E gold / milestone 完成确认 | PASS | 用户明确授权冻结 [required/negative/optional gold](p3-e-materialization-annotations.md)；不冻结普通 case 精确数量，不把 inventory 自动变成 expected；E Completed |

现行 execution plan 的 E 真实验收要求是四类 Task subgraph/snippet 检查，没有要求真实 Change 双侧 E smoke；不临时扩大 E scope。真实 Change/base-head E smoke 保留未验证，留待 P3-I 综合验证，双侧行为已有 temporary Git Hook 覆盖。其他未验证项：真实源 drift/跨 revision 错误注入；Text FontWeight、其他组件/全仓 coverage；strict full；大规模 extraction 性能。这些不是本次 E 新增 Completion 门槛。ranking/relevance/recall、token budget/Context Pack 指标 N/A，不提前实现。全部 E AC、必需 targeted tests、已规划真实 smoke 与本次语义冻结复核满足，未发现新缺口。

## Reproduction and review

```powershell
py -3 scripts/run_e_smoke.py --family creation --repository-root <target> --artifacts var/evaluation/p3-c1 --output <new-creation-report>
py -3 scripts/run_e_smoke.py --family <property|layout|overlay> --repository-root <target> --artifacts var/evaluation/p3-d/<family> --output <new-family-report>
```

Runner 只读已存在 artifacts；缺失/漂移即失败，不 rebuild；输出拒绝覆盖。机器可读 actual 位于 `var/evaluation/p3-e/{creation,property,layout,overlay}.json`，schema `p3-e-smoke-observations-v1`、`gold_status=proposed-not-human-frozen`；包括源 anchors、B binding、审计结果、完整 ContextCandidateSet 与 source-limit/cut 摘要，属于计划消费的 runtime validation report，不提交 Git。

本 session 新增 runner/本报告，更新 E annotation、plan/spec 导航；production 仅修复 E origin 路径，tests 仅补充对应回查断言。没有改 P2 frozen semantics、D gold、后续 milestone 状态，没有导出 patch 或逐命令日志。review 使用当前 Git diff 与新增文件，不自动 commit。

最终冻结仅更新 E gold、本报告、active plan 与 spec 验收导航；上述 runtime observations 保持原样。P3-E 标记 Completed，P3 Phase 仍 In Progress，P3-F/G/H/I 保持 Not Started。
