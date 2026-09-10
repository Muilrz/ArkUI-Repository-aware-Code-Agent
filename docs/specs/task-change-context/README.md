# Task / Change Context specifications

当前实现范围为 P3-A 的共享输入边界（`arkui_agent.context`）、P3-B 的知识读取契约（`arkui_agent.knowledge`）、P3-C1 的多通道候选检索（`arkui_agent.retrieval.service`）、P3-C2 的双侧范围映射（`arkui_agent.retrieval.change_mapping`）及已验收的 P3-D 图扩展（`arkui_agent.retrieval.expansion`）。

- [Task / Change input v1](input-v1.md)：typed model、坐标、revision intent、有限 parser、错误与序列化。
- [Knowledge Snapshot Read Contract v1](knowledge-snapshot-v1.md)：manifest、generation、freshness、scope、prebuilt validation 和只读 binding。
- [Multi-channel Candidate Retrieval v1](candidate-retrieval-v1.md)：公共 API adapters、固定 session、有限 planning、候选去重、provenance 和 channel completeness。
- [Changed Range Mapping v1](change-range-mapping-v1.md)：双侧 revision/session 隔离、edit block 坐标、P1 extent 证明、未映射范围与 C1 integration。
- [Graph Expansion v1](graph-expansion-v1.md)：P3-D 有界 policy、C1/C2 seeds、原始 P2 traversal/trace observations、预算与 provenance。
- [P3 evaluation 输入与标注提纲](../../evaluation/p3-input-annotation-outline.md)：待人工冻结的输入设计，不包含 retrieval expected。
- [C1 frozen annotations](../../evaluation/p3-c1-annotation-draft.md) / [真实 candidate smoke](../../evaluation/p3-c1-candidate-smoke.md)：三组人工 expected 与选定 scope 的验收结果。

P3-D expansion 已完成验收，见 [frozen gold](../../evaluation/p3-d-expansion-annotations.md) 与 [验收报告](../../evaluation/p3-d-expansion-smoke.md)；Refresh/rebuild、subgraph/snippet、ranking 和 Context Pack 由后续 milestone 定义。本目录不替代 [P3 execution plan](../../exec-plans/active/P3-task-change-context.md) 的验收状态。
