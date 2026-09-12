# Repository Knowledge Service Architecture

## Purpose

本文定义 Code Review Service 使用的 provider-based Repository Knowledge Service。最高层方向以 [Technical Roadmap](technical-roadmap.md) 为准；本文件只展开 provider、freshness、evidence、query、update/rebuild 和 degradation 边界。

Repository Knowledge Service 不是必须维护统一数据库、统一 `KnowledgeSnapshot` 或统一 generation 的知识平台。它在一次 review 的目标 revision 下协调多个 provider，并为 KnowledgeGateway 返回可追溯、可降级的 evidence。

## Architecture

```text
ReviewRequest(repository, base/head revision, change)
                         ↓
                 KnowledgeGateway
                         ↓
          Repository Knowledge Service
          ┌──────────┬──────────┬──────────┬──────────┐
          ↓          ↓          ↓          ↓
      DocsKb      LiveSource     P1         P2
      Provider     Provider    Provider    Provider
          └──────────┴──────────┴──────────┴──────────┘
                         ↓
           evidence + provider freshness
                         ↓
               ReviewContextPack
```

`KnowledgeGateway` 屏蔽 provider selection、freshness policy、budget、fallback 和 evidence normalization。Code Review Service 不直接读取 P1/P2 私有存储，也不把 provider 内部 generation 当作公共一致性模型。

## Provider contract

每个 provider 至少具有下列逻辑能力：

- 声明 provider name、capabilities 和版本；
- 针对 repository/revision 返回 freshness status；
- 在明确 query/change scope 和 budget 下检索 evidence；
- 保留 source、revision/version、location/identity、confidence/uncertainty；
- 对 unsupported、ambiguous、truncated、stale 和 error 显式建模；
- 支持适用时的 update/rebuild，或明确报告不支持。

公共 contract 不规定 provider 使用数据库、文件、CLI、MCP 或内存结构。Provider 返回的 evidence 不能隐去自身 revision，也不能把启发式匹配伪装成 semantic fact。

## Providers

### DocsKbProvider

数据源：ArkUI docs/kb、`context_registry`、`kb_search`。

职责：

- 提供组件边界、架构约束、领域术语、API/behavior 文档；
- 根据 change/review query 返回有来源的相关文档片段；
- 报告 docs corpus revision/version 和 freshness；
- 文档与源码冲突时保留冲突，不覆盖当前 Live Source。

Docs evidence 是解释和约束证据，不是当前源码存在性的最终证明。

### LiveSourceProvider

数据源：`rg`、Git、filesystem。

职责：

- 在目标 base/head revision 下读取 diff、changed hunks 和周边源码；
- 查找当前声明、实现、配置、宏、调用写法和测试源码；
- 验证其他 provider 的 file/range/symbol claims 是否仍适用于目标 revision；
- 对不存在、无法读取或 revision 无法解析的源码明确失败。

Live Source 是当前 PR revision 源码事实的最终 source of truth。工作树、base、head 不得混用；每条 evidence 必须携带它实际读取的 side/revision。若目标 revision 无法读取，Review 不得谎称已基于当前源码完成。

### P1Provider

复用现有 P1 Repository Intelligence，提供：

- symbol identity；
- declaration / definition；
- reference；
- caller / callee；
- test fixture / test case mapping。

P1Provider 保留 P1 已实现的 identity、provenance、ambiguity 和 unsupported 语义。Adapter 可以把现有 P1 query contract 归一化为 knowledge evidence，但不得重写 frozen P1 semantics。

当 P1 revision 与 review target 不一致时，P1 evidence 标为 stale，不能作为当前确定事实。Service 可以刷新 P1 或排除其 claims，并继续 `Docs + Live Source` review。

### P2Provider

复用现有 P2 ArkUI Code Graph，提供：

- ArkUI role metadata；
- framework-aware relations；
- bounded creation/property/layout/overlay traces；
- evidence-preserving partial/ambiguous results。

P2Provider 不改变 [P2 architecture](code-graph-architecture.md) 和现有 [P2 specs](../specs/code-graph/README.md)。P2 evidence 在第一阶段是 optional；P2 stale/unavailable 不能阻塞 review。

### Future SemanticMcpProvider

未来可以增加 `SemanticMcpProvider`，通过外部 semantic MCP 补充 facts。它必须遵循相同 freshness/evidence contract，且只能作为可选 provider。当前架构、R0–R6 DoD 和最低可用 review 不依赖它。

## Provider-level freshness

Repository Knowledge status 以目标 repository revision 为顶层上下文，分别报告 provider 状态：

```json
{
  "repository_revision": "B",
  "docs": {"status": "ready", "revision": "B"},
  "live_source": {"status": "ready", "revision": "B"},
  "p1": {"status": "stale", "revision": "A"},
  "p2": {"status": "stale", "revision": "A"}
}
```

