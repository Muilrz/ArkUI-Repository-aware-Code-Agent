# Code Graph Specifications

本目录定义 P2 当前已实现行为，是 API、identity、relation、evidence、query status 和 failure semantics 的规范来源。

| Specification | 对应 milestone | 内容 |
| --- | --- | --- |
| [Graph model and query](graph-model-and-query.md) | P2-A | node/edge identity、provenance、dedup、query 和 traversal |
| [Projection and storage](projection-and-storage.md) | P2-B | P1 facts projection、snapshot、持久化和生成数据生命周期 |
| [Domain role mapping](domain-role-mapping.md) | P2-C | Component、role、recognized/unknown/ambiguous |
| [Framework relations](framework-relations.md) | P2-D | CREATE、UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW、CLOSE、TEST、MOCK |
| [Creation trace](traces/creation.md) | P2-E | Component creation trace |
| [Property update trace](traces/property-update.md) | P2-F | Property writer/state/reader trace |
| [Measure/layout trace](traces/measure-layout.md) | P2-G | LayoutAlgorithm、Measure、Layout、LayoutProperty trace |
| [Overlay show/close trace](traces/overlay-show-close.md) | P2-H | Menu Show/Close trace |

这些文件描述稳定行为和能力边界，不保存 milestone 状态、逐次测试输出或开发过程。具体 ArkUI revision、源码位置和 expected result 由相应 `tests/fixtures/*_cases.py` 维护；执行状态见 P2 execution plan。
