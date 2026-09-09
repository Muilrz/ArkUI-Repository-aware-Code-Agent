# P3-C1 Button / Text / Menu candidate smoke

2026-09-09：三组 frozen expected conformance 通过，required **12/12**；这是 selected-files direct retrieval 验收，不是完整 creation chain、全仓 recall 或 Context Pack 验收。

## Freeze and preparation

- Human approver：本任务用户，2026-09-09 明确接受三组 expected，仅要求固定 preparation scope。
- Frozen at：`2026-09-09T08:42:35+00:00`；[冻结清单](p3-c1-annotation-draft.md) 与 `tests/fixtures/c1_cases.py` 在真实查询之前落实；未据 actual 改动 expected。
- Repository：`OpenHarmony/arkui_ace_engine`；revision：`0096f5bd943ed1f7fa56883aed0e2379f13c2885`；外部 checkout 查询前后均 clean。
- Preparation：复用已有 P2 creation 的公共 P1 collector；没有执行 P2 trace/baseline，没有实现 P3-F refresh，没有复用无可信 provenance 的遗留 index。
- 固定 closure rule：`p2-creation-source-closure-v1`，先收集固定 13 个 preparation 文件及该 collector 的 symbol ranges/reference 文件并集，再发布 manifest；**C1 query 不参与 inventory 计算，也未动态扩充 scope**。
- 最终 inventory：30 文件，56 symbols，355 generic graph edges；text scope 6 文件，test scope 空集。无 full-repository coverage 承诺。
- Generation：`c1-835a2e2db8caa6a7`；P3-B binding：`fresh` / sufficient；所有 case 与顺序稳定性复验复用同一 session。
- manifest SHA-256：`8817b4071560d6a7afce463f033fc2e2e2b8cc2056e1e36ac496883aea797086`。
- executable expected SHA-256：`dad37c4ac97ad3122f78ec4607b0275f88ebd67dc6349ef48f2979e55cfe8ac3`。
- 工具：clangd 22.1.6、ripgrep 15.2.0、Git 2.53.0.windows.2。无 compile_commands.json，使用现有 collector 的 C++17 fallback flags/include directories；完整版本和配置摘要保存在 preparation report/manifest。

Preparation 在 `08:46:31.882746–08:48:00.791555 UTC` 完成（88.909 秒）。首条 C1 query 在 manifest 发布后执行；三组 query、反转 query 顺序复验和公共 API provenance 审计在 `08:48:10.149243–08:48:49.463564 UTC` 完成（39.314 秒），命令 returncode 0。

## Actual versus frozen expected

| Case | Required symbol / definition / text / direct CALL | Optional model definition | Optional domain component | 其他入口 text/reference observations | Candidates |
| --- | --- | --- | --- | ---: | ---: |
| Button | 4/4 | 命中 model 源码 659 行 | 命中 Button | 2 | 216 |
| Text | 4/4 | 命中 model 源码 90 行 | 命中 Text | 2 | 218 |
| Menu | 4/4 | 命中 model 源码 25 行 | 命中 Menu | 2 | 218 |

Required entry → model CALL 分别是 `CreateButtonFrameNodeForCustom → ButtonModelNG::CreateFrameNode`、`ViewModel::createTextNode → TextModelNG::CreateFrameNode`、`CreateMenuFrameNode → MenuModelNG::CreateFrameNode`。它们来自 P1 语义事实，并与 P2 对应 CALL 合并 provenance；没有从 hint 构造 SymbolIdentity。

每个 case 均有 38 个 query reports：8 ok、9 empty、14 unresolved、6 unsupported、1 truncated，0 backend failure。总体 status 为 truncated，不能描述为“所有通道完整成功”。

- **Unknown / unsupported：** 每个 case 的 component hint 和 entry hint 各触发三种显式关系通道；INHERIT / OVERRIDE / MOCK 全部 unsupported。直接 graph reports 保留 `unavailable_relations:INHERIT,OVERRIDE`。
- **Unresolved：** `Button` / `Text` / `Menu` 是合法 domain component 名称，但不是此 index 中可解析的同名 symbol，相关 symbol-seeded channels 保留 `symbol_seed_not_resolved`。入口 function 的 domain role 保留 unknown，没有由 component hint 推断 framework role。
- **Tests：** 三个已知入口的 test mapping 均为 scope 内 empty。准备未包含 test files，不能推断真实仓库没有对应测试或测试覆盖。
- **Ambiguity / overload：** 三个指定入口均唯一；此次 real queries 未出现 overload ambiguity（0 ambiguous reports）。各 symbol report 均与公共 P1 同名候选 identity 集合对照，无身份丢失；多 overload 的行为由已通过的 targeted tests 补充覆盖，不把本次唯一输入当成多 overload 实证。
- **Provenance：** 所有 observations 均与绑定 P1/P2 public read facts 对照；candidate snapshot/generation、query origins、source paths/hashes 均通过。每个 case 反转 query 顺序后 canonical JSON 完全相同。
- **Truncation：** 每个组件名 text query 达到冻结 `max_results_per_query=200`，保留 `query_result_limit`；入口名称的 required text 命中未受影响。未扩大任何 bounds，未覆盖首轮结果，也未根据截断追加 scope。
- **Forbidden inference：** 未出现 `FrameNode::GetOrCreateFrameNode → InnerMenuPattern` 伪造 CALL，未用 MenuPattern 替代 callback binding，未声称 Menu 创建链完整。

