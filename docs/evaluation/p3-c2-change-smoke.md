# P3-C2 frozen Change smoke — passed

## Final acceptance — 2026-09-09

**PASS；P3-C2 Completed。** 修复后的 trusted Stop Hook 为 **72/72，188.289 秒，exit 0**，完成于 `2026-09-09T10:29:02.619379+00:00`，包含真实 clangd 双文件顺序与严格 conflict regression。随后重跑用户已授权的原冻结 smoke，未改变 gold、revision、semantic scope、bounds 或 inventory 规则。

固定 repository 为 `OpenHarmony/arkui_ace_engine`，base `5422984fee409dc6f0a679ab5fc7ed38c19aae92`，head `b29b394599624df784c0a7480a39537853d38821`。Frozen expected SHA-256 仍为 `8453c6ce67ec01e2bb0a9a569b7703eb2d18933e2cda3a1b54dba2702d3edd49`。

| Side | Generation | Symbols / observations | Semantic files / fingerprint files | Manifest publication UTC |
| --- | --- | --- | --- | --- |
| base | `c2-base-37fed8342db3dc7a` | 92 / 95 | 2 / 4 | 11:43:53.834750 |
| head | `c2-head-8aa01ae0b5392961` | 93 / 102 | 3 / 5 | 11:43:59.861542 |

两侧独立 clean checkout、P1/P2 artifacts、manifest、P3-B sessions；绑定均为 **fresh / coverage sufficient / diagnostics empty**。Head canonicalization 无冲突，保留 declaration-site class parent。批量入口与 merge 的顺序不变性由上述真实 clangd regression 覆盖。

Base inventory 为下文记录的四个路径；head inventory 为同样四路径加 F1 `frameworks/core/components_ng/pattern/button/toggle_button_paint_property.cpp`。两侧最终 inventory 均在第一条 query（**11:44:12.006612 UTC**）之前发布，query 不扩充 scope。Toolchain 为 clangd 22.1.6，原 C++17/include roots，两侧 compile database 均不存在。

### Every range actual

M = `OHOS::Ace::NG::ToggleButtonPaintProperty::ToJsonValue`；T = `OHOS::Ace::ToggleTheme`。坐标一基、end exclusive。所有行 ambiguous=False，未截断。

| Range | Actual | Public P1 proof | Diagnostics |
| --- | --- | --- | --- |
| F1/H0 old `[1,1)` | not_applicable，空 | 文件不存在 | `file_absent_on_side` |
| F1/H0 new `[1,41)` | M，intersecting | head F1 definition `[(22,33),(22,44))` | `intersection_only_no_enclosing_extent` |
| F2/H0 old `[22,24)` | unresolved，空 | 无合法 extent | `no_proven_symbol_extent` |
| F2/H0 new `[22,26)` | T，intersecting | head F2 declaration/definition `[(24,7),(24,18))` | `intersection_only_no_enclosing_extent` |
| F2/H1 old `[53,70)` | M，intersecting | base F2 declaration/definition `[(53,10),(53,21))` | `intersection_only_no_enclosing_extent` |
| F2/H1 new `[55,56)` | M，intersecting | head F2 declaration `[(55,10),(55,21))` | `intersection_only_no_enclosing_extent` |
| F3/H0 old `[22,22)` | unresolved，空 | include 区零长度点，无吸附 | `no_proven_symbol_extent` |
| F3/H0 new `[22,23)` | unresolved，空 | include 指令不是被引入类的范围 | `no_proven_symbol_extent` |

T 的两条同坐标 proof 按 P1 原样保留，不将 forward declaration 推断为实现发生变更。M 的 base/head opaque identity 恰好相同，输出仍分别绑定不同 revision/generation，未跨侧合并。没有额外可证明的 namespace/class candidates；没有把 token extent 扩成 body，也没有伪造 relation。

### AC / evidence

- 4/4 required symbol-range hits、3/3 required unresolved、1/1 not_applicable 通过。
- 公共 index 独立枚举与 actual 全部 identity/extent proofs 精确相等，无遗漏或无依据的额外候选。
- 每条 anchor 的 file/hunk/block/range/side/provenance 与重新解析的原 frozen Change 精确相等；每个 seed/binding 的 repository/revision/snapshot/generation 正确。
- 两侧 manifest 校验和、全部 inventory 源码 SHA-256 未漂移，freshness guards 通过。
- 同一输入、同一双 sessions 的两次生产 `ChangedRangeMapper.map` canonical JSON **完全一致**；report passed=true，range_count_valid=true。
- 合法多解、overload、真实 rename/delete、缺 base 与 P1 范围不足等边界由 targeted tests 覆盖；本真实 subset 只宣称 add/modify 和表中零长度场景。

运行报告位于 `var/c2-smoke-canonical/report.json`，完整 actual 位于同目录 `actual.json`；各侧 `preparation.json`/`manifest.json` 保留 query 前 inventory 与 artifact identity。显式 prepare 约 12 秒，query/审计报告约 28 秒。未执行 strict full、P2/C1 baseline 或 P3-D；未修改 frozen expected。P3 Phase 保持 In Progress，P3-D 保持 Not Started。

## Historical first attempt (superseded)

以下为首次失败记录，保留其事实；不代表最终验收状态。

2026-09-09：用户人工确认 [frozen expected](p3-c2-change-annotation-draft.md)，同时显式授权真实验收。冻结时间 `2026-09-09T09:54:15+00:00`，approver 为本任务用户；expected 文件 SHA-256 为 `8453c6ce67ec01e2bb0a9a569b7703eb2d18933e2cda3a1b54dba2702d3edd49`。未根据 preparation 或 actual 修改 expected。

