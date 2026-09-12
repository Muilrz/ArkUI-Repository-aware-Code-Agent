# Task / Change Context specifications

当前实现范围为 P3-A 的共享输入边界（`arkui_agent.context`）、P3-B 的知识读取契约（`arkui_agent.knowledge`）、P3-C1 的多通道候选检索（`arkui_agent.retrieval.service`）、P3-C2 的双侧范围映射（`arkui_agent.retrieval.change_mapping`）、已验收的 P3-D 图扩展（`arkui_agent.retrieval.expansion`）与已验收的 P3-E 候选物化（`arkui_agent.context.materialization`）。

- [Task / Change input v1](input-v1.md)：typed model、坐标、revision intent、有限 parser、错误与序列化。
- [Knowledge Snapshot Read Contract v1](knowledge-snapshot-v1.md)：manifest、generation、freshness、scope、prebuilt validation 和只读 binding。
- [Multi-channel Candidate Retrieval v1](candidate-retrieval-v1.md)：公共 API adapters、固定 session、有限 planning、候选去重、provenance 和 channel completeness。
- [Changed Range Mapping v1](change-range-mapping-v1.md)：双侧 revision/session 隔离、edit block 坐标、P1 extent 证明、未映射范围与 C1 integration。
- [Graph Expansion v1](graph-expansion-v1.md)：P3-D 有界 policy、C1/C2 seeds、原始 P2 traversal/trace observations、预算与 provenance。
- [ContextCandidateSet / Task Subgraph v1](context-candidates-v1.md)：P3-E typed 候选、观察/依赖闭包、只读 snippet 与共享 backing、revision/hash/坐标验证及 round-trip。
- [P3 evaluation 输入与标注提纲](../../evaluation/p3-input-annotation-outline.md)：输入设计与标注边界。
- [C1 frozen annotations](../../evaluation/p3-c1-annotation-draft.md) / [真实 candidate smoke](../../evaluation/p3-c1-candidate-smoke.md)：三组人工 expected 与选定 scope 的验收结果。

P3-D expansion 已完成验收，见 [frozen gold](../../evaluation/p3-d-expansion-annotations.md) 与 [验收报告](../../evaluation/p3-d-expansion-smoke.md)。P3-E 修复后 targeted Hook 与真实 subgraph/snippet [验收](../../evaluation/p3-e-materialization-smoke.md) 已通过，用户授权的 [evidence gold](../../evaluation/p3-e-materialization-annotations.md) 已冻结，P3-E Completed。

## Superseded route and historical boundary

P3-A～E 上述 contract 继续代表“当前已经实现的行为”，不能因为长期架构发生变化就追溯修改成未来状态。未完成的 P3-F1～F6/G/H/I 路线已经停止；本目录不再作为 R0–R6 的 future architecture plan。

特别是：

- `knowledge-snapshot-v1.md` 继续描述 P3-B 已实现的 fixed-generation read/freshness contract；
- 已存在的 P3-F / incremental knowledge spec 只记录工作区当前或历史实现事实，不表示 R 路线必须继续 semantic shard、fact ownership、P1 Delta、P2 incremental graph 或 Snapshot Query View；
- P2 frozen relation semantics、P3 A～E frozen annotations/evaluation 不因存储和 refresh 路线变化而改写。

当前长期设计见 [Technical Roadmap](../../architecture/technical-roadmap.md)、[Repository Knowledge Architecture](../../architecture/repository-knowledge-architecture.md) 与 [ADR-0005](../../decisions/ADR-0005-code-review-service-pivot.md)；历史实施状态见 [superseded P3 execution plan](../../exec-plans/superseded/P3-task-change-context.md)。[ADR-0004](../../decisions/ADR-0004-incremental-repository-knowledge.md) 保留为被取代的历史决定。
