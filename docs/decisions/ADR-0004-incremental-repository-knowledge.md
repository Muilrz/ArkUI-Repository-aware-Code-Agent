# ADR-0004 — Dependency-Driven Incremental Repository Knowledge

- **Status:** Superseded by [ADR-0005](ADR-0005-code-review-service-pivot.md)
- **Decision scope:** Repository Knowledge refresh、versioning、P1/P2 derived data lifecycle

> 本 ADR 保留为历史决策记录。其 dependency-driven incremental lifecycle、统一 KnowledgeSnapshot/generation、semantic shard 和 ownership 不再是产品关键路径；当前 Repository Knowledge 使用 provider-based architecture。旧实现可以保留为 provider 内部优化，但不得成为 Review availability 的硬依赖。

## Context

早期 P3 规划允许 target repository revision 变化后全量 rebuild P1/P2，再发布新的 `KnowledgeSnapshot`。该方案适合作为 correctness-first bootstrap，但 GitCode 上的 ArkUI Ace Engine 属于高频变化的大型 C++ repository。如果每次源码变化都重建完整 Symbol/Semantic Index 和 ArkUI Code Graph，refresh latency、CPU/IO 成本以及 freshness lag 会进入 Code Review/UT 等在线能力的关键路径。

同时，完全取消版本化 snapshot 也不可接受。Review/UT/Agent 结果必须能够证明自己消费的是哪个 repository revision、哪套 P1/P2 knowledge 和 rules/tool versions；正在读取旧版本的任务不能因新 refresh 原地覆盖而观察到混合数据。

## Decision

采用 **Dependency-Driven Incremental Repository Knowledge**：

1. 保留 revision-bound、immutable `KnowledgeSnapshot` / generation；
2. `KnowledgeSnapshot` 改为逻辑 manifest，不要求每个 generation 拥有一份完整物理数据库副本；
3. P1 以 TU + compile context 为主要 semantic production / invalidation 单位，维护 dependency impact、semantic fingerprint、immutable semantic shard version 与 ownership；
4. P1 refresh 输出结构化 delta，P2 基于 provenance/规则失效范围增量更新 graph/domain facts；
5. P2 无法安全局部失效的规则允许扩大范围或 full rebuild，正确性优先；
6. P3 负责 refresh planning、freshness、generation、single-writer/atomic publish 和 snapshot-bound query session；
7. normal query 通过 indexed `SnapshotQueryView` 查询，不扫描全部 shard；
8. full rebuild 保留为 bootstrap、recovery、incompatible change、wide invalidation 和 explicit force 的 fallback；
9. 第一版不强制 Base+Delta/LSM/复杂 compaction，先实现 immutable logical shards + ownership + manifest。

## Consequences

### Positive

- 高频源码变化只重建受影响 TU/graph derivations；
- 旧 generation 可继续被 in-flight reader 使用；
- Review/UT/Context Pack 仍然具有明确 revision/snapshot provenance；
- clangd 继续只是 semantic producer，Repository Knowledge schema 不绑定 clangd 私有缓存格式；
- P1/P2 的 query API 可以保持稳定，增量复杂度主要留在 refresh path；
- 可以用真实 affected-TU ratio 和 refresh latency 决定后续存储优化。

### Costs

- 需要 dependency metadata、semantic fingerprint、ownership 和 garbage collection；
- P2 derived facts 需要更明确的 provenance 与 invalidation scope；
- snapshot publication 需要管理 immutable generation 与 read visibility；
- 必须增加 incremental-vs-full conformance tests，防止 false-negative invalidation 留下 stale facts。

## Rejected alternatives

### Full rebuild on every revision

实现简单，但无法满足高频 repository 更新下的 freshness/cost 目标，因此只保留为 fallback。

### Stateless on-demand search only

可以减少持久化维护成本，但会丢失稳定的 semantic/graph derived knowledge、跨能力共享和 revision-consistent evidence，不适合作为本项目主架构。

### One physical database per revision

版本隔离简单，但会重复存储大量未变化知识并增加发布/清理成本。改用 immutable manifest 引用复用 shard。

### Base + Delta as first implementation

可能降低写放大，但会提前引入 compaction、read merge 和多层可见性复杂度。待真实数据表明 single-store shard versioning 不足时再引入。

## Follow-up

- `architecture/repository-knowledge-architecture.md` 展开长期结构；
- `technical-roadmap.md` §4 维护最高层 lifecycle 原则；
- `exec-plans/phase-map.md` 将增量 lifecycle 纳入 P3 的工程边界，并明确 P1/P2 ownership；
- P3 active plan 将旧的“全量 rebuild integration”拆为 dependency、P1 shard、P2 incremental、snapshot query view 和 refresh orchestration milestones；
- 既有 P1/P2 completed plans 与 frozen P2 baseline 保留历史事实，不回写成“当时已经实现增量”。
