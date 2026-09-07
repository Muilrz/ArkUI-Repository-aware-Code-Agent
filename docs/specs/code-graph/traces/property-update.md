# Property Update Trace Specification

对应 P2-F。实现位于 `src/arkui_agent/graph/property.py`。

## API and seed

`trace_property_update(index, graph, domain, workspace, seed=..., setter=..., component=..., bounds=...)` 返回 immutable `PropertyTrace`。

seed、setter 都是显式完整 P1 NodeIdentity；不接受同名字符串替代。component 使用 P2-C identity。seed 可以直接是 setter，此时保留局部片段并报告 `missing_entry_call`。

输入 scope、nodes 和 P1 edge evidence 必须一致。Partial graph 中缺失的 CALL、REFERENCE、DECLARE、DEFINE 或 framework binding 不从完整 index 恢复。

## Traversal and binding

query 只沿已验证 CALL 枚举 seed → setter direct supporting chains。先反向可达过滤，再按 canonical edge order 和 per-path visited 展开；到 setter 即停止。`PropertyBounds(8, 32, 1000)` 限制深度、paths 和 forward states。

setter 的 semantic parent 必须是同 Component Model。P2-D UPDATE_PROPERTY 是 method → property class binding，不等于 CALL。binding 必须在输入 graph 中存在，并经 framework extractor 重新验证其 generic/source evidence。

受支持 macro 中的 property class token 通过精确 source range 的唯一 P1 REFERENCE 绑定；Layout/Paint macro 必须匹配相应 P2-C role。property token 是带 source evidence 的语法标签，不是虚构 field identity。

## State association

下游只接受可验证的显式 member read/write：

- writer 必须是真实 CALL endpoint，并是目标 property class 的 METHOD；
- 完整 tiny writer body 把参数赋给有精确 REFERENCE 的同 parent FIELD；
- reader 的完整 tiny body返回同一 FIELD identity；
- 只有真实 consumer → reader CALL 才纳入 consumer。

不根据方法名、宏生成 artifact、邻近代码、继承成员或复杂 body 猜测 state flow。该关联证明静态同一成员，不证明运行时对象相同、调用先后或渲染效果。

## Result and status

- nodes 按 Entry/Bridge/support → Model → LayoutProperty/PaintProperty → writer → state → reader → consumer 排列。
- `calls` 只保存连续 entry → setter CALL；`binding` 保存 UPDATE_PROPERTY；`support` 保存原方向 CALL/REFERENCE。
- candidates、candidate_evidence 和 gaps 保留冲突、未知和缺失证据。
- 唯一无缺口且穷尽的静态链为 complete；缺事实/unsupported/截断为 incomplete；多路径或 identity/role 冲突为 ambiguous。

真实 revision、source checks 和 expected traces 由 `tests/fixtures/property_cases.py` 维护。
