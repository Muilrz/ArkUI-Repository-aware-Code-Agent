# Repository Knowledge Specifications

本目录保留已经实现或在旧 P3-F 工作中形成的 Repository Knowledge contract。当前长期目标仍以
[`../../architecture/repository-knowledge-architecture.md`](../../architecture/repository-knowledge-architecture.md)
为准；旧 incremental lifecycle 已被 provider-based Service 路线取代，不再从本目录继续规划 F2～F6。

当前 contract：

- [Change Impact v1](change-impact-v1.md)：P3-F1 已形成的 repository change、compile context、TU identity、compiler dependency metadata、reverse lookup、semantic fingerprint input 与 affected-TU diagnostics；保留为当前/历史实现事实，不代表 R 路线的必选 contract。

P3-B 已实现的 snapshot 读取行为仍由
[`../task-change-context/knowledge-snapshot-v1.md`](../task-change-context/knowledge-snapshot-v1.md)
定义。旧 full rebuild/publish 实现的当前行为仍保留在既有 task-change-context spec 中，
但不代表 dependency-driven incremental orchestration 已实现或仍在 active roadmap。历史计划见
[`../../exec-plans/superseded/P3-task-change-context.md`](../../exec-plans/superseded/P3-task-change-context.md)。
