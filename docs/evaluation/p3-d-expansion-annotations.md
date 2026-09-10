# P3-D expansion evidence gold — frozen

状态：**Frozen，2026-09-10**。Human approver：本任务用户，审阅 [真实 smoke 与建议](p3-d-expansion-smoke.md) 后明确批准以下语义范围。整理者：Codex。这是用户批准后的冻结，不是从 implementation actual 自动反填 expected。

## Scope and authority

Task repository 为 `OpenHarmony/arkui_ace_engine`，revision 固定为 `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。P2 source anchors、identity 选择依据及 relation/trace 语义继续引用 `tests/fixtures/creation_cases.py`、`property_cases.py`、`layout_cases.py`、`overlay_cases.py` 的既有冻结项。本文件冻结它们在 P3-D 中的任务相关性与保留要求，不修改或另造 P2 contract。

Change 使用 [C2 frozen case](p3-c2-change-annotation-draft.md) 的 base `5422984fee409dc6f0a679ab5fc7ed38c19aae92` / head `b29b394599624df784c0a7480a39537853d38821`、原 selected files、原 diff options 及 SHA-256 `a0532aec1b6221e41ddd87638ac9b35c4f44c57faa94ef147f66b02db73dcfae`。仅采用正式 `change-frozen.json`；首次非冻结选项产生的 `change.json` 为 **invalid/superseded**，不纳入 gold 或验收。

source observation、人工 expected、implementation-derived 数据分别保留：源码行/hash 是观察；本文件与引用的 frozen fixtures 是人工批准的 expected；runtime candidates/graph/trace/counts 是 actual。不得将全部 actual 字段、CALL 或精确输出大小升级为长期 required 契约。本次 generation/source hashes 见 smoke 报告；单个 generation 不属于长期算法行为。

## Required positive and negative evidence

| Case / P2 reference | Required semantic evidence | Required negative evidence / forbidden inference |
| --- | --- | --- |
| creation-button / creation-text | frozen entry → Model::CreateFrameNode → FrameNode::CreateFrameNode 的关键 CALL；可靠 PatternArgument 及 supporting/source evidence；原 complete | association 不转为 FrameNode → Pattern CALL，不证明同 runtime instance |
| creation-menu | frozen entry → MenuModelNG::CreateFrameNode → FrameNode::GetOrCreateFrameNode 的关键 CALL及 provenance | 原 incomplete；missing_pattern_stage、unsupported_pattern_callback；不得以 constructor/helper CALL 恢复 callback/Pattern binding |
| property-button-native / property-text-native | frozen entry → 精确 native setter overload 的关键 CALL | 原 incomplete、missing_update_binding；不从宏文本补 binding，不与 stack overload 合并 |
| property-button-stack / property-text-stack | setter → LayoutProperty 的 UPDATE_PROPERTY binding 及 supporting/source evidence | 原 incomplete、missing_entry_call、missing_property_writer；writer 不可得是 required negative evidence，不造 writer/state identity |
| layout-button | 已知 Pattern/factory、CREATE、MEASURE 与独立 LayoutProperty dependency；semantic parent/type/source evidence | missing_layout_binding；不生成 Measure → Layout CALL |
| layout-text | 已知 Pattern/factory 与 supporting evidence | unsupported_factory_body、原 incomplete；不从类名补 CREATE |
| layout-menu | 已知 Pattern/factory；**MenuLayoutAlgorithm、MultiMenuLayoutAlgorithm、SubMenuLayoutAlgorithm 全部为 required candidates**，保留各自 identity/evidence | 原 ambiguous、ambiguous_algorithm_identity、missing_create_binding；不选择 default/runtime algorithm或生成确定 CREATE |
| overlay-show-menu / overlay-close-menu | REAL_SHOW 与 REAL_CLOSE 的三条已核验路径（1 Show、2 Close）；真实 CALL、SHOW/CLOSE bindings、supporting/source evidence | Show incomplete、Close ambiguous；ambiguous_paths、每条路径的 unsupported_manager_body、animation=unresolved；不得丢路径、推断无动画或同 runtime instance |
| Change expansion | 消费 C2 证明的 revision-side scoped seeds；保留 seed/query/extent provenance 引用、base/head identity 隔离与上游诊断；相同 opaque identity 不跨侧合并 | 缺侧/不可映射/unsupported/unresolved 不改成成功空事实；当前 snapshot 无可扩展 relation 不表示代码无依赖，也不得从另一侧补边 |

可靠 writer evidence 若由输入 P2 trace 实际提供，须保留其 identity/source/support；本次真实 native/stack 没有确认可得 writer，不冻结不存在的正向 writer。既有 P2 synthetic writer/association contract 不变，不扩大 D scope。

**所有 case 的 gap、ambiguity、unsupported、unresolved 均为 required negative evidence。** INHERIT/OVERRIDE unavailable、当前无可靠生产者的 MOCK、未知 role、dangling/source limitation、上游截断均不得静默消失。独立 evidence 可以召回，但不能改写原 trace 状态或以新关系把负向证据“修好”。

普通预算足够的 case 保留上述语义集合；专门 budget case 按下一节验证显式省略及 negative summary，不要求任意小限额下仍返回全部正向事实。

## Optional and unannotated evidence

不影响主链/association 成立的辅助 CALL 保持 optional，包括已审阅的：

- ButtonModelNG::CreateFrameNode → LayoutProperty::UpdatePadding。
- ButtonModelNG::CreateFrameNode → ButtonTheme::GetPadding。
- TextModelNG::CreateFrameNode → UINode::GetContext。

使用实际 scoped identity/source evidence，不由展示名创建 identity。其余 helper、implicit operator、constructor CALL 的相关性未逐项标注，不自动升级 required，也不当作已知 irrelevant。主链/association 必需的 supporting evidence 不属于可随意省略的辅助 CALL。

## Dedicated budget/truncation gold

`p3.expansion.v1`、depth=2 与各 limit 是**本次 validation policy/input metadata**。普通 case 不冻结偶然的 node/edge/query/path 精确总数、全部辅助 CALL 或 traversal 发现顺序。相同 input/snapshot/policy 仍须 deterministic；不借 gold 固化内部实现。

| Dedicated input | Required outcome |
| --- | --- |
| max_queries=0 | 明确 query limit、truncated；不声称已执行完整检索 |
| max_nodes=1 的已验证 Task cases | 不越预算；超出观察整体省略并记录 node limit，保留已观察的原 P2 status/gaps/ambiguity summary |
| max_paths=0 的 path trace cases | 明确 path cut；省略路径但保留原 trace summary/negative evidence，不改判唯一完整 |
| max_paths=0 的 Layout cases | Layout 无 path occurrences，该限额本身不触发 path truncation |
| Change max_queries=1 | head 优先、双侧共享总限额；old 明确 query cut，保留 scoped inputs/provenance/诊断；不分别给两侧一份全局预算 |
| targeted tests 的恰好/超限及 per-seed 边界 | 恰好达到上限不凭计数本身宣称截断；实际阻止继续查询/接纳时有 stop reason，不越预算，原 ambiguity/gap 不改判 complete |

专用输入及对照见 `tests/integration/test_graph_expansion.py`、`tests/unit/retrieval/test_expansion_policy.py` 与 smoke budget probes；不增加昂贵 baseline。

## Change boundary and completion

C2 固定 case 的 4 mapped / 3 unresolved / 1 not_applicable 只是**前置验收事实**，不在 D 重复冻结 range-mapping contract；当前 old 1/new 2 去重 seed 数、零边总数也不是普通 case 的长期精确数量契约。D required 聚焦正确消费 seeds、provenance、revision-side 隔离与 expansion/shared-budget 行为。

recall 和无关候选比例保持 **N/A，非 P3-D Completion blocker**；不引入 E candidate-set 或 G ranking/relevance evaluation，不以 actual 自动建立相关性分母。

trusted targeted tests、11 个真实 Task cases、正式 frozen Change 与 source/provenance/budget 审计已覆盖上述要求。用户已审阅 actual 并批准此语义范围，冻结复核未发现新 AC 缺口；本次只更新文档，不新增测试、不重跑 smoke/strict full。P3-D Completed；P3 Phase 仍 In Progress，不进入后续 milestone。
