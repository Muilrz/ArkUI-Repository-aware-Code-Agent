# ArkUI Code Graph Architecture

本文说明 P2 ArkUI Code Graph 的稳定结构和职责边界，以及它在新 Code Review Service 中作为 `P2Provider` 的定位。长期系统方向以 [`technical-roadmap.md`](technical-roadmap.md) 为准；接口和行为细节以 [`../specs/code-graph/`](../specs/code-graph/README.md) 为准；milestone 状态和验收范围以 [已归档 P2 execution plan](../exec-plans/completed/P2-arkui-code-graph.md) 为准。

## Purpose

P2 在 P1 Repository Intelligence 提供的 C++ repository facts 之上，增加可追溯的 ArkUI domain interpretation：

```text
P1 symbols / source / references / calls / tests
                         ↓
              Generic Code Graph
                         ↓
             ArkUI Role Metadata
                         ↓
          Framework-aware Relations
                         ↓
               Bounded Domain Traces
```

各层只增加自己的解释，不修改底层 P1 identity，也不把推断结果伪装成 P1 semantic fact。

## Layers

### Generic graph

统一表达 symbol、file、test entity 及 DECLARE、DEFINE、REFERENCE、CALL、TEST 等 P1 facts。Graph identity、provenance、排序和查询不依赖具体 storage backend。Graph snapshot 是可从 P1 重建的派生数据。

### ArkUI role metadata

将经过明确规则识别的 class 标注为 Model、Pattern、LayoutProperty、PaintProperty、LayoutAlgorithm、OverlayManager 等角色，并关联已知 Component。无法可靠识别的实体保持 unknown；冲突候选保持 ambiguous。

Role metadata 与 generic graph 分离。它不能改变 symbol identity，也不能通过目录或名称相似度传播角色。

### Framework relations

在 generic facts 和 role evidence 之上建立 CREATE、UPDATE_PROPERTY、MEASURE、LAYOUT、SHOW、CLOSE 等 ArkUI relation。

每条 relation 必须保留底层 source/P1 evidence。MEASURE、LAYOUT、SHOW、CLOSE 表示 operation binding；它们不等同于真实 CALL。unsupported 或 ambiguous source shape 不产生猜测边。

### Domain traces

Creation、Property Update、Measure/Layout、Overlay Show/Close trace 使用显式 seed，在给定 snapshot 中进行有界、可重复、evidence-preserving 的查询。Trace 可以组合 generic CALL、framework binding 和局部 source association，但必须在结果中区分它们的 provenance 和语义。

Trace 返回 complete、incomplete 或 ambiguous，并保留候选、缺口与截断状态。架构顺序用于表达已验证阶段，不自动代表运行时时序或同一对象实例。

## Core invariants

- P1 opaque identity 是 symbol identity 的唯一来源；同名和 overload 不合并。
- Generic relation 与 ArkUI domain relation 始终可区分。
- 每个 node、edge、binding 和 source association 可以追溯到证据。
- Partial graph 保持 partial；query 不从完整 index 静默补回缺失 edge。
- Canonical ordering 只保证确定性，不表示 ranking 或置信度。
- 多候选、role/identity 冲突显式返回 ambiguous；缺失或不支持的证据返回 incomplete。
- 所有 traversal 有明确终止条件和预算；截断结果不宣称唯一完整。
- Repository-derived graph、report 和 index 是可重建 runtime data，不进入 Git。

## P2Provider position

Repository Knowledge Service 通过 `P2Provider` adapter 复用 P2：

```text
existing P2 graph/query APIs
            ↓
        P2Provider
            ↓
ArkUI-specific evidence + provider freshness
            ↓
   KnowledgeGateway / ReviewContextPack
```

`P2Provider` 只做 capability/freshness/evidence normalization，不修改 P2 identity、relation、trace、provenance、partial 或 ambiguous 语义。Provider 必须报告其 repository revision/version；当 P2 stale 或 unavailable 时，Review 排除旧 revision 的 current-fact claims，并降级到 Docs + Live Source（以及可用 P1）。P2 在第一阶段是可选增强，不能成为 review availability 的硬门槛。

未来 provider 内部可以采用任何安全 refresh 或 storage 优化，但新 Repository Knowledge 公共 contract 不要求 P2 实现 incremental projection、统一 snapshot 或 generation。

## Boundaries

P2 不负责：

- 自然语言 Task parsing；
- review-specific context ranking 或 `ReviewContextPack` selection；
- scheduler、review job、MCP 或 Skill orchestration；
- ArkUI runtime execution、对象生命周期模拟或 UI rendering；
- 源码修改、build、test 和 repair loop。

已实现的 P3 task/change-driven graph expansion 是独立历史 contract；新路线可以在 KnowledgeGateway 中复用，但不回写 P2 frozen scope。通用 Lifecycle Trace 未纳入 P2 Definition of Done。

## Normative specifications

- [Graph model and query](../specs/code-graph/graph-model-and-query.md)
- [Projection and storage](../specs/code-graph/projection-and-storage.md)
- [Domain role mapping](../specs/code-graph/domain-role-mapping.md)
- [Framework relations](../specs/code-graph/framework-relations.md)
- [Creation trace](../specs/code-graph/traces/creation.md)
- [Property update trace](../specs/code-graph/traces/property-update.md)
- [Measure/layout trace](../specs/code-graph/traces/measure-layout.md)
- [Overlay show/close trace](../specs/code-graph/traces/overlay-show-close.md)