## Result

**Setup failure；P3-C2 保持 In Progress。** 两个独立 clean checkout 均已就绪；base snapshot 已发布，head 收集出现相同 identity 的 conflicting public P1 facts，遵照冻结 preparation 条件停止，未发布 head manifest。没有调用 `ChangedRangeMapper.map`，没有 actual mapping、稳定性结果或 smoke pass。

- Repository：`OpenHarmony/arkui_ace_engine`。
- Base：`5422984fee409dc6f0a679ab5fc7ed38c19aae92`。
- Head：`b29b394599624df784c0a7480a39537853d38821`。
- 原 target checkout 保持 clean，HEAD 仍为 `0096f5bd943ed1f7fa56883aed0e2379f13c2885`。
- clangd：22.1.6，冻结的 C++17 fallback 和四个 include roots；base 没有 compile database。
- 独立 checkout 使用 `core.autocrlf=false`、`core.longpaths=true`。与选定 C++ scope 无关的 LFS 包在本地源缺失，因此保留 Git LFS pointers，不下载包，不扩大验收范围。

## Prepared inventory

Base generation：`c2-base-fa3089acf9972258`。P1 收集两个 primary 文件分别返回 9 / 86 symbols，去除完全相同记录后 92 个；manifest 于 `2026-09-09T09:59:58.003742+00:00` 发布，早于任何 C2 query。semantic scope 仍只有 F2/F3。

固定闭包规则得到的最终 base fingerprint inventory：

1. `frameworks/base/utils/utils.h`
2. `frameworks/core/components_ng/pattern/button/toggle_button_paint_property.h`
3. `frameworks/core/components_ng/pattern/button/toggle_button_pattern.h`
4. `interfaces/inner_api/ace_kit/include/ui/base/utils/utils.h`

Head F1/F2/F3 各返回 4 / 12 / 86 symbols；因以下冲突，未发布最终 manifest/inventory，也没有建立双侧 query sessions。不能将准备失败的一侧当成 usable/fresh generation。

## Conflicting P1 facts

同一 qualified name：`OHOS::Ace::NG::ToggleButtonPaintProperty::ToJsonValue`。

同一 identity：`symbol:8a80986d580b0b088c3868908a91c7fc9d5c31cc9d42ca571afe2c6e08c0a8ab`。

| Field | 从 F1 `.cpp` 收集 | 从 F2 `.h` 收集 |
| --- | --- | --- |
| display_name | `ToggleButtonPaintProperty::ToJsonValue` | `ToJsonValue` |
| parent_identity | `symbol:1109324ac01e38cc2a5df4070dfc7fbe571c0c5246b61a19feafe55d4494ab6b`（namespace） | `symbol:056efce2182eab06390c77e2016ec04020bd63b9fd39da89616b1d344f28b5a6`（class） |
| declaration | F2 `[(55,10),(55,21))` | 相同 |
| definition | F1 `[(22,33),(22,44))` | 相同 |

坐标一致不等于完整 Symbol facts 一致。冻结规则要求 conflicting facts 报告 setup 问题，不能选取更有利的记录或根据 expected 重写 parent/display_name。本次没有修改 P1 backend，也没有放宽冻结条件。

## Eight-range acceptance status

| Range | Frozen requirement | Actual / proof / ambiguity / diagnostics / provenance |
| --- | --- | --- |
| F1/H0 old `[1,1)` | not_applicable，空 | 未执行，不能视为通过 |
| F1/H0 new `[1,41)` | M intersecting | 未执行 |
| F2/H0 old `[22,24)` | unresolved，空 | 未执行 |
| F2/H0 new `[22,26)` | T intersecting | 未执行 |
| F2/H1 old `[53,70)` | M intersecting，base | 未执行 |
| F2/H1 new `[55,56)` | M intersecting，head | 未执行 |
| F3/H0 old `[22,22)` | unresolved，空 | 未执行 |
| F3/H0 new `[22,23)` | unresolved，空 | 未执行 |

没有 actual C2 relation，因而不宣称“所有 mapping 无伪造”已验收。双侧 binding、每个 range 的 provenance、额外候选完整性与重复 canonical 稳定性仍待真实执行。

## Reproduction and validation

显式验收入口为 `scripts/run_c2_smoke.py`，`prepare` 和 `query` 分开；通过 `--repository-root`、`--checkouts-root`、`--output` 指定路径。checkout 必须位于本项目外部；output 使用新的运行目录。只在双侧 manifest 成功发布后使用 query。

本次可重建运行证据位于 `var/c2-smoke-frozen/base/{manifest,preparation}.json` 与 `var/c2-smoke-frozen/head/setup-failure.json`；不提交 artifacts。第一次尝试因 runner 的相对/绝对路径错误中止，其未发布产物保留在 `var/c2-smoke/`。已修正路径处理；清理命令被自动审批拒绝，因此使用新目录，不删除原目录。

开始本轮时读取 trusted Stop Hook：46/46 通过，183.382 秒（包含 C2 24 tests），完成时间 `2026-09-09T09:45:59.970745+00:00`。本轮新增 preparation conflict regression tests，等待 trusted Stop Hook，未手动执行 tests。真实 smoke preparation 已按用户授权运行；未运行 strict full、C1/P2 baseline 或 P3-D。
