# Code Review Architecture

## 1. Purpose

本文定义 ArkUI Repository-aware Code Agent 的长期在线代码检视架构。

第一目标平台为 **GitCode**，主要面向 Pull Request 在线检视；系统需要支持可配置轮询间隔、按 PR 作者用户名筛选、检视前 Repository Knowledge freshness check，以及基于 ArkUI 全仓 repository facts 的 Stability、Memory/Lifetime、Functional Correctness、Test Impact 等检视能力。

本文只定义 architecture boundary。未来真实实现的 API、配置字段、ReviewFinding schema、不变量和失败语义应在对应 milestone 完成时进入 `docs/specs/`。

---

## 2. Architecture Position

```text
                     GitCode
                       │
                PR / Change Source
                       │
                       ▼
                CodeHostProvider
                       │
                       ▼
                  Review Watcher
              ┌────────┼────────┐
              │        │        │
           interval   author   revision
           trigger    filter    dedup
              └────────┼────────┘
                       ▼
             Review Change Model
                       │
                       ▼
             Knowledge Freshness Gate
                       │
                       ▼
          P3 Change Retrieval & Context
                       │
                       ▼
                Code Review Skill
       ┌───────────────┼────────────────┐
       ↓               ↓                ↓
   Stability     Memory / Lifetime   Functional
                       +
                   Test Impact
                       │
                       ▼
              Structured Findings
                       │
                       ▼
                Review Publisher
                       │
                       ▼
               GitCode Comments
```

Code Review 不重新实现 repository parser、semantic backend、symbol index 或 ArkUI graph。它消费 P1/P2/P3/P4 的共享能力。

---

## 3. Code Host Provider Boundary

上层 Review workflow 不直接绑定 GitCode HTTP/API schema。

定义通用概念：

```text
CodeHostProvider
        ↑
 GitCodeProvider
```

未来可以扩展：

```text
CodeHostProvider
├─ GitCodeProvider
├─ GitHubProvider
└─ GiteeProvider
```

provider 至少为 Code Review 预留以下能力：

### Read

- discover/list pull requests；
- get pull request metadata；
- 获取 author username；
- 获取 base/head revision；
- 获取 changed files；
- 获取 diff / changed hunks / source positions；
- 获取已有 review/comment 状态（用于 dedup / update policy）。

### Write

- publish review summary；
- publish inline finding/comment；
- 必要时更新或标记 Agent 自己生成的 review state。

认证、pagination、HTTP retry、GitCode 私有字段、comment position 映射和平台错误码全部留在 provider/adapter 内。

---

## 4. Review Trigger and Watcher

Code Review Skill 不负责长期轮询。

长期 trigger 由独立 Review Watcher / orchestration 负责。

### 4.1 Configurable Polling

需要支持可配置轮询间隔，例如：

```text
10 minutes
```

但 `10 min` 只是配置示例，不作为硬编码架构常量。

Watcher 周期执行：

```text
poll
 ↓
list candidate PRs
 ↓
filter
 ↓
new review work?
 ↓
submit Review Task
```

未来可以增加 webhook/event trigger，但不要求第一版同时实现；无论 trigger 来源如何，后续 Review Task contract 不应改变。

### 4.2 Author Filter

支持配置 PR author username allowlist/filter。

逻辑上：

```text
PR author
   ↓
author in configured review set?
   ├─ no  → ignore
   └─ yes → continue
```

过滤发生在昂贵的 knowledge retrieval / LLM review 之前。

### 4.3 Repository / Branch / Path Filters

第一版核心需求是 author filter。架构为后续扩展预留：

- repository
- target branch
- path include/exclude
- labels / review state

但不应在第一版为了通用配置框架扩大 scope。

---

## 5. Review Identity and Deduplication

同一个 PR 在没有新提交时，不应每个轮询周期重复 review、重复发评论。

Review work identity 至少应包含：

```text
repository
pull_request_identity
head_revision
```

核心规则：

```text
PR #123 @ abc123
already reviewed abc123
        ↓
       skip

PR #123 @ def456
new head revision
        ↓
      review
```

未来可加入：

- review policy version；
- knowledge snapshot identity；
- manual force re-review；
- finding fingerprint。

