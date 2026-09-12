# Repository Change Impact v1

本规范定义 P3-F1 已实现的 Change Detection、Compile Context 与 Dependency Impact
contract。实现位于 `arkui_agent.repository.dependency`。本能力只计算 affected TU，
不重新解析 TU、不写 P1/P2 facts，也不发布 Snapshot。

## Repository change normalization

`RepositoryChange` 使用 canonical repository-relative POSIX `RepositoryFile` 表达
old/new side，支持 `modify/add/delete/rename`。kind 与路径组合必须一致。
`normalize_repository_changes` 去重、拒绝同一 revision side 上互相冲突的路径，并按
old path、new path、kind 返回稳定顺序。rename 的 old/new side 都保留并参与 impact。

该模型是 P1 dependency boundary，不依赖 P3 `FileChange` 或 GitCode schema。上层 adapter
负责把 platform-neutral Change 或 repository diff 转为本模型。

## Compile context and TU identity

`CompileContext` 包含：

- TU source path；
- compile working directory；
- 完整、有序 compiler arguments；
- 对该 command 有语义影响的 configuration input path + content SHA-256；
- identity schema version。

`CompileContextIdentity` 是上述 canonical payload 的 versioned SHA-256。
`TranslationUnitIdentity` 绑定 source path 与 compile-context identity，因此同一 `.cpp`
在 flags、include/search context、macro 或 relevant configuration 改变后是不同的语义
生产/失效单位。同一 source 可以有多个不同 compile context/TU identity，不做一对一假设。

`CompilationDatabaseProvider` 是标准 JSON Compilation Database adapter。它优先读取
`arguments`，也支持 `command`；将 source 规范化到 repository boundary，并对显式声明的
configuration files 计算内容 hash。database 可以位于 repository 内或由调用方显式配置的
外部 build metadata 目录，但其中 TU source 必须位于 target repository。缺失、损坏、重复
exact command、repository 外 source
或非法 entry 返回 `coverage=unknown` 和 typed fallback diagnostic；缺失 metadata 与损坏
metadata 分别报告 `missing_compile_metadata` / `malformed_metadata`，不猜选一个 command。

## Dependency metadata provider

`DependencyMetadataProvider` 隔离 compiler/build backend。provider 输出：

- 每个 exact TU identity 的 `DependencyRecord`；
- compiler-derived repository dependency closure；
- metadata/provider identity；
- `complete/partial/unknown` coverage；
- typed diagnostics。

`MakeDepfileDependencyProvider` 是首个 backend adapter，消费 compiler `-MD/-MMD` 等产生的
Make-style depfile。depfile 的 flattened dependency closure 同时覆盖直接和间接 header；
系统不通过源码文本扫描 `#include` 补齐或宣称完整。repository 外 system/toolchain header
不进入 repository reverse index，并留下有界 diagnostic。任一已知 TU 缺 depfile或 depfile
损坏时 coverage 不是 complete，并给出 safe fallback reason。多 compile context 的 source 必须
按 exact TU identity 绑定 depfile；source-path 简写只允许用于该 source 唯一 TU 的情况。

`ReverseDependencyIndex` 只反转 provider 已证明的 dependency closure：
`repository file -> exact TU identities`。它不推断缺失 edge。

## Affected-TU flow

`DependencyImpactAnalyzer` 同时消费 previous/current compile inventory 与 previous/current
dependency snapshot：

1. normalize repository changes；
2. 对比同一 source 的 old/new TU identity，compile context 新增、删除或变化时纳入相应 TU；
3. `.c/.cc/.cpp/.cxx/.m/.mm` 与 test TU 变化时纳入 old/new side 的自身 TU；
4. header/`.inc` 变化时，对 old/new path 查询两个 revision side 的 reverse dependency；
5. relevant configuration path 变化时纳入声明该 input 的 TU；
6. 合并、去重并按 TU identity 稳定排序；
7. 汇总 dependency coverage 与 fallback diagnostics。

源码 add/modify/delete/rename 没有对应 compile context 时，不能证明 semantic invalidation，
返回 full-rebuild-required diagnostic。header change 在任一 side 的 compile/dependency coverage
不完整时，即使已经找到部分 TU，也返回 `full_rebuild_required`；找到的集合仅是已证明下界，
不能作为 safe incremental 完整集合。非 C/C++ 且未声明为 relevant configuration 的变化保留
`unsupported_changed_file` diagnostic，但不会把普通文档变化自动扩大为 full rebuild。

`DependencyImpact.status` 为：

- `safe_incremental`：affected set 与所需 dependency coverage 可证明完整；
- `unknown`：coverage 无法证明，调用方必须扩大范围或 fallback；
- `full_rebuild_required`：typed diagnostic 已明确要求 fallback。

F1 只返回策略输入。F6 才拥有最终 `NO_OP / INCREMENTAL / FULL_REBUILD` planner decision。

## Semantic fingerprint input

`SemanticFingerprintInput` 的 versioned canonical SHA-256 输入包含：

- exact TU identity 与 compile-context identity；
- TU source 和 compiler-derived repository dependency 的 path/content SHA-256；
- dependency metadata identity；
- semantic producer identity/version；
- semantic schema/index identity；
- fingerprint schema version。

compile arguments、include/search configuration、macros 与 relevant build configuration 已通过
compile-context identity 进入 fingerprint。只有完整输入 fingerprint 相同，后续 F3 才可以判定
semantic shard 可复用；F1 本身不创建或复用 shard。

## Explicit non-goals

- clangd affected-TU reparse；
- Semantic Shard、ownership 或 P1 Delta；
- P2 incremental graph；
- Snapshot Query View/publication；
- refresh planner/scheduler/GitCode polling；
- 以文本 `#include` scanning 冒充完整 dependency metadata。
