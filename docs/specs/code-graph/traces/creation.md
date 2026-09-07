# Component Creation Trace Specification

对应 P2-E。实现位于 `src/arkui_agent/graph/creation.py`。

## API and result

`trace_component_creation(index, graph, domain, workspace, seed=..., component=..., bounds=...)` 返回 immutable `CreationTrace`。

- seed 是调用方显式选择的完整 P1 NodeIdentity；component 是已知 `arkui.component` identity。
- query 不解析自然语言，不按名称选择 entry、overload 或 Pattern。
- 输入可为 generic 或 framework graph，并允许 partial graph；缺失 relation 不从完整 index 补回。
- result 保存 scope、seed、component、status、paths、exhaustive、diagnostics 和 `p2.creation.v1` ruleset。

## Traversal

只沿输入 graph 中可由 P1 核验的 outgoing CALL。Framework operation binding、property CREATE 和 file REFERENCE 不作为 CALL hop。

查询先对同 Component Model 和已核验 FrameNode factory 做反向可达过滤，再按 canonical edge order、per-path visited 枚举 simple paths。到达 FrameNode factory 后停止 CALL traversal，并独立核验 Pattern argument association。

`CreationBounds(max_depth=8, max_paths=32, max_states=1000)` 分别限制 CALL 深度、返回路径数和 forward states。预算截断或 cycle cut 设置 gap 和 `exhaustive=False`；canonical order 不代表 ranking。

## Evidence and stages

- `CreationPath.nodes` 按 Entry/Bridge → support → Model → FrameNode → Pattern 的架构顺序保存已验证节点及 evidence。
- `relations` 只保存连续真实 CALL，保留原 endpoints 和 P1 精度。
- `pattern_argument` 保存 caller、frame factory、Pattern 参数以及 supporting CALL/REFERENCE、allocation、role 和 source evidence。它不是 GraphEdge，也不生成 FrameNode → Pattern CALL。
- Pattern association 只支持已审查的直接 factory source shape；Frame factory token和 Pattern token 都必须有唯一 P1 REFERENCE，allocation helper 必须有真实 CALL 和权威 implementation evidence。
- FrameNode 仅作 trace-local identity check：method 的真实 parent 必须是 authoritative `OHOS::Ace::NG::FrameNode` class。
- unknown/ambiguous Pattern 保留 candidate 和 evidence，不提升为 Pattern stage。

架构顺序不表示 C++ 参数求值顺序或同一 runtime instance。

## Status

- `complete`：穷尽后只有一条无缺口的 Entry/Bridge → Model → FrameNode 路径，并有可靠 Pattern association。
- `incomplete`：缺事实、unsupported source shape 或搜索截断。
- `ambiguous`：多条候选路径，或 role/reference/allocation identity 冲突。

每个 path 另有自身 status。截断时即使已有 complete path，也不能宣称全局唯一完整。

真实 revision、source checks 和 expected traces 由 `tests/fixtures/creation_cases.py` 维护。