Provider status 至少包含：

- `ready`：可按声明 revision/capability 使用；
- `stale`：已有数据不对齐目标 revision；
- `unavailable`：provider 或依赖不存在；
- `refreshing`：更新进行中，尚不能声明 ready；
- `error`：检查、查询或更新失败。

实现 contract 还应冻结 `revision`、provider/tool/rule version、`checked_at` 和 diagnostics。`revision: null` 表示未知，不等于目标 revision。

### Freshness rules

1. LiveSourceProvider 必须能读取目标 head revision，才可完成基于当前源码的 review。
2. DocsKbProvider 可以具有与源码不同的版本模型，但必须显式报告；冲突由 Live Source 裁决当前源码事实。
3. P1/P2 只有 revision 对齐或 provider 明确定义并证明 compatibility 时，才能作为 current facts。
4. Stale P1/P2 可以用于提示刷新或候选 discovery，但不能无标记进入 finding 的确定 evidence。
5. Provider readiness 彼此独立；不存在统一 snapshot/generation gate。
6. 所有排除、刷新、fallback 和 provider error 都写入 ReviewContextPack/ReviewResult diagnostics。

## Query and context assembly

KnowledgeGateway 接收：

- repository identity；
- base/head revision 与 diff/change scope；
- requested evidence capabilities；
- category/context budgets；
- freshness/degradation policy。

推荐顺序：

```text
validate target revision with LiveSource
                ↓
query changed source and direct context
                ↓
query relevant Docs evidence
                ↓
check P1/P2 freshness independently
        ┌───────┴────────┐
      ready          stale/unavailable
        ↓                 ↓
      query          refresh or exclude
        └───────┬─────────┘
                ↓
normalize, deduplicate, budget, record gaps
                ↓
ReviewContextPack
```

Evidence merge 不表示事实被强行统一。相互冲突的来源保留 provenance 和冲突；Live Source 只对当前源码事实优先，Docs/P1/P2 各自的 domain/semantic claims 仍按其 evidence strength 解释。

## Degradation matrix

| Provider state | Review behavior |
| --- | --- |
| Docs ready + Live Source ready + P1/P2 ready | 使用全部适用 evidence |
| Docs ready + Live Source ready + P1 stale/unavailable | 排除 stale P1 current claims，以 Docs + Live Source 继续 |
| Docs ready + Live Source ready + P2 stale/unavailable | 排除 graph claims，以 Docs + Live Source + 可用 P1 继续 |
| Docs unavailable + Live Source ready | 可按 policy 做 source-only review，并明确降级 |
| Live Source unavailable/not at target revision | 不得完成声称基于当前 revision 的 review；返回可诊断失败 |

P1/P2 refresh 是提升质量的路径，不是最低 availability gate。

## Update and rebuild

Repository Knowledge Service 对外提供：

- `update_repo_knowledge`：按 repository、target revision 和可选 provider scope 做常规更新；
- `rebuild_repo_knowledge`：按明确 provider scope 做恢复性/强制重建；
- `get_knowledge_status`：返回 provider-level freshness 和 diagnostics。

Update/rebuild 是 Service 操作，不由 Skill 实现。并发、幂等、进度、失败和 last usable data 由后续 implementation spec 冻结。

Provider 内部可以采用 full rebuild、incremental update、cache 或 stateless query。旧 P3-F 的 dependency-driven incremental lifecycle 可以作为 P1/P2 provider 内部未来优化参考，但不是公共 contract，也不是 Review 的阻塞前置条件。

## Storage and persistence

- Live Source 可无持久化，直接在明确 revision 查询。
- Docs/P1/P2 可以复用现有 index/graph/cache。
- Provider-specific snapshot、generation、shard 或 manifest 可以保留为内部实现细节。
- KnowledgeGateway 只持久化 review 可追溯所需的 provider status/evidence references，不要求复制全仓知识。
- 所有派生 index、graph、cache 和 runtime status 都是可重建 runtime data，默认不提交 Git。

## Correctness and failure semantics

- 不把 stale/unknown 伪装成 ready。
- 不把旧 revision fact 当作当前确定事实。
- 不因 P1/P2 不可用而阻止最低 `Docs + Live Source` review。
- 不以 Docs 推翻当前源码。
- 不因 provider failure 丢失已知 degradation diagnostics。
- 不把名称相似、文本命中或图路径自动提升为 semantic proof。
- 不为获得“统一视图”改变 P1/P2 frozen semantics。

## Historical relationship

[ADR-0004](../decisions/ADR-0004-incremental-repository-knowledge.md) 的统一 incremental lifecycle 决策已由 [ADR-0005](../decisions/ADR-0005-code-review-service-pivot.md) 取代。旧实现、spec 和 P3-A～E 已完成事实保留；本架构只改变未来产品如何消费这些能力。
