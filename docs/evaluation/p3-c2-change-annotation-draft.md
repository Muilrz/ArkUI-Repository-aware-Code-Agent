# P3-C2 real Change 人工验收草案

状态：**Frozen expected**。human approver：本任务用户（2026-09-09 明确人工审阅通过）；frozen_at：`2026-09-09T09:54:15+00:00`。用户同时显式授权按本文执行真实 C2 smoke。以下 expected 在 P1 preparation 和第一条 C2 query 前冻结，仅依据 Git 历史对象、源码和已实现 P1/C2 contract；不得根据 actual 修改。正文中的草案/拟执行措辞保留为冻结时的验收设计记录。

## Repository and revision pair

- Repository identity：`OpenHarmony/arkui_ace_engine`。
- Git object 来源：用户指定的外部只读 checkout，当前 HEAD 仍为 C1 的 `0096f5bd943ed1f7fa56883aed0e2379f13c2885`，不是本次拟查询 revision。
- **Base：`5422984fee409dc6f0a679ab5fc7ed38c19aae92`**。
- **Head：`b29b394599624df784c0a7480a39537853d38821`**。
- Head 的直接 parent 是上述 base；commit subject：`优化bubble/toggle/menu/select/checkboxgroup/button组件头文件引用`。两个真实 commit 均已通过 `git show` 读取；没有伪造同 revision pair。
- 将来执行时为两个 revision 准备各自 clean checkout 和独立 generation/session；不切换/修改现有 C1 checkout，不把当前 HEAD 当 base/head。

整个 commit 改动 17 文件，本 smoke **明确仅选下表 3 文件**；不宣称覆盖整个 commit。

| ID | 完整 repository-relative path | Change kind |
| --- | --- | --- |
| F1 | `frameworks/core/components_ng/pattern/button/toggle_button_paint_property.cpp` | add；base 不存在，head 40 行 |
| F2 | `frameworks/core/components_ng/pattern/button/toggle_button_paint_property.h` | modify；base 79 行，head 65 行 |
| F3 | `frameworks/core/components_ng/pattern/button/toggle_button_pattern.h` | modify；base 159 行，head 160 行 |

本 pair 的 selected subset **没有 rename 或整文件 delete**。F2 删除 inline body 属于 modify 中的删除行，不标成 FileChange.DELETE；移动方法实现也不是文件 rename。计划要求的至少一个 add/delete/rename 场景由 F1 add 满足。rename/delete 真正双侧语义已在本轮通过的 targeted tests 覆盖，不冒充本次真实覆盖。

## Diff generation and every hunk

固定生成选项：`git diff --no-ext-diff --no-textconv --unified=0 --no-renames BASE HEAD -- F1 F2 F3`，路径展开为上表完整路径。禁用外部 diff/textconv；`--no-renames` 是该 subset 的固定选项，不测试 rename detection。

选定 diff 的原始 stdout SHA-256：`a0532aec1b6221e41ddd87638ac9b35c4f44c57faa94ef147f66b02db73dcfae`。不另存 patch/diff snapshot；将来由固定 Git objects 生成并校验，再交 A parser。没有 context 行，所以每个 hunk 恰好一个连续 edit block。

以下内部 range 均为 **1-based、column=1、end exclusive**；`[a,b)` 表示 `[(a,1),(b,1))`。Git 零 count 的 start 与 A 规范化后的 point 不相同，必须使用内部值。

| Hunk | Git header | old internal range | new internal range | Source change |
| --- | --- | --- | --- | --- |
| F1/H0 | `@@ -0,0 +1,40 @@` | `[1,1)`，path=None | `[1,41)` | 新增整个 `.cpp`，包含 namespace 和 `ToJsonValue` 定义 |
| F2/H0 | `@@ -22,2 +22,4 @@` | `[22,24)` | `[22,26)` | 两条 include 换成空行、`namespace OHOS::Ace`、`class ToggleTheme;` 与 namespace close |
| F2/H1 | `@@ -53,17 +55 @@` | `[53,70)` | `[55,56)` | inline `ToJsonValue` 定义改成单行 declaration |
| F3/H0 | `@@ -21,0 +22 @@` | `[22,22)`，path 存在 | `[22,23)` | 插入 `#include "core/components/toggle/toggle_theme.h"` |

## 每个 changed range 的 proposed expected

符号简称：

- **M** = `OHOS::Ace::NG::ToggleButtonPaintProperty::ToJsonValue`。
- **T** = `OHOS::Ace::ToggleTheme`。
- **C** = `OHOS::Ace::NG::ToggleButtonPaintProperty`。
- **N** = `OHOS::Ace::NG` namespace；**A** = `OHOS::Ace` namespace（P1 若将 nested namespace 拆成多条，仍按各自真实 identity/extent 保留）。

opaque SymbolIdentity 只能由各侧 P1 public API 产生，不能填写猜测 hash。执行前用下表的 qualified name + path + anchor 核对独立 P1 facts；同名目标不唯一必须保留并报告 setup ambiguity，不能选择第一项。下面的“必需”不得在实际执行后降级成 optional。

