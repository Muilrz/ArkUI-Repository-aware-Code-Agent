# P3-C1 frozen direct candidate annotations

状态：**Frozen expected**（Button / Text / Menu 三组）；P2 expected 文件保持不变。human approver：本任务用户（2026-09-09 明确确认）；frozen_at：`2026-09-09T08:42:35+00:00`（落实冻结时间）；固定 revision：`0096f5bd943ed1f7fa56883aed0e2379f13c2885`。

## Source-reviewed and human-approved expected

下表三个 creation case 的 expected 已经用户人工审阅并明确接受；其余 P3 case 继续 unannotated。源码审阅者为 Codex，人工审批者为本任务用户。除用户指定的 preparation scope 澄清外，冻结时不改变此前 proposed expected。机器可执行对应项见 `tests/fixtures/c1_cases.py`。

已只读核验外部 checkout 的 HEAD 为 `0096f5bd943ed1f7fa56883aed0e2379f13c2885`，`git status --porcelain` 为空。以下预期来自现有 source anchors 和实际源码阅读，没有运行 C1 获取 actual，也没有读取 actual 来填 gold。

统一 namespace 为 `OHOS::Ace::NG`，Text 入口另加 `ViewModel`。保持下文三个 Task 原文。

| Case | Required evidence（逐项核验，不从 actual 选择答案） | Relevant optional evidence（缺失单独报告，不计 required 失败） |
| --- | --- | --- |
| c1-button-creation | `CreateButtonFrameNodeForCustom` 的独立 symbol；definition 覆盖入口文件 970 行；text 命中该行函数名称；direct CALL 从该入口到 `ButtonModelNG::CreateFrameNode`，依据 972 行调用 | 入口的其他准确文本/reference occurrences；CALL payload 中 model 的 definition 对应 model 文件 659 行；现有 Button domain component evidence |
| c1-text-creation | `ViewModel::createTextNode` 的独立 symbol；definition 覆盖入口文件 113 行；text 命中该行函数名称；direct CALL 从该入口到 `TextModelNG::CreateFrameNode`，依据 115 行调用 | 入口的其他准确文本/reference occurrences；CALL payload 中 model 的 definition 对应 model 文件 90 行；现有 Text domain component evidence |
| c1-menu-creation | `CreateMenuFrameNode` 的独立 symbol；definition 覆盖入口文件 445 行；text 命中该行函数名称；direct CALL 从该入口到 `MenuModelNG::CreateFrameNode`，依据 447 行调用 | 入口的其他准确文本/reference occurrences；CALL payload 中 model 的 definition 对应 model 文件 25 行；现有 Menu domain component evidence |

Required 共 **12 个 evidence checks**，每个 case 四项。这些是不同事实视图的 conformance checks，不当作 12 个互不重叠的语义相关性单位计算 recall。opaque SymbolIdentity 在执行前由 P1 对上述精确 qualified name + file + source anchor 建立对应；若不唯一，报告 setup ambiguity，不选择第一项或修改 gold。CALL 精度仅为 caller definition/declaration，不能把源代码审阅的调用行号冒充 P1 call-site range。

所有可得 overload 必须按 identity 保留；若触发名称 budget 则记录 ambiguity + truncation，不能因只保留一项就宣称唯一。三个指定入口在对应 selected-file preparation 中预期唯一，不能据此宣称全仓同名唯一。graph/source provenance 中所有 identity 都须属于绑定的 snapshot/generation，source paths/ranges/hash 必须可回溯；顺序反转不得改变 canonical output。

### Expected unknown / unsupported and forbidden inference

