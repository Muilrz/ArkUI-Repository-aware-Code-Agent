# P3-D real expansion smoke — 2026-09-10

**P3-D Completed。** trusted Stop Hook 12/12；四类 Task 共 11 个场景与原冻结 C2 Change expansion 检查通过。2026-09-10 用户审阅实际结果后批准语义 gold，已按 [最终 frozen annotations](p3-d-expansion-annotations.md) 收口。冻结复核未发现新 AC 缺口；recall/无关候选比例按用户明确边界继续 N/A，不作为 D Completion blocker。

## Trusted Stop Hook

读取 `var/validation/latest.json` 与 `latest.log`，不是手动调用 Hook：

- turn：`01a08923-61a0-7f31-829d-5229296b7dfc`。
- mode/classification/status：targeted / passed / passed；returncode 0。
- `2026-09-10T02:41:26.101335+00:00` 至 `02:42:54.607743+00:00`。
- `tests.integration.test_graph_expansion` 与 `tests.unit.retrieval.test_expansion_policy`：12/12，测试耗时 87.140 秒，无 skip/failure。
- 本轮未修改这些测试、fixture 或 P3-D production implementation；只新增真实验收入口和验收文档。没有手动运行测试命令、strict full 或其他 baseline。

收尾时再次读取最新 trusted Hook：turn `01a08947-4003-7423-9814-cbb3d7f110ba`，targeted/passed，returncode 0；`2026-09-10T03:06:06.451685+00:00` 至 `03:07:38.083299+00:00`，同两模块 **12/12、91.180 秒**。这次冻结仅改文档，implementation/tests 未变；未手动触发 Hook 或测试。

## Binding and preparation

用户本轮明确授权：Hook 全通过后执行现行 D 小范围真实 smoke，并先输出 actual 与冻结建议。所有目标 checkout 保持只读；结束时三个 checkout 均 clean。P2 implementation/spec/frozen fixtures、C1/C2 frozen expected 均无 diff。