| Range | 必需结果 | 预期 ambiguity / unresolved | Source anchor / rationale |
| --- | --- | --- | --- |
| F1/H0 old `[1,1)` | `not_applicable`；symbols 空；`file_absent_on_side` | 非 unresolved，不触发 old path 查找 | base tree 确认不存在 F1；不得用 head 新文件提供 old symbols |
| F1/H0 new `[1,41)` | **M，intersecting**；证明 extent 必须在 head F1 | 至少 M；存在同文件 namespace 等额外合法 extent 时全部保留，多个 identity 则 ambiguous=True | head F1:22–23 签名，24–39 body；整个新增区间大于 method extent，因此不能标 enclosing |
| F2/H0 old `[22,24)` | `unresolved`、symbols 空、`no_proven_symbol_extent` | ambiguity=False | old F2:22–23 是 include，不是被 include 类的 declaration/definition；不能映射到 ToggleTheme 或 PipelineContext |
| F2/H0 new `[22,26)` | **T，intersecting**；证明应为 head F2:24 的 forward declaration | 同文件 A extent 若可得，则与 T 同时保留、ambiguous=True；只有 T 时 False | new F2:23 namespace；24 `class ToggleTheme;`；25 close。它是声明证据，不等于 ToggleTheme 实现被修改 |
| F2/H1 old `[53,70)` | **M，intersecting**；只使用 base F2 的 definition/declaration 证据 | 如果 P1 真正提供同文件 C/N enclosing extent，须附加并设 ambiguous=True；仅 token-only 容器不附加 | base F2:53 签名、54–69 body。changed interval 从列 1 开始并延伸至下一行，超出 method 自身范围；不能把 method 标 enclosing |
| F2/H1 new `[55,56)` | **M，intersecting**；只使用 head F2 declaration 证据 | 同上，C/N 仅可由真实 enclosing extent 附加；不借 head F1 的定义范围来命中本 header | head F2:55 单行 declaration；head F1:22 是同方法定义，但文件不同，不能作为当前 range proof |
| F3/H0 old `[22,22)` | `unresolved`、symbols 空、`no_proven_symbol_extent` | ambiguity=False；现存文件上的零长度点 | 插入点在 includes 区域，早于 namespace/class；不得吸附下一行或 `ToggleButtonPattern` |
| F3/H0 new `[22,23)` | `unresolved`、symbols 空、`no_proven_symbol_extent` | ambiguity=False | new F3:22 仍只是 include 指令，不能把被引入头文件中的类作为当前文件命中 |

### 额外命中与不确定性的冻结规则

这里明确采用 **必需源码锚点 + 对额外原始 P1 extent 的固定约束**，不在运行前捏造未知的 backend namespace identity 数量：

1. 上表 4 个必需 symbol-range checks 为硬要求：F1/new M、F2/H0/new T、F2/H1/old M、F2/H1/new M。P1 若没有提供这些同文件证据，真实结果即为差异/失败，不能据 actual 改为 expected unresolved。
2. 上表三处必需 unresolved 范围与一处 not_applicable 都要求 symbols 空。不要把 unknown 当任意集合。
3. 非空命中范围中的额外 namespace/class，仅在**该侧、该文件**原始 declaration/definition extent 确实 enclosing/intersecting 时允许；必须逐项保存 proof 并检查，没有 extent 依据的额外 identity 为错误。F1 的同文件 N extent 若返回，属于 intersecting；F2/H0/new 的 A extent若返回，属于 intersecting；F2/H1 的 C/N 只有覆盖该改动才允许 enclosing。
4. 不将 `documentSymbol.range` 或人工读出的花括号范围代替 P1 已持久化的 declaration/definition。P1 token-only 范围只能证明 token 的相交；不能为了产生 enclosing/ambiguity 而填造完整 class/function body。
5. 同一 identity 的 declaration/definition 多条 proof 合并为一个 candidate；不同 identity 全部保留。跨 side 即使 opaque identity 相同也不合并。ambiguous 必须等于该 range 实际保留的合法不同 identities 的多解情况；截断前观察到多解也不能丢弃 ambiguity。
6. 此真实 subset 不强制制造 overload 或正向 point-interior 命中；这些已由 targeted tests 覆盖。会核验不丢 overload，但不会把没有 overload 的实际输入写成真实多 overload 通过。

如果希望使用“精确封闭 identity 集合”而不是上述规则，需要在人工冻结前另行审阅独立 P1 preparation 产物；当前没有运行这种 preparation，不会默默补填。上述规则本身也是本次请求人工审阅的内容。

## Snapshot scope and fixed execution design

本轮只提案，不创建 checkout/index/manifest，不启动 clangd。

人工冻结并获得执行授权后，拟采用：

