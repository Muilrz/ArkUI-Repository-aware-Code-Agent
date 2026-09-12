# Code Review Service Architecture

## 1. Purpose

本文定义项目的核心业务架构：独立 Repository-aware Code Review Service。第一目标平台是 GitCode，第一阶段聚焦 Pull Request/diff 的 Stability、Memory / Resource / Lifetime 和 Functional Correctness review。

本文定义未来边界；真实实现完成后，其 API、schema、不变量和失败语义进入 `docs/specs/`。最高层方向以 [Technical Roadmap](technical-roadmap.md) 为准。

## 2. Architecture position

```text
GitCode PR / Diff
        ↓
GitCodeProvider
        ↓
PR Poller / Scheduler ──→ Review User Filter ──→ Revision Dedup
                                                   ↓
                                         Review Job Manager
                                                   ↓
                                            Review Engine
                                                   ↕
                                          KnowledgeGateway
                                                   ↓
                                  Repository Knowledge Service
                            (Docs + Live Source + P1 + optional P2)
                                                   ↓
                                         ReviewContextPack
                                                   ↓
                                     Structured Review Findings
                                                   ↓
                                             Result Store
                                                   ↓
                         application API / MCP Server / Code Review Skill
```

Service 是 review 生命周期的 owner。外部 Agent 可以触发或读取 review，但不负责 scheduler、filter、dedup、job state 或 result persistence。

## 3. Service components

### GitCodeProvider

隔离 GitCode authentication、pagination、HTTP retry/error、PR/diff schema 和 position mapping。平台无关层只消费稳定 domain models。

Read capabilities 至少规划：

- discover/list PR；
- PR metadata、author、base/head SHA；
- changed files、diff、hunks/ranges；
- 必要的 source/review state。

未来若发布 comment，write capability 也必须留在 provider；Review Engine 不直接调用 GitCode API。

### PR Poller / Scheduler

按配置周期发现候选 PR 并提交 review work。轮询间隔不是硬编码常量。未来 webhook 可以作为新的 trigger adapter，但不改变 ReviewRequest contract。

Scheduler 属于 Service，不属于 MCP、Skill 或外部 Agent。

### Review User Filter

按配置的 PR author username 集合过滤。过滤在昂贵的 knowledge/review 之前执行。`set_review_users` / `get_review_users` 管理的是 Service 配置，不把名单嵌入 Skill。

### Revision Dedup

最小 review identity：

```text
repository + pr_id + head_sha + review_policy_version
```

同一 identity 已成功完成或正在由有效 claim 处理时，不创建重复 review。新 `head_sha` 或 policy version 是新工作。Force retry、failed retry 和 finding fingerprint 的细节由 R1/R3 spec 冻结。

### Review Job Manager

负责：

- 接受手动或自动 ReviewRequest；
- job lifecycle、并发 claim、timeout/cancel/retry；
- 调用 KnowledgeGateway 与 Review Engine；
- 保存 degradation、failure 和 result identity；
- 为 `get_review_status` / `get_review_result` 提供稳定查询。

Job Manager 不实现通用 Agent planning 或任意 Tool/Skill runtime。

### Review Engine

消费平台无关的 ReviewRequest + ReviewContextPack，执行固定 review policy，输出 zero or more validated `ReviewFinding`。它不轮询 GitCode、不刷新 provider 私有存储、不发布平台 comment。

### Result Store

持久化：

- review identity、request 和状态；
- head/base revision 与 review policy version；
- provider freshness/degradation summary；
- structured findings；
- failure/retry/audit diagnostics。

Result Store 不保存一份私有全仓 Repository Knowledge 副本。

## 4. Review request and ingestion

Review 可来自：

- `review_pr`：以 repository + PR identity 由 GitCodeProvider 获取 metadata/diff；
- `review_diff`：调用者直接提供平台无关 diff/change input；
- auto review：Scheduler 发现并通过同一 application API 提交。

标准化输入至少包含：

```text
PR metadata
+ diff
+ changed files/hunks
+ base/head revision
+ review policy/version
```

无法映射到 symbol 的 hunk 仍保留 file/range/text evidence，不以名称猜测 symbol identity。

## 5. KnowledgeGateway and freshness

Review Engine 只通过 KnowledgeGateway 获取 knowledge。Provider 结构与 freshness 详见 [Repository Knowledge Architecture](repository-knowledge-architecture.md)。

Context evidence：

```text
Docs evidence
+ Live Source evidence
+ P1 facts
+ optional P2 graph evidence
```

关键规则：

- Live Source 必须对齐当前 head revision，是源码事实的最终 source of truth。
- Freshness 按 Docs/Live Source/P1/P2 分别报告，不使用统一 Snapshot gate。
- P1/P2 stale 时刷新或排除其 current-fact claims；不得静默使用旧 revision evidence。
- P1/P2 stale/unavailable 不阻塞 `Docs + Live Source` review。
- Provider degradation 与证据 gaps 进入 ReviewContextPack 和最终 result。

## 6. ReviewContextPack

`ReviewContextPack` 至少包含：

- repository、PR/diff、base/head revision；
- changed files/hunks/ranges；
- Docs、Live Source、P1 和 optional P2 evidence；
- 每个 provider 的 status/revision/version；
- evidence provenance 和 inclusion reason；
- stale/excluded provider、unsupported/ambiguous/truncated gaps；
- context budget 和实际裁剪结果。