- 显式 `inherit`、`override`、`mock` queries 均预期 `unsupported`，不是成功空集。
- direct graph incoming/outgoing 预期保留 P2 `unavailable_relations` 中的 INHERIT/OVERRIDE；空 edge 集与 unavailable 诊断可同时存在。
- 本 preparation 不索引测试，test scope 明确为空；已知入口的 test mapping 预期为 scope 内 empty，不代表 ArkUI 无测试。后续若改变 test preparation，须先复核这条 expected。
- Menu callback 的 `patternCreator → InnerMenuPattern` binding 仍不可得；不应出现伪造的 `FrameNode::GetOrCreateFrameNode → InnerMenuPattern` CALL。不得替换成 MenuPattern 或把文本命中说成创建链已完整。
- 不要求 C1 返回两跳 model → FrameNode / Pattern chain；只检查输入入口的直接候选。未查询到多跳依赖不算 C1 漏检。Button/Text pattern 构造行只是本次源码审阅背景，不据此从 query hint 生成 relation。
- 所有返回 CALL/graph relations 须逐条对应绑定的 P1/P2 public read facts；额外源码无法证明的 relation 单独报告，不能只检查上述 Menu 禁止边就宣称零伪造。
- 所有 cap diagnostics 原样报告。首次 smoke 的 required 缺失如果由 truncation 导致，验收仍不通过；不得通过扩大 budget 后覆盖第一次结果或静默调整冻结参数。

### Frozen smoke configuration

使用 C1 `TASK_CHANNELS` 加显式 `GRAPH_INCOMING`、`GRAPH_OUTGOING`、`INHERIT`、`OVERRIDE`、`MOCK`，保持同一 Task planner，不把 expected 当 query result。每个 case 使用同一 P3-B bound session。

固定 bounds：`max_queries=64`、`max_calls_per_channel=512`、`max_name_candidates=20`、`max_results_per_query=200`、`max_records_per_query=1000`、`max_candidates_per_channel=1000`、`max_candidates=2000`、`max_query_characters=4096`。这是输出/调用预算，不是 backend 成本承诺。

准备 scope 沿用 P2 creation 的 selected-files 设计：三个 entry `.cpp`、各组件 model `.cpp` / model `.h` / pattern `.h` 和 `frame_node.h`，以及查询前按 `p2-creation-source-closure-v1` 确定的 source provenance 文件；测试文件集合为空。此规则在 preparation 阶段对固定三个 entry/model 的公共 P1 collector 输出取所有 symbol declaration/definition 与 references 文件的去重有序并集，加上上述 13 个固定源文件；不做递归语义扩展。最终 selected-files inventory 和 fingerprint 必须写入 manifest，完成发布并绑定后才允许第一条 C1 query。禁止根据 actual retrieval 的 provenance 动态扩充 inventory；范围外事实按 C1 contract 排除并诊断，不能修改 scope 后隐藏差异。text scope 固定为三个 entry + 三个 model `.cpp`；不能搜索根目录后宣称受 selected-files 约束。实际 manifest 须完整记录文件 inventory、source fingerprint、工具/配置/规则、artifact hashes 和 generation。当前工作区只有遗留 P1 index，没有此 scope 的可信 P3-B manifest，不能给旧 index 补标签后假定 fresh；需要使用已有公共 P1/P2 fixture preparation 建立此次小范围验收的可验证 artifacts，不实现生产 refresh entry point。

### Reviewed file hashes (SHA-256)

`frameworks/core/components_ng/pattern/` 在下表缩写为 `pattern/`，只是文档展示缩写；机器输入须用完整路径。

| Source | SHA-256 |
| --- | --- |
| pattern/button/bridge/button_dynamic_modifier.cpp | `cc4ac849eff263ef4aad50f4e1fe4dbc085fe662c3bf6f19e34ae1d50f31721e` |
| pattern/button/button_model_ng.cpp | `5e423a593b059e7a80e343656d2c24a56c5f176ea181a2792e55dce2a3d70667` |
| frameworks/core/interfaces/native/node/view_model.cpp | `4766c5bf42da2ff872d057933d2ec457d7306cb38a691d40126105ddfdae5142` |
| pattern/text/text_model_ng.cpp | `bd2d8a9e78b8253d5841e56b5309baa457ca53c6a433cd8e65f3bd1b1c43dc69` |
| pattern/menu/bridge/menu/menu_dynamic_modifier.cpp | `24632be2039ecb32ccebcb5dc739aa15ae8d84dce7f01263563056e383b65dfb` |
| pattern/menu/menu_model_ng.cpp | `89562c75890f7bd943768b52f8b623a863ee8d271ba6ec066a5fe1bdc0941572` |