## Relation audit and source precision limitation

三组返回了 4 / 6 / 6 个 P1 DirectCallRelation observations；对应 graph CALL observations 按 identity 合并。全部与公共 P1/P2 read facts 精确一致，C1 新增伪造 relation 数为 **0**。其他 DECLARE/DEFINE/REFERENCE graph observations 也逐条核对来源，不只核对 required CALL。

原始 report 的 `source_unproven_calls` 分别记录 4 / 6 / 6 项，**未删除或回填这些记录**。这个检查尝试在 P1 提供的 caller range 内寻找 callee 名称；本 fixture 的 caller definition range 仅是函数名称 token，不能用于证明完整函数体调用。因此这一自动检查不能证明上述任何一条 CALL 的 call-site，包括三个 required CALL；这不等于 C1 生成了错误 relation。

后续只读源码核对（作为 actual 审计，不修改 gold）：三个冻结入口函数体直接包含 model CreateFrameNode、RawPtr、IncRefCount；`CHECK_NULL_RETURN` 使用布尔转换，`RefPtr::operator bool` 实现在 `referenced.h:233`；Text/Menu 的 `->` 经 `RefPtr::operator->`（同文件 224 行）及 `LifeCycleCheckable::PtrHolder::operator->`（`lifecycle_checkable.h:39`）。这些隐式调用有源码依据，但 C1 仍只保留 P1 精度，不伪造 exact call-site。

宏定义补充审阅位于 `interfaces/inner_api/ace_kit/include/ui/base/utils/utils.h:33`；它不是本次 C1 返回 evidence，不加入已绑定 inventory。补充源码审阅不能冒充 snapshot 内新增检索事实，也不证明 runtime branch 或全仓语义完整性。

## Validation and reproducibility

最新 trusted Stop Hook：2026-09-09，两个 targeted 模块 **22/22**、77.868 秒、returncode 0；包含真实 temporary Git/P1/P2/rg tests。此后未修改 C1 production code 或这两个 test 模块。新增验收 harness 由本次用户显式授权的 prepare/query 两条命令实际执行验证。

```powershell
py -3 scripts/run_c1_smoke.py prepare --repository-root $env:ARKUI_REPO_ROOT --output var/evaluation/p3-c1
py -3 scripts/run_c1_smoke.py query --repository-root $env:ARKUI_REPO_ROOT --output var/evaluation/p3-c1
```

重新验收必须显式使用新的输出目录；prepare 拒绝覆盖已有目录，query 拒绝覆盖已有 actual/report。不在此流程中自动运行 strict full、其他真实 baseline、refresh 或后续 milestone。

本次 runtime artifacts 在 `var/evaluation/p3-c1/`：manifest、preparation（最终 inventory/配置）、index/graph/domain、三份 actual JSON、`report.json`。它们是可重建验收数据，不提交 Git。机器 report 的 passed 表示 frozen checks 与公共事实一致性通过，不等于全部通道 complete；source precision 限制如上明确列出。

## P3-C1 AC conclusion

| Acceptance criterion | Evidence / conclusion |
| --- | --- |
| Task 与 structured Change seeds 共享通道 | targeted integration tests 通过；real smoke 验证 Task 路径；本次没有运行 C2 mapping |
| 同名不同 identity 保留 | overload/dedup targeted tests 通过；real symbol identity 集合一致 |
| Query 顺序不影响 canonical output | 三组同一 session 的反序复验均通过 |
| empty / unsupported / failure / truncated 区分 | targeted failure tests 通过；real 中 empty/unsupported/truncated/unresolved 均明示 |
| 每个 candidate 有 snapshot/source/query provenance | 三组全部 observations/source hashes/public read 对照通过，0 新造 relation |
| 有限 candidate limit 不冒充 context 完整性 | 三组 text 截断保留；required 未缺失；无全仓/完整 context 声明 |

P3-C1 验收通过。P3 Phase 继续 In Progress，P3-C2 及后续保持 Not Started。