Context selection 应优先 change-local、可证明、可行动的 evidence。不得把全仓源码/graph 无约束塞入模型。旧 P3-A～E 能力可以被 adapter 复用，但新 Service contract 不以旧统一 KnowledgeSnapshot 为前提。

## 7. Review categories

### Stability

关注 null/invalid state、range/boundary、error/recovery path、async/callback state、重复注册/遗漏清理、生命周期错配和 crash-prone assumption。

### Memory / Resource / Lifetime

关注 strong/weak/raw ownership、callback capture、registration/unregistration 对称性、资源 release、异步持有、cycle、dangling/leak 风险。仅有类型名或文本模式不足以产生强 finding。

### Functional Correctness

关注遗漏分支、状态/property 传播、ArkUI Model/Pattern/Property/Layout 路径、default/reset behavior、API contract 和与同类实现的有证据偏差。

测试源码和 test mapping 可以作为 correctness evidence 或 coverage suggestion，但本产品路线不包含 UT Development / Repair workflow。

## 8. ReviewFinding contract

Finding 至少包含：

```text
file
location/range
category
severity
title
description
evidence
reasoning
suggestion
confidence
```

Severity：

```text
Critical
High
Medium
Low
```

约束：

- `file` 和 `location/range` 必须对应 change 或有明确相关性；
- evidence 必须可追溯到 diff/Live Source/provider source 与 revision；
- description 解释问题和后果，reasoning 连接证据与结论，suggestion 提供可行动方向；
- confidence 不替代证据，provider stale/unknown 必须影响 confidence/claim；
- 允许成功返回 zero findings；
- Review Engine/validator 拒绝缺少必要定位、证据或枚举非法的 finding。

## 9. Auto review lifecycle

```text
Scheduler tick
    ↓
GitCodeProvider.list candidate PRs
    ↓
Review User Filter
    ↓
compute repository + pr_id + head_sha + policy version
    ↓
Revision Dedup
    ├── seen/in-flight → skip with state
    └── new → Review Job Manager
                   ↓
          knowledge + review
                   ↓
             persist result
```

`start_auto_review` / `stop_auto_review` 控制 Service scheduler。停止 auto review 不删除既有结果；进程重启后的 state/recovery 由 R1/R5 spec 冻结。

## 10. MCP boundary

MCP Server 暴露 application APIs，第一阶段至少规划：

```text
review_pr
review_diff
get_review_result

update_repo_knowledge
rebuild_repo_knowledge
get_knowledge_status

set_review_users
get_review_users

start_auto_review
stop_auto_review
get_review_status
```

MCP 负责输入验证、稳定错误映射、认证/授权和结果序列化。它不复制 Review Engine、KnowledgeGateway、scheduler 或 Result Store logic，也不实现 Agent Runtime。

## 11. Code Review Skill boundary

Skill 面向 Codex、Claude 和其他支持 MCP 的 Agent，说明如何选择和组合 tools、轮询异步 result、解释 findings/freshness/degradation、处理 error 和遵守发布权限。

Skill 不负责：

- 持续 polling PR；
- 保存 review users 或 dedup state；
- GitCode HTTP/API；
- provider refresh/cache/index；
- review result persistence；
- 通用 planning/state/retry loop。

## 12. Safety and failure semantics

1. **No evidence, no strong finding**：关键结论必须有可追溯证据。
2. **No forced finding**：No-Issue change 可以 zero findings。
3. **No duplicate review spam**：同一 review identity 不因 scheduler 重复处理。
4. **No stale masquerading**：旧 P1/P2 revision 不作为当前确定事实。
5. **Live Source authority**：当前源码与其他来源冲突时，以目标 revision Live Source 为准并记录冲突。
6. **Graceful enhancement loss**：P1/P2 failure 降低能力但不阻塞 Docs + Live Source。
7. **No platform leakage**：GitCode 私有 schema 不进入 engine/knowledge contract。
8. **Explicit partial/unknown**：证据不足、ambiguous、truncated 和 provider error 不静默补全。

## 13. Evaluation

Benchmark 至少覆盖：

- Stability issue；
- Memory / Resource / Lifetime issue；
- Functional regression；
- ambiguous/insufficient evidence；
- stale P1/P2 degradation；
- No-Issue PR/diff；
- duplicate poll/retry/restart state；
- GitCode/provider/MCP failure。

指标至少包含 Finding Precision/Recall、False Positive Rate、Category/Severity/Location Accuracy、Evidence/Provenance Validity、Revision Alignment、Duplicate Review Rate、Review Latency、job success/recovery 和 MCP contract compatibility。

## 14. Phase ownership

- R0：Service/domain/port foundation。
- R1：GitCodeProvider、PR state、users、identity/dedup。
- R2：KnowledgeGateway、providers、freshness、update/rebuild、degradation。
- R3：ReviewContextPack、Review Engine、finding validation/categories。
- R4：MCP Server。
- R5：Service-owned auto review 与 MCP-only Code Review Skill。
- R6：formal evaluation、security/reliability/performance hardening。

P1/P2 的 frozen contract 不因本架构扩大；旧 P3/P4/P5 路线不再是实现依赖。
