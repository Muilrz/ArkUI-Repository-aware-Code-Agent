# Overlay Show and Close Trace Specification

对应 P2-H。实现位于 `src/arkui_agent/graph/overlay.py`。

## API and boundary

`trace_overlay(index, graph, domain, workspace, manager=..., component=..., show_seed=..., close_seeds=(...), bounds=...)` 返回 immutable `OverlayTrace`。

entry 和 manager 使用完整 P1 NodeIdentity；同名 overload 不合并。component 使用 P2-C identity。当前范围是调用方显式配对的 Menu API family；query 不自动发现 overlay/entry，不证明 Show 和 Close 使用同一 runtime node/manager instance，也不扩展为通用 Lifecycle Trace。

Show 和 Close 是两个独立 `OverlayLeg`，分别保存 operation、seeds、paths、status、gaps 和 exhaustive。

## Traversal

每个 leg 只枚举 seed → operation 的真实 P1 CALL。operation 必须是选定 manager 的 semantic child METHOD，Show 和 Close 分别匹配 ShowMenu/HideMenu。

查询先做反向可达过滤，再按 canonical edge order、per-path visited 枚举 simple paths；到 operation 即停止入口 CALL traversal。多条 path 全部保留，不排序选优。

`OverlayBounds(max_depth=8, max_paths=32, max_states=1000)` 对每个 leg 分别限制 CALL 深度、paths 和 forward states。cycle/depth/path/state cut 设置 gap 和 `exhaustive=False`。

## Binding and managed associations

- OverlayManager 必须有唯一 P2-C shared OVERLAY_MANAGER role。
- SHOW/CLOSE 是 manager class → operation entry binding，不是 CALL；binding 与入口 CALL 分开保存并重新核验。
- operation 必须有 DEFINE 和受支持的源码起始签名。
- `RefPtr<FrameNode> [&] menu` 参数类型通过同一 opaque method identity 的 definition 或有 DECLARE 支持的 declaration 中精确 P1 REFERENCE 证明。声明/实现冲突为 ambiguous。
- managed node stage 是 `managed_node_type`，只证明参数类型，不创造 runtime FrameNode identity 或 CREATE。

可选 Pattern tail 只接受完整 tiny body：menu null guard、`GetPattern<T>()`、pattern null guard 和 direct member call。T 需要唯一 REFERENCE、同 Component Pattern role；member 需要唯一 identity、正确 semantic parent 和真实 operation → member CALL。

可选 animation 只接受精确 `AnimationUtils::Animate` METHOD identity、权威声明位置、token REFERENCE 和真实 direct CALL：

- 有可靠直接证据：`present`，加入 animation stage；
- 完整受支持 body 没有直接 Animate：`not_observed_in_supported_body`，不创建 stage；
- body 不受支持：`unresolved`，不声称传递调用中没有动画。

分支、lambda、comment、附近函数、同名目标或未解析 modifier/function-pointer dispatch 都不能替代这些证据。

## Result and status

- nodes 按 entry/support → manager → operation → managed_node_type → optional Pattern → optional animation 排列。
- `calls` 只保存连续 entry → operation CALL；`binding` 保存 SHOW/CLOSE；`support` 保存原方向 DECLARE/DEFINE/REFERENCE 和可选 tail CALL。
- source_evidence 保存精确 signature/body range 和 source hash；candidates/gaps 保留冲突与缺失事实。
- 唯一无缺口且穷尽的静态 path 为 complete；缺事实、unsupported 或截断为 incomplete；多路径或 identity/role/component 冲突为 ambiguous。

exhaustive 只相对于传入 graph 和显式 seeds，不表示覆盖仓库全部 Close/runtime path。真实 revision、source checks 和 expected traces 由 `tests/fixtures/overlay_cases.py` 维护。