- 两侧各一个 clean checkout、独立 P1 index/P2 generic graph/domain、各自 B manifest 和 SnapshotSession。
- base semantic_files 固定 **F2、F3**；head semantic_files 固定 **F1、F2、F3**。不谎称 base F1 存在。不以本次 commit 的全部 17 文件或全仓为 scope。
- 使用公共 `ClangdSemanticProvider.symbols_in_file` 收集上述文件内全部返回 symbols；不按 expected 名称筛选、不人为补 extent、不作 caller/callee/reference/graph expansion。保留实际声明/定义路径；重复 identity 的 conflicting facts 作为 setup 问题报告，不按“有利于 expected”选择。
- source fingerprint inventory 采用在查询前固定的规则 `c2-declaration-definition-source-v1`：该侧固定 semantic files，加本次公共 P1 preparation 返回 symbols 的 declaration/definition 文件，去重排序；这一过程只发生于 preparation，**第一条 C2 query 前写入最终 manifest inventory**。不能根据 actual C2 matches/provenance 扩大 scope。
- semantic_files 仍为固定 2/3 文件，附加 fingerprint 文件不宣称已具备 semantic coverage。test_files 与 text_files 均固定为空；本 smoke 不额外运行 C1 text 检索。
- clangd 使用 22.1.6；固定 C++17 fallback，repository-relative include roots 为 `.`、`frameworks`、`interfaces/inner_api/ace`、`interfaces/inner_api/ace_kit/include`；记录实际 toolchain/config/rule fingerprints、compile database 是否存在及 digest。若环境不兼容，应在 query 前报告 setup failure，不调整 frozen expected。
- mapping bounds 固定默认值：`max_ranges=512`、`max_files_per_side=128`、`max_symbols_per_file=10000`、`max_candidates_per_range=128`。预期 8 个 range records 不触发 limits；任何截断都必须保留，必需证据因此缺失不能算通过。
- 主要 smoke 调用 `ChangedRangeMapper.map(Change, base=..., head=...)`，不需要调用 D 或 ranking；C1 integration 已由 targeted tests 覆盖。对同一固定输入、同一 sessions 重复 mapping 时 canonical JSON 应相同。
- 每个 RangeMapping 记录 file/hunk/block provenance、Side、path、原始 LineRange、对应 revision、snapshot/generation；每个 seed 保留真实 P1 SymbolIdentity 与所有 extent proofs。

## Forbidden mappings and failure gates

1. 不允许把 head F1 新增实现当成 base 证据；不允许把 base F2:53–69 行号直接套用到 head F2:55。
2. 不允许因方法从 header 移到 `.cpp` 就推断 FileChange.RENAME，或推断跨 revision identity 相同。
3. 不允许把 include 增删映射成被 include 文件中的 class/function；不允许根据文件名里的 `toggle_button` 猜 symbol。
4. 不允许把 F3 的 old 零长度点吸附到 next symbol，也不能把 F1 缺文件的 old side 与 F3 现存文件但无 enclosing 的 old side 混成同一状态。
5. 不允许把 head F2 的 declaration range 映射依据替换为 head F1 的 definition range；必须 path 与 side 同时一致。
6. 缺 revision/session、scope 不足、未知 language/backend、source/artifact drift 不能返回假成功。缺侧时保留另一侧结果和原 file/range；运行中一致性失败遵循 B，整体不发布混合结果。
7. 不允许隐藏合法多解或截断、不允许手工制造 P1 extent、SymbolIdentity、generation 或 fresh provenance。
8. 不改 frozen P2/C1 expected；不依据 actual 修改此草案冻结后的 expected。若上述硬要求失败，C2 保持 In Progress 并报告差异。

## Git blob source hashes

下表 SHA-256 直接对 `git show REV:path` 原始 bytes 计算，不是 C2 检索结果。

| Side/file | SHA-256 |
| --- | --- |
| base F1 | absent，不伪造 hash |
| base F2 | `8cd46eb5fa4dd2210961e4495a8eefbf39ab6541afa978eadc178e2cae9634ab` |
| base F3 | `ccbadd8ee764794e399c9ad2def782532bfac4d93c6f9cb9a1bc4be77679229c` |
| head F1 | `3b40ef524d2ee934126ffd6b74dae2dcb4f55fb2e5b7db63ff86adddaf4c3599` |
| head F2 | `0c3fc2459db17053858149e79da15fbe5886cd9af4524c7c38ac3ec617d0e2f6` |
| head F3 | `c922b993a860dde102930f475954cdb3147d336a9ea866431a2b212b3240e194` |

## Current validation state

trusted Stop Hook 已通过：24 个 C2 tests + 22 个 C1 tests = **46/46**，182.141 秒，returncode 0（2026-09-09 09:14:37 UTC 完成）。本轮仅读取报告、Git 历史和源码并准备本文；没有运行测试、真实 C2 query/smoke 或 strict full。

C2 继续 In Progress，D 继续 Not Started。人工确认本文不会自动触发 smoke；冻结后仍等待用户显式授权。
