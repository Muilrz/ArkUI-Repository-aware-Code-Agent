# Measure and Layout Trace Specification

对应 P2-G。实现位于 `src/arkui_agent/graph/layout.py`。

## API and stages

`trace_measure_layout(index, graph, domain, workspace, seed=..., component=..., bounds=...)` 返回 immutable `LayoutTrace`。seed 是显式 Pattern P1 identity，component 是显式 P2-C identity。

最小架构阶段为：

```text
Pattern → CreateLayoutAlgorithm method → LayoutAlgorithm
        → Measure/MeasureContent
        → Layout
        → LayoutProperty dependency
```

缺失阶段不补占位 node。Measure 和 Layout 是独立 operation，不生成 Measure → Layout relation。

## Evidence rules

- Pattern → factory 由 METHOD `parent_identity` 表示成员关系，不伪造 class → method CALL。
- factory → algorithm 必须使用输入 graph 中重新核验的 P2-D CREATE；需要受支持完整 allocation body、唯一目标 REFERENCE 和真实 allocation CALL。
- 受支持的完整 switch/case allocation body只能暴露有精确 REFERENCE 的候选，不能解析条件、选择 default 或生成 CREATE。
- MEASURE 和 LAYOUT 分别是 algorithm class → method 的 P2-D binding。method 必须有匹配 parent、DECLARE；implementation stage 还需要 DEFINE 和源码起始签名。
- inherited but undeclared operation 不从名称或基类文本外推。
- LayoutProperty dependency 只接受 operation definition 开头受支持的 straight-line preamble，以及 `DynamicCast<T>(layoutWrapper->GetLayoutProperty())` 中 T 的唯一精确 REFERENCE。
- T 必须有同 Component、无歧义的 LayoutProperty role。该关联只证明静态类型依赖。

不跨 branch、comment、literal、preprocessor、附近函数或 unsupported preamble 借用 evidence。

## Result

- `stages` 按 Pattern/factory/algorithm/Measure/Layout/LayoutProperty 保存全部已接纳候选及 anchors、parent 和 role evidence。
- `bindings` 保存 CREATE/MEASURE/LAYOUT；`support` 保存 DECLARE/DEFINE/REFERENCE。
- `calls` 独立保留 factory/operation 的真实一跳 CALL，不递归展开，也不暗示这些 CALL 构成连续路径。
- `dependencies` 保存 operation、property identity、原 REFERENCE 和 source evidence。
- `candidates`、`gaps`、`source_evidence` 和 `exhaustive` 保存未解决 identity、缺口、源码 hash 和截断状态。

`LayoutBounds(max_candidates=32, max_calls=100)` 限制各阶段候选和总一跳 CALL 输出。超限为 incomplete 且 `exhaustive=False`；已知 ambiguity 不因截断为一个候选而消失。

唯一无缺口静态片段为 complete；缺事实/unsupported 为 incomplete；多候选或 identity/role 冲突为 ambiguous。

真实 revision、source checks 和 expected traces 由 `tests/fixtures/layout_cases.py` 维护。