这些字段的最终 contract 由实现 spec 冻结。

---

## 6. Change Ingestion

GitCodeProvider 将平台私有数据转换为平台无关的 Change model。

概念结构：

```text
ReviewChange
├─ repository identity
├─ pull request identity
├─ author
├─ base revision
├─ head revision
├─ changed files
├─ changed hunks / ranges
└─ platform provenance
```

随后使用 P1 semantic retrieval 将 changed range 尽可能映射到：

- changed symbol；
- enclosing class / method；
- declaration / definition；
- direct references / callers / callees；
- relevant tests。

无法稳定映射到 symbol 的 diff 仍保留 file/range/text evidence，不通过名称猜测 symbol identity。

---

## 7. Knowledge Freshness Gate

检视前必须调用共享 Repository Knowledge lifecycle，而不是让 Reviewer 自己“重新理解全仓”。

Repository Knowledge 的 snapshot、freshness 与 refresh 边界统一定义在 [`technical-roadmap.md`](technical-roadmap.md) 的 **Repository Knowledge Lifecycle** 章节；Code Review 这里只定义如何消费该共享能力。

目标流程：

```text
ReviewChange(base/head revision)
          ↓
read current KnowledgeSnapshot
          ↓
check compatibility / freshness
     ┌────┴─────┐
   fresh      stale/unknown
     ↓             ↓
continue      refresh / rebuild
                    ↓
               publish snapshot
                    ↓
                 continue
```

对 PR diff 的 review context，应明确记录使用的 snapshot identity。

如果 refresh 失败且 snapshot 明显不适用于目标 change，不得静默把 stale knowledge 当作 fresh evidence。

---

## 8. Review Context Builder

Code Review 复用 P3 Task / Change Retrieval & Context Builder。

输入：

- changed files / hunks；
- changed symbols；
- PR metadata；
- KnowledgeSnapshot identity。

候选 context 至少可来自：

- changed source；
- target symbol declaration / definition；
- callers / callees / references；
- inheritance / override；
- ArkUI role / framework relation；
- creation / property / layout / overlay trace（与 change 相关时）；
- existing tests / tested-symbol mapping；
- similar implementation / test evidence。

输出结构化 `ReviewContextPack`，并保留：

- changed evidence；
- supporting repository evidence；
- provenance；
- ranking / inclusion reason；
- token budget。

不允许把整个 ArkUI graph 或全仓源码直接塞给 LLM。

---

## 9. Code Review Skill

Code Review Skill 描述 Review workflow 与 reasoning checklist，不承担 platform polling、knowledge persistence 或 HTTP 细节。

逻辑流程：

```text
ReviewContextPack
       ↓
understand change intent / affected behavior
       ↓
review by category
       ↓
validate evidence / impact
       ↓
produce zero or more ReviewFinding
```

第一版至少包含以下 category。

### 9.1 Stability

关注包括但不限于：

- null / invalid state；
- range / boundary；
- lifecycle mismatch；
- duplicated registration / missing cleanup；
- async/callback state transition；
- error path / recovery path；
- crash-prone assumptions。

### 9.2 Memory / Lifetime

重点结合 ArkUI C++ ownership/lifecycle context 关注：

- strong/weak reference 使用关系；
- raw pointer lifetime；
- lambda/callback capture；
- registration/unregistration 对称性；
- owner/callback cycle；
- async task 持有对象生命周期；
- evidence-supported leak / dangling risk。

不能仅凭出现 `RefPtr`、`WeakPtr`、裸指针等文本模式就宣告泄漏；finding 必须有 supporting evidence。

### 9.3 Functional Correctness

关注：

- change 是否遗漏必要分支；
- property/state 是否正确传播；
- Model/Pattern/Property/Layout 等 framework path 是否被破坏；
- 修改与现有同类组件行为是否明显不一致；
- API contract / default state / reset behavior 是否发生无意变化。

### 9.4 Test Impact

结合 Test Mapping / Existing Test 判断：

- 行为变化是否已有测试覆盖；
- 是否新增边界路径但没有相应 UT；
- 修改是否使旧测试假设失效；
- 是否存在可明确指出的 coverage gap。

Code Review 可以建议补 UT；真正生成/修改测试由 UT Development capability 负责。