Task repository 为 `OpenHarmony/arkui_ace_engine`，固定 revision `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。每个 snapshot 在 C1/D 查询前固定；同一 case 的 direct retrieval、D、原公共 P2 trace、重复检查及预算检查均复用同一个 B session，没有查询后扩大 inventory。

| Family | Generation | Fingerprint files | Preparation |
| --- | --- | ---: | --- |
| Creation | c1-835a2e2db8caa6a7 | 30 | 原 C1 manifest/index/graph/domain 原样复用 |
| Property | d-property-79ccf692ad0b5722 | 22 | 既有 P2 property selected collector → 公开 P1 index → P2 graph/framework/domain |
| Layout | d-layout-a0c55875c9dc2243 | 21 | 既有 P2 layout selected collector，同上 |
| Overlay | d-overlay-9baef0b0e6d80904 | 10 | 既有 P2 overlay selected collector，同上 |

新 preparation 使用 clangd 22.1.6、既有 C++17 fallback/include flags，无 compile database；实际工具版本、配置、source hashes、inventory 和 manifest hash 保存在各 preparation/manifest。Property collector 既有 scope 包含 Button/Text/Menu，本次查询为 D annotation 指定的 Button/Text native/stack 四场景。没有改变 collector 或增加全仓 preparation/refresh 能力。

Change 使用原 C2 snapshot：base `5422984fee409dc6f0a679ab5fc7ed38c19aae92` / generation `c2-base-37fed8342db3dc7a`（4 files），head `b29b394599624df784c0a7480a39537853d38821` / generation `c2-head-8aa01ae0b5392961`（5 files）。未 rebuild，绑定均 fresh。原 3-file、`--no-ext-diff --no-textconv --unified=0 --no-renames` diff SHA-256 为 `a0532aec1b6221e41ddd87638ac9b35c4f44c57faa94ef147f66b02db73dcfae`，执行前校验。

首次 Change 入口用了不同 context/rename 选项；虽查询成功，但不符合原冻结输入，因此 `change.json` **invalid/superseded，不计入验收或 gold**。已修正入口并增加 frozen diff hash 校验，重新执行的 `change-frozen.json` 是正式结果；没有修改 expected 或覆盖首轮观察。

## Actual results

下面 N/E/P/Q 是 D 接纳的 node identity / edge identity / path occurrences / query attempts，遵循 D spec 的保守计数；不是相关性分数，也不是普通 case 的 frozen 精确数量契约。Direct 列是本轮 C1 **symbol-only 参数候选**数，用于观察与扩展的明确对照，不代表 C1 全通道最优 recall，也不将 D 增加的所有关系认定为 relevant。

| Case | Direct | D N/E/P/Q | 原 P2 status / known gaps | 检查 |
| --- | ---: | --- | --- | --- |
| creation-button | 1 | 29/28/1/2 | complete | PASS |
| creation-text | 1 | 31/32/1/2 | complete | PASS |
| creation-menu | 1 | 13/11/1/2 | incomplete；missing_pattern_stage、unsupported_pattern_callback | PASS |
| property-button-native | 2 | 7/5/1/3 | incomplete；missing_update_binding | PASS |
| property-button-stack | 1 | 6/5/1/2 | incomplete；missing_entry_call、missing_property_writer | PASS |
| property-text-native | 2 | 6/4/1/3 | incomplete；missing_update_binding | PASS |
| property-text-stack | 1 | 6/5/1/2 | incomplete；missing_entry_call、missing_property_writer | PASS |
| layout-button | 1 | 12/11/0/2 | incomplete；missing_layout_binding | PASS |
| layout-text | 1 | 8/5/0/2 | incomplete；unsupported_factory_body | PASS |
| layout-menu | 1 | 13/10/0/2 | ambiguous；ambiguous_algorithm_identity、missing_create_binding | PASS |
| overlay-menu | 4 | 10/10/3/5 | Show incomplete / Close ambiguous；unsupported_manager_body | PASS |
| Change old | 1 unique scoped seed | 1/0/0/1 | 不自动选择 trace family | PASS |
| Change new | 2 unique scoped seeds | 2/0/0/2 | 不自动选择 trace family | PASS |

Task 查询 UTC 时间：Creation 02:50:11–02:51:46，Layout 02:52:23–02:54:05，Overlay 02:53:45–02:54:25，Property 02:54:23–02:56:32。每类 report passed=true，所有命令 returncode 0。

- 每个 Task case 的 D trace 与同 session、同有效 bounds 下独立调用公共 P2 trace 的完整 typed result 相等；同时符合原 P2 frozen status/gaps/stages。不是只比较 status 标签。
- Menu layout 的 `MenuLayoutAlgorithm`、`MultiMenuLayoutAlgorithm`、`SubMenuLayoutAlgorithm` 三个 candidates 全部保留；没有从 switch/default 选出 runtime algorithm。
- Overlay 保留 1 Show + 2 Close paths；每条路径保留 manager-body gap 与 animation=`unresolved`。没有推断无 animation 或同 runtime instance。
- D 中每条 GraphEdge 都匹配绑定 graph 的原 EdgeIdentity，原 evidence 是绑定 edge evidence 的子集；无新增无依据 edge。P2 trace-local associations 原样嵌套，不转为 CALL。
- 所有 Task 与 Change canonical 重复输出一致；seed/query provenance 和 source hashes 校验通过。额外读取已生成 JSON，独立递归核对所有 observation source file 都有绑定 hash、所有 scoped seeds 与 snapshot/side 一致，并重算 node/edge/path 总数，结果一致。
- INHERIT/OVERRIDE/MOCK unsupported/unavailable 保留。P1 原 caller-range/token 精度没有提高为 exact call-site；未证明的 runtime 行为不在通过声明内。
- Change 原 8 anchors 的 ordinal/side/range/status 精确符合冻结清单：4 mapped / 3 unresolved / 1 not_applicable；完整 C2 envelope 保留。同名/相同 opaque identity 的 base/head seeds 不合并。本 snapshot 无可用新 CALL/framework relation，因此 D 返回零边，**不解释为真实代码没有依赖**。

## Policy and actual budget checks

使用 `p3.expansion.v1`；所有完整配置和 policy 派生 query IDs 在 actual 中。Task outgoing、Change both，默认 relation 集合 CALL/CREATE/UPDATE_PROPERTY/MEASURE/LAYOUT/SHOW/CLOSE/TEST。四类 trace 均用显式且经 C1 查询的 source-anchored identity 参数；本次不是自然语言自动 planner 的真实质量验收。

| Limit | Effective baseline |
| --- | ---: |
| max_depth | 2 |
| max_nodes_per_seed / max_edges_per_seed | 100 / 200 |
| max_queries_per_seed / max_paths_per_seed | 8 / 32 |
| max_states_per_trace / max_layout_candidates | 1000 / 32 |
| max_queries / max_nodes / max_edges / max_paths | 64 / 500 / 1000 / 128 |
| P2 layout max_calls | 200 |

每个 Task case 另执行三种已有预算配置：max_queries=0、max_nodes=1、max_paths=0，其余同默认。前两种全部显式 truncated；path traces 在零 path 预算下整体省略、原 P2 ambiguity/gap summary 保留。Layout 没有 path occurrences，零 path 上限未触发截断，这是正确的 N/A 边界。所有输出均不越预算；恰好/超出 edge 和 per-seed 限额另由本轮已通过的 targeted tests 覆盖，没有自行增加额外真实 baseline。

Change 使用 max_queries=1 验证双侧共享限额：head 优先消费一次，old 明确 query cut；全局总尝试数为 1，旧侧的输入范围/provenance 仍在 envelope 中。默认 head 消费 2 次后，old 的有效剩余 max_queries=62、max_nodes=498，max_edges/max_paths 未消耗。

## Evidence categories and approved semantic gold

**真实源码 observation：** source_checks 在查询前核对原冻结源码行与当前文件 hash；另只读审阅 ButtonModelNG::CreateFrameNode 的 GetLayoutProperty/GetTheme/GetPadding/UpdatePadding、TextModelNG::CreateFrameNode 的 GetContext，以及 MenuPattern::CreateLayoutAlgorithm 的三个分支。源码文本只证明观察到相应表达式，不能自行升级成 semantic identity、trace relation 或 runtime 结论。

**已有人工作品 expected：** 原 P2 fixtures 的 source anchors/status/gaps/relations，以及 C2 冻结 diff/8-range 清单。它们保持原样，只用于比较。本轮 PASS 的 frozen conformance 指这些既有约束。

**Implementation-derived 数据：** actual JSON 内的 C1 candidates、P2 graph/trace、D node/edge counts、关联与候选集合；report 的 `proposed_additional_relations` 是返回关系 inventory，**不是已批准 gold**，也不表示所有项 relevant。不同 snapshot 的 identity 不混合。recall/无关候选比例按用户批准的 D 边界继续 N/A，不是 Completion blocker。

2026-09-10 用户已批准 required/optional 冻结方向，最终权威清单见 [frozen annotations](p3-d-expansion-annotations.md)。仅冻结关键任务语义事实及 required negative evidence；辅助 CALL 保持 optional，其余 inventory 不自动变为 expected。既有 P2 frozen expected 不变。

相较初始建议的调整：Menu 三 algorithm 明确全部 required；gap/ambiguity/unsupported/unresolved 统一明确为 required negative evidence；普通 case 的精确数量和 policy/limits 仅作 validation metadata；Change range-mapping 统计仅作 C2 前置事实，不重复冻结其 contract；不将当前零边数冻结为长期行为；recall/无关比例不再阻塞 D。专用 budget case 只冻结对应 stop/truncation 语义。没有新增正向 writer、callback 或其他不存在的 relation。

源码 observations 与 implementation-derived 原始报告不因批准而改写；runtime report 中历史 `gold_status=proposed-not-human-frozen` 是运行时状态，保留原样。当前人工批准状态由 frozen annotations 记录，不能覆盖原始报告伪装为执行前已冻结。

## AC conclusions and closure gate

| P3-D Acceptance Criterion | Conclusion | Evidence |
| --- | --- | --- |
| 同 snapshot/input/policy 可重复 | PASS | 全部 Task/Change canonical repeat |
| 每个扩展可追溯 seed/真实 relation | PASS | 公共 graph/evidence 比较、source hash 与独立 serialized audit |
| 跨组件扩展有事实依据 | PASS | 所有跨 scope endpoints 的 edges 均来自同绑定 graph；未用组件成员补边 |
| operation binding 不转 CALL | PASS | P2 完整 typed trace 相等，EdgeIdentity 保留 |
| 预算限制显式说明 | PASS | targeted 边界 + 实际 query/node/path cuts + Change 共享预算 |
| Menu 多 algorithm / Overlay 多 Close paths 保留 | PASS | 真实 3 algorithms / 2 Close paths，summary 截断透传 |
| 缺关系可返回独立证据但不宣称修复 P2 | PASS | Menu/Property/Text/Overlay 原 gaps/status 全保留 |
| 必需 targeted tests | PASS | trusted Hook 12/12 |
| 现行真实 smoke 执行与旧 frozen conformance | PASS | 11 Task cases + 原冻结 Change |
| 新 P3 语义 gold 人工冻结 | PASS | 用户明确批准；required/optional/negative/budget 边界已冻结，与已通过的实际证据对照，无新缺口 |
| recall / 无关候选比例 | N/A | 用户明确排除于 D Completion blocker，不进入 E/G evaluation |

全部 P3-D AC、必需 targeted tests、已规划真实验收和用户批准的语义冻结均满足，Status 改为 Completed。P3 Phase 仍 In Progress，E/F 仍 Not Started。strict full、额外 baseline 未运行；自然语言自动 planner 的真实质量、全仓覆盖、recall/ranking 不在本次验收结论内，不扩为 D 新门槛。

## Reproduction and files

新增 `scripts/run_d_smoke.py` 只承担上述显式验收；prepare/query 分开，输出拒绝覆盖。Creation query 的 `--artifacts` 指向原 C1 目录；其余三类先 prepare 再 query；change 使用原 C2 artifacts/checkouts。所有外部路径通过 CLI 参数提供，不写死到实现中。

```powershell
py -3 scripts/run_d_smoke.py query --family creation --repository-root <target> --artifacts <C1-artifacts> --output <new-creation-report>
py -3 scripts/run_d_smoke.py prepare --family <property|layout|overlay> --repository-root <target> --artifacts <new-family-artifacts>
py -3 scripts/run_d_smoke.py query --family <property|layout|overlay> --repository-root <target> --artifacts <family-artifacts> --output <new-family-report>
py -3 scripts/run_d_smoke.py change --repository-root <target> --checkouts-root <C2-checkouts> --artifacts <C2-artifacts> --output <new-change-report>
```

本轮 runtime evidence 位于 `var/evaluation/p3-d/`：creation/property/layout/overlay.json、正式 change-frozen.json，以及三个 family 的 preparation/manifest/P1/P2 可重建 artifacts。它们不提交 Git；旧 change.json 是已排除的首次观察。完整 JSON 是验收流程消费的机器报告，不导出 patch、code-freeze 或逐命令日志。

本轮源码变更仅新增验收 runner；文档新增本报告、更新 D annotation 状态及 active plan。production expansion、P2、tests 均未修改。当前 Git diff/untracked files 保留供 review，不自动 commit。

本次最终冻结只修改 annotation、evaluation 报告、active plan 与 spec 导航；未修改 production、runner、tests、P2 frozen expected，未重跑真实 smoke 或 strict full。
