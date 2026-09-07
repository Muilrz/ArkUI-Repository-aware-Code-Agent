# Framework Relations Specification

对应 P2-D。实现位于 `src/arkui_agent/graph/framework.py`。

## Contract

`extract_framework_relations(index, generic, domain, workspace)` 消费相同 scope 的 P1 index、generic GraphSnapshot、DomainMap 和只读 target workspace，返回 `FrameworkExtraction(graph, diagnostics, ruleset_identity)`。

输出 graph 保留原 nodes 和 identity，generic edges 与 typed framework edges 共存。输入必须是与 index 完全匹配且不含旧 domain edges 的 generic projection；rebuild 顺序为：

```text
project_index → role mapper → framework extractor → GraphStore.save
```

## Relation semantics

| Relation | Endpoints | Required evidence |
| --- | --- | --- |
| CREATE | Pattern factory method → same-Component Property/Algorithm class | semantic parent、DEFINE、受支持完整 allocation body、目标 token REFERENCE、真实 MakeRefPtr CALL 和 allocation implementation |
| UPDATE_PROPERTY | Model method → same-Component Layout/PaintProperty class | parent、DEFINE、唯一目标 REFERENCE、受支持 property macro 及其 macro chain |
| MEASURE | LayoutAlgorithm class → Measure/MeasureContent method | parent、DECLARE、role、完整参数与 override declaration |
| LAYOUT | LayoutAlgorithm class → Layout method | parent、DECLARE、role、完整 Layout declaration |
| SHOW/CLOSE | shared OverlayManager class → ShowMenu/HideMenu method | parent、DECLARE、OverlayManager role、完整 FrameNode/menu 参数契约 |
| TEST | existing test case → tested symbol | P1 tested-symbol mapping；可增强 target role evidence |
| MOCK | no new edge | P1 尚无可靠 mock mapping fact，返回 diagnostic |

MEASURE、LAYOUT、SHOW 和 CLOSE 是 class → operation 的 domain binding，不表示真实发生的 CALL。真实 CALL 始终以 P1 CALL edge 独立保存。CREATE/UPDATE_PROPERTY 仅覆盖已审查的完整 source shape；复杂 lambda、条件分支、多语句模板和任意文本匹配不生成 relation。

## Evidence and failure semantics

每条 framework edge 保留原 P1 evidence、supporting generic EdgeIdentity、P1 parent identity、role rule evidence/fingerprint、framework ruleset version、精确 source range 和 LF-normalized source SHA-256。

文本只用于验证 P1 已定位 identity 处的受支持模板，不用于选择同名 symbol。CALL 的 caller-range 精度不提升为 call-site。一次 extraction 缓存已读 source，并在返回前确认文件未变化。

缺 parent/definition/reference/CALL、unknown/ambiguous role、多个 reference identity、跨 Component、unsupported source shape 或不支持的 macro 不出边，并返回 deterministic diagnostic。I/O、scope、snapshot 和 source consistency 错误显式失败。

具体 ArkUI relation expected 由 framework integration fixtures/tests 维护。
