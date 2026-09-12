# ADR-0003: Multi-capability Repository-aware Engineering Agent

- **Status:** Superseded by [ADR-0005](ADR-0005-code-review-service-pivot.md)
- **Date:** 2026-09-07

> 本 ADR 保留为历史决策记录。multi-capability Engineering Agent、generic Agent Runtime 和 Code Review/UT sibling capability 路线不再是当前产品方向；当前架构以 ADR-0005 与 `docs/architecture/technical-roadmap.md` 为准。

## Context

项目最初的长期路线把 P0-P4 的 Repository Intelligence、ArkUI Code Graph、Task Context Builder 和 Agent Runtime 最终主要收敛到 P5 `UT Agent & Repair`。

随着在线代码检视需求进入项目，目标能力扩展为：

- GitCode Pull Request 在线检视；
- 可配置轮询间隔，例如每 10 分钟发现新的 review work；
- 可按 PR 作者用户名筛选检视对象；
- 检视前使用 ArkUI 全仓 repository knowledge，并支持周期刷新与手动刷新；
- 重点检视 Stability、Memory/Lifetime、Functional Correctness、Test Impact 等问题；
- 继续保留并发展原有 UT Generation / Build / Test / Repair 能力。

如果为 Code Review 单独建立 repository parser、index、graph、context pipeline 或 Agent runtime，会重复 P1-P4 已有/规划的基础设施并产生长期双轨维护成本。

同时，当前项目实际名称已经是 **ArkUI Repository-aware Code Agent**，该名称没有把产品限制在 UT 场景，不需要为了此次能力扩展修改 repository/local folder 名称。

## Decision

### 1. Project Positioning

ArkUI Repository-aware Code Agent 定位为面向 ArkUI Ace Engine 的 **multi-capability Repository-aware Engineering Agent**。

UT 不再是唯一最终产品能力。

第一批 Engineering Capabilities 为：

```text
Engineering Capabilities
├─ Code Review
└─ UT Development & Repair
```

后续源码分析、问题定位、修复等能力应优先作为新的 capability 复用共享基础设施。

### 2. Shared Infrastructure

以下层次是所有 capability 的共享基础设施：

```text
P1 Repository Intelligence
        ↓
P2 ArkUI Code Graph
        ↓
P3 Task / Change Retrieval & Context Builder
        ↓
P4 Agent Runtime
```

任何 capability 不得为了自身需求复制独立 Symbol Index、ArkUI Graph 或长期 Context pipeline。

### 3. Repository Knowledge Lifecycle

Repository-derived persistent knowledge 继续沉淀在：

- index；
- graph；
- component/framework metadata；
- knowledge snapshot / freshness metadata。

不使用长期 LLM memory 作为全仓知识存储。

增加共享 Repository Knowledge Lifecycle：

- snapshot identity / repository revision；
- freshness check；
- scheduler-invokable periodic refresh；
- manual refresh；
- refresh failure visibility。

第一版允许 repository revision 变化后全量 rebuild；增量 refresh 作为后续性能优化。

### 4. Task and Change as Peer Inputs

P3 从 `Task Retrieval & Context Builder` 扩展为 `Task / Change Retrieval & Context Builder`。

自然语言开发 Task 与 PR/Commit/Diff Change 都可以作为 retrieval seed，之后共享 Text/Symbol/Reference/Test/Graph retrieval 和 Context Builder。

P3 不直接绑定 GitCode API。

### 5. Agent Runtime, Skill and Tool

P4 保持通用 Agent Runtime，新增明确的 Skill contract / invocation 边界：

- **Tool**：执行 repository query、knowledge refresh、code host read/write、build/test 等受控动作；
- **Skill**：描述如何组合 Tool 完成一种工程任务；
- **Runtime**：负责 planning、state、observation、retry、stop、trace 和 Skill/Tool 调度。

Skill 不负责长期轮询线程，也不以 LLM memory 保存 repository knowledge。

### 6. Engineering Capabilities in P5

P5 从 `UT Agent & Repair` 扩展为 `Engineering Capabilities`。

Code Review 与 UT Development / Repair 是 sibling capabilities。

Code Review 第一目标平台为 GitCode，并通过通用 `CodeHostProvider` / `GitCodeProvider` adapter boundary 集成，包含：

- PR/change ingestion；
- configurable polling watcher；
- author username filtering；
- head revision deduplication；
- knowledge freshness gate；
- repository-aware review context；
- Stability / Memory-Lifetime / Functional / Test Impact review；
- structured ReviewFinding；
- review/comment publishing。

UT Development / Repair 继续包含 Test Mapping、UT Generation、Patch、Minimal Build/Test、Failure Classification 和 Repair Loop。

### 7. Evaluation

P6 继续整合 P1-P5 已持续建设的 evaluation，并新增 Code Review benchmark 与指标。

Code Review benchmark 必须包含 No-Issue cases，避免“每个 PR 必须找出问题”的系统偏差。

## Relationship to Previous ADRs

### ADR-0001

本 ADR **amends** ADR-0001 中 P3/P5 的具体产品边界：

- P3 从 Task-only 扩展为 Task / Change；
- P5 从 UT-only 扩展为 Engineering Capabilities。

ADR-0001 的核心工程管理模型仍然有效：

```text
Phase
  ↓
Milestone
  ↓
Codex Task
```

P0、P1、P2 的既有边界与已完成结果不因本 ADR 重写。

### ADR-0002

本 ADR 遵循 ADR-0002 的文档权威规则：

- 长期结构进入 `docs/architecture/`；
- Phase 边界进入 `phase-map.md`；
- 未来实现后的具体 contract 才进入 `docs/specs/`；
- 当前 P2 execution plan 不因未来 Code Review 需求扩 scope。

## Consequences

### Positive

- Code Review 与 UT 共享同一套 repository-aware 基础设施。
- 现有 P0/P1 成果和当前 P2 工作不需要推翻。
- P3/P4 变成真正可复用的 Task/Change Context 与 Agent Runtime。
- GitCode 是首个 Code Host，而不是上层硬依赖，未来可扩展 GitHub/Gitee。
- Repository Knowledge freshness 成为显式平台能力，降低使用旧 index/graph 分析新代码的风险。
- 后续增加新的 Engineering Capability 时有稳定扩展模式。

### Trade-offs

- P3/P5 的未来 scope 比最初 UT-only 路线更大，需要在接近开发时继续拆 milestone。
- Code Review 需要处理 polling/dedup/publishing 等非纯代码分析问题。
- Knowledge refresh 引入 revision consistency 与失败可见性要求。
- Code Review evaluation 必须关注 false positive，而不能只统计“发现了多少问题”。

## Follow-up

1. 保持当前 P2 execution plan 不变，继续完成 P2。
2. 更新 `technical-roadmap.md` 与 `phase-map.md` 体现新的长期架构。
3. 在 `technical-roadmap.md` 中统一维护 Repository Knowledge Lifecycle，并新增 `code-review-architecture.md` 作为独立 Code Review 专题架构。
4. Code Graph 当前 contract 继续由 `docs/specs/code-graph/` 维护；移除不再定义现行规范的 `architecture/graph-contract.md` 兼容文档。
5. P3 接近开发时再创建/细化 active execution plan 和对应 milestone。
6. Code Review 的具体 API/config/ReviewFinding contract 在实现 milestone 完成时进入 `docs/specs/`，不提前把 architecture proposal 当作已实现规范。
