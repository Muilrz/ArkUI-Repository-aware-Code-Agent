# P3 evaluation 输入与标注提纲

此文档只设计 P3 输入和人工标注流程，不是已冻结 expected dataset，也不报告检索结果。P3-A synthetic parser tests 的语法预期不替代真实 ArkUI evidence gold。

## Task input drafts

Task suite 的 revision 使用 [P2 baseline](p2-code-graph-baseline.md) 中的固定值。创建实际输入时须显式填入该 revision；不能自动从 HEAD 读取。以下 source 名称已对照既有 P2 fixtures，输入含义及新 P3 gold 仍待人工复核/冻结。

每项使用 repository=`OpenHarmony/arkui_ace_engine`、独立 source_id，并保留完整原文；方括号是 [input v1](../specs/task-change-context/input-v1.md) 的 hint 标签。

| Draft ID | Task text | P2 reference / review focus |
| --- | --- | --- |
| task-button-creation | `检查 [component:Button] [symbol:CreateButtonFrameNodeForCustom] 的创建依赖` | `tests/fixtures/creation_cases.py` Button；creation 输入 |
| task-text-creation | `检查 [component:Text] [symbol:createTextNode] 的创建依赖` | 同上 Text |
| task-menu-creation | `解释 [component:Menu] [symbol:CreateMenuFrameNode] 的 callback 创建路径` | 同上 Menu；已知 callback/Pattern 缺口不得被消除 |
| task-fontweight | `给 [component:Text] 的 [property:FontWeight] 补 [test_intent:UT]` | `tests/fixtures/property_cases.py`；macro/state flow 的文本与语义分开标注 |
| task-button-layout | `检查 [component:Button] 的 [action:measure/layout] 依赖` | `tests/fixtures/layout_cases.py` Button |
| task-text-layout | `检查 [component:Text] 的 [action:measure/layout] 入口` | 同上 Text；unsupported factory 单列 |
| task-menu-layout | `检查 [component:Menu] 的 [action:measure/layout] algorithm 选择` | 同上 Menu；多个 algorithm 候选 |
| task-overlay-show | `分析 [symbol:ViewAbstract::BindMenuWithItems] 的 [action:show] 路径` | `tests/fixtures/overlay_cases.py` REAL_SHOW |
| task-overlay-close | `分析 [symbol:ViewAbstract::CloseMenu] 与 [symbol:MenuPattern::HideMenu] 的 [action:close] 路径` | 同上 REAL_CLOSE；overload、多个 Close 路径和 animation unknown |

人工审查需确认输入是否对应所选 P2 case/anchor，不要求 parser 理解自由文本中的所有意图。不把 P2 expected 拷贝为 P3 的 required evidence。未知 component、缺 revision、模糊 overload、空 test mapping 等负例可补入独立 P3 suite。

## Reproducible Change input design

C2 人工选择可读取的真实 ArkUI base/head pair；当前尚未选择，因此本提纲不填写 revision 或伪造 patch/expected。选定后记录：

1. repository、完整 base/head commit IDs、取得输入的 source_id，以及原 unified diff 的 digest/生成选项。
2. base/head 各自 source anchors（path、侧、范围、原文/hash），确保 diff 可复现；不要用“同一 commit 充当两侧”构造虚假的修改验收。
3. 至少一个真实修改，以及 add/delete/rename 场景；包括可映射和无法证明 symbol 的范围。没有合适 revision pair 时保持未标注/待验收。
4. 明确 old/new range 使用 input v1 半开坐标；缺 base evidence 的 deletion 保留原 hunk，不能用 head 替代。

P3-A 的 `test_diff_parser.py` 具有独立可复现的 synthetic modify/add/delete/rename、多 hunk、invalid/unsupported 输入，仅验证 parsing，不查询真实仓库。

## Annotation fields and freeze gates

每个未来 case 应记录 input、repository/revisions、P2 case/fixture 引用（适用时）、source anchors、annotation status、annotator、rationale 和冻结时间。以下维度在对应 milestone 的查询之前人工独立冻结：

| Dimension | Annotation intent | First milestone |
| --- | --- | --- |
| required evidence | 任务必须包含的 symbol/range/typed relation/test 及依据 | C1/D |
| relevant optional evidence | 有帮助但非必需的 evidence | C1/D/G |
| known unavailable dependency | 上游缺事实/unsupported/missing mapping，不从 required denominator 偷删 | C1/D |
| forbidden inference | 不可伪造的 callback binding、CALL、runtime branch、animation 等 | C1/D |
| task subgraph / dependencies | endpoints、supporting evidence、dependency closure | E |
| relevance / selection | tier、budget 档位及预期缺失原因 | G/H |

未标注维度必须明确为 unannotated（不写 `expected: []`）；经人工确认的空集才是 frozen empty，非适用维度为 N/A。当前不创建带空 expected 的可执行 fixture，不从 actual 输出反填 gold。P3 evidence 的归一化/重叠去重单位在 C1/D 首批人工冻结时确定。

后续按 [P3 execution plan evaluation design](../exec-plans/active/P3-task-change-context.md#evaluation-design-and-acceptance-gates) 比较 direct retrieval/expansion、多个预算及失败分类；P3-A 不运行 retrieval、P2 baseline，也不改其 denominator 或 frozen expected。