---

## 10. ReviewFinding Model

Review reasoning 与平台评论文本分离，内部使用结构化 finding。

概念字段：

```text
ReviewFinding
├─ category
├─ severity
├─ confidence
├─ file
├─ source range / line
├─ changed_symbol
├─ title / summary
├─ description
├─ consequence
├─ evidence
├─ related_symbols
├─ recommendation
├─ knowledge_snapshot_identity
└─ provenance
```

具体字段类型、severity 枚举、confidence 语义和 fingerprint 算法在实现 milestone 的 spec 中冻结。

### Core Constraints

- finding 必须定位到具体 change/source evidence；
- finding 的 supporting claim 必须能追溯 P1/P2/P3 evidence；
- 不确定时显式降低 confidence 或不发布；
- 允许返回 **zero findings**；
- 不通过“必须给每个 PR 留评论”的产品要求强迫模型制造问题。

---

## 11. Review Publisher

Publisher 把结构化 finding 转换为 GitCode review/comment。

Publisher 负责：

- inline position mapping；
- summary formatting；
- platform-specific limits / retry；
- finding fingerprint / duplicate suppression；
- publish result tracking。

Publisher 不重新进行代码 reasoning。

第一版应优先：

- 少而准确的 finding；
- 可追溯证据；
- 防止重复评论；
- 当位置映射失败时有明确降级策略（例如 summary 而不是伪造 inline location）。

---

## 12. Configuration Boundary

架构需要支持下列配置概念：

```text
Code Review Config
├─ code host / repository
├─ polling interval
├─ author username filter
├─ knowledge refresh policy
├─ review categories
├─ publish mode
└─ runtime limits
```

例如“每 10 分钟轮询”和“每天刷新知识”属于配置值，而不是写死在 Skill 代码中。

具体 YAML/TOML/env schema 等到对应 implementation milestone 再由 spec 冻结。

---

## 13. Safety, Quality and Failure Semantics

Code Review 的目标不是最大化评论数量，而是最大化有证据、可行动 finding 的质量。

至少坚持：

1. **No evidence, no strong finding**：关键结论必须有 source/repository evidence。
2. **No forced finding**：无问题 PR 可以返回成功且 zero findings。
3. **No duplicate spam**：同一 PR head/finding 不因轮询重复发布。
4. **No stale-knowledge masquerading**：知识 freshness 不满足时显式失败/降级。
5. **No platform leakage**：GitCode 私有 schema 不进入 review reasoning contract。
6. **No full-repo prompt stuffing**：全仓知识通过 retrieval/context 压缩后进入 LLM。
7. **Explicit partial/unknown**：无法证明的 lifetime/functional path 不静默补全。

---

## 14. Evaluation

Code Review evaluation 从 capability 开发阶段同步建立。

Benchmark 至少覆盖：

- Stability issue；
- Memory/Lifetime issue；
- Functional regression；
- Missing/insufficient UT；
- ambiguous/insufficient evidence；
- **No-Issue PR / Change**。

指标至少考虑：

- Finding Precision；
- Finding Recall；
- False Positive Rate；
- Category Accuracy；
- Severity Accuracy；
- Evidence / Provenance Validity；
- Duplicate Comment Rate；
- Review Latency；
- Tool Calls / Token Cost。

Ablation 至少比较：

```text
Diff-only LLM
vs
Diff + Text Retrieval
vs
Diff + Symbol Retrieval
vs
Diff + Code Graph
vs
Full Repository-aware Reviewer
```

---

## 15. Phase Ownership

### P1 / P2

提供 repository facts 和 ArkUI graph，不增加 GitCode polling。

### P3

提供 Change input、Knowledge Snapshot/Freshness、Review Context 所需 retrieval/context 能力。

### P4

提供 Tool/Skill runtime、state、trace 和 read-only agent behavior。

### P5

实现 CodeHostProvider/GitCodeProvider、Review Watcher、author filter、dedup、Code Review Skill、ReviewFinding、Publisher，以及 UT Development / Repair 等 Engineering Capabilities。

### P6

形成正式 Code Review benchmark、ablation 与 hardening。

当前 P2 execution plan 和 Code Graph specs 不因本文新增需求而扩 scope。