## Fixed inputs

repository 固定 `OpenHarmony/arkui_ace_engine`，Task target revision 使用 [P2 baseline](p2-code-graph-baseline.md) 的完整固定 revision；调用方须显式提交该 revision 和经 P3-B 验证的 prebuilt manifest/session，不能以 graph snapshot_key 或当前 HEAD 代替。source anchors 从对应 P2 fixture 引用处人工核验，新的 P3 required/relevant evidence 独立标注。

| Case ID | Task | Existing anchor reference | C1 query channels / review focus |
| --- | --- | --- | --- |
| c1-button-creation | `检查 [component:Button] [symbol:CreateButtonFrameNodeForCustom] 的创建依赖` | `tests/fixtures/creation_cases.py` Button case | symbol/declaration/definition/reference/callers/callees/text/domain_component；标注 direct candidates，不能要求 C1 自动发现多跳 creation chain |
| c1-text-creation | `检查 [component:Text] [symbol:createTextNode] 的创建依赖` | 同文件 Text case | 同上，加 tests_for_symbol/test_mapping；文本测试线索与真实语义 mapping 分别标注 |
| c1-menu-creation | `解释 [component:Menu] [symbol:CreateMenuFrameNode] 的 callback 创建路径` | 同文件 Menu case | 同上，加显式 graph incoming/outgoing；保留 callback/Pattern gap，命中文本不能补造绑定 |

输入复用 [P3 input outline](p3-input-annotation-outline.md) 的三个 creation drafts。这里没有开启 D trace/expansion，也不选择 C2 Change revisions。

## Human annotation worksheet

每个 case 在执行 retrieval **之前**填写并冻结：

1. annotator、时间、完整 Git revision、P2 case ID 和 source anchor path/range/hash。
2. required evidence：具体 symbol identity/source anchor、typed relation 端点、test mapping 或准确 text range；记录依据。尚无 backend identity 时先冻结可人工核验的 source/name anchors，再显式验证其 identity 对应关系，不能从候选输出选择正确答案。
3. relevant optional evidence、known unavailable dependency 和 forbidden inference；每个维度区分 frozen empty / unannotated / N/A。
4. 固定 channels、所有 `RetrievalBounds`、semantic/test/text selected-files scope 和预构建配置；不能声称 full-repository coverage。
5. ambiguity、unsupported、empty mapping、source 与 artifact provenance 的预期约束。

建议 evidence 单位为 symbol identity、精确 range + role、typed directed relation、test identity/mapping；不同 overload 不合并，重叠 range 不自动合并。该评估单位随本清单一并冻结；当前 C1 技术 dedup 规则见 [candidate retrieval spec](../specs/task-change-context/candidate-retrieval-v1.md)，不替代 required/relevant 人工判断。

## Explicit smoke and completion gate

用户显式触发后，在可验证的 selected-files snapshot 上调用生产 `task_request` / `CandidateRetriever.retrieve`；结果由公共 P1/P2 API 产生，expected 只供比较。核验 required evidence、query/source/snapshot provenance、overload/ambiguity 和 channel diagnostics，报告 scope/bounds 截断；不据 actual 改写 gold，不运行 P2 full baseline，不自动 refresh。

人工冻结已完成；真实 smoke 结果另见 execution plan 引用的验收报告，不能回填或修改本清单。synthetic integration fixture 的独立预期只验证代码 contract，不冒充真实 ArkUI gold。
