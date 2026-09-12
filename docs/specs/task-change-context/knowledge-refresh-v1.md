# Knowledge Refresh / Rebuild Contract v1

P3-F 的 authoritative production contract。读取、freshness、binding 与 manifest record 的定义仍由 [Knowledge Snapshot Read Contract v1](knowledge-snapshot-v1.md) 负责；本文只定义如何生产并发布这些 record。

## Public entry points

Rebuild 重建 SymbolIndex / Graph / KnowledgeSnapshot，不编译 ArkUI。clangd 是实际 production 运行依赖；compile configuration 指影响解析的 compile database、flags、include paths、macros 等。selected/full 均允许 fallback flags/includes，不强制 compile_commands.json。

`--compiler` / `compiler_executable` 仅是可选 caller-supplied provenance hint，进入 configuration fingerprint；当前不执行、不探测本机 compiler，也不根据其是否安装或可执行阻止 publication。实际 clangd binary/version 仍进入 toolchain fingerprint，实际 semantic configuration 变化仍阻止 no-op。

- `KnowledgeRefreshService.refresh(RefreshRequest)` 是手动调用和未来 scheduler 共用的单次 service 入口。
- `P1P2RefreshBuilder` 是 production build adapter；`ProductionBuildInputs` 从 clangd executable bytes 与 `--version`、可选 compiler hint、compiler flags、include directories、compile database path/bytes、显式 config files（并自动包含 root `.clangd`）、schema 和规则版本生成 `BuildConfiguration`。
- `scripts/refresh_knowledge.py` 是薄 CLI，只解析参数、创建同一个 service 并输出结果；它不包含 scheduler、polling、watcher、Git fetch/pull/checkout 或 retry。
- `scripts/smoke_refresh_knowledge.py` 是独立 acceptance reader：绑定已发布 manifest，并让指定 qualified symbol 依次经过 C1 retrieval、D expansion 与 E materialization；它不参与生产 refresh。

target repository 始终只读。refresh 只写调用方显式提供、且位于 target worktree 外部的 knowledge root。

## One-shot pipeline

一次实际 rebuild 使用现有公开能力，顺序为：

```text
Git revision / dirty / tracked inventory observation
→ RepositoryScanner scope verification
→ SemanticProvider (production default: ClangdSemanticProvider)
→ SymbolIndex + RepositoryTestDiscoverer
→ project_index
→ default_role_mapper
→ extract_framework_relations
→ GraphStore + DomainMap persistence
→ KnowledgeSnapshot construction and public artifact validation
→ atomic KnowledgeManifest publication
```

生产路径不导入 `tests.*` 或 evaluation preparation，不读取 SQLite 私有表，也不消费 clangd 私有 JSON。Provider 的 JSON-RPC 适配仍封装在 P1 `ClangdSemanticProvider` 内。

## Writer and generation rules

同一 knowledge root 使用 `.refresh.lock` 的 exclusive-create lease。第二个 writer 立即返回 `conflict`，不等待、不重试、不读取或改写 manifest。lease 只保护 writer；reader 依赖 P3-B 的 immutable generation contract。

每个实际 attempt 使用新的 `SnapshotIdentity`；index/domain 位于 `generations/generation-<uuid>/`，graph 使用 `GraphStore` 自带的 repository/generation digest 隔离路径。这样避免 Windows 下把两个 64 字符 GraphStore digest 再嵌入 UUID 目录导致超长路径，同时仍保证 index、graph 和 domain 均不覆盖 last usable generation。P3-F 不删除旧 generation；已绑定 session 因此继续读取绑定时的 artifact path。

manifest 通过同目录 temporary file、flush/fsync 和 `os.replace` 原子替换。开始实际 build 前发布 `latest_attempt=building`，同时保留原 `last_usable`；成功完成 source/config revalidation 和 artifact public-reader validation 后，单次发布新 `last_usable` 与 matching succeeded attempt。若任一 build stage 或正式 publication 失败，尽力原子发布 failed attempt，且 last usable 仍指向旧 generation。若 filesystem 本身使 failed publication 也失败，返回双重 diagnostic，不能声称 manifest 已记录 failed。

## No-op and force

`force=False` 只有在 P3-B `PrebuiltSnapshotReader.inspect` 对当前 repository、完整 commit、resolved scope、真实 `BuildConfiguration`、source fingerprint 与 artifact bytes 返回 `can_bind=true` 时才 no-op。因此 revision/source/scope/config/toolchain/rules/schema/compile database/artifact 任一不兼容均进入新 attempt。`latest_attempt=building/failed` 的整体状态不能 bind，也不能 no-op。

`force=True` 跳过 no-op 判定，但不跳过 clean Git、scope、source/config drift 或 artifact validation；即使 revision 相同也产生独立 generation。

## Drift and failure semantics

service 在 build 前与正式 publication 前分别读取 Git commit、porcelain dirty state、tracked inventory 和本次 source inventory hashes/stats，并要求 observation 完全相同；同时重新解析 BuildConfiguration。revision、dirty state、tracked inventory、source bytes/stat、tool binary/version、compile database 或规则/config 发生变化时，本次 attempt failed，不发布新 fresh snapshot。

P3-F 不稳定 checkout，也不执行 fetch/pull/checkout。调用者必须提供已处于目标 commit 的 clean worktree。任一 semantic/test/index/projection/domain/framework/persistence/validation stage 失败会失败整个 generation，不把 partial artifact 发布为 usable。失败 detail 记录 stage/provider 提供的文件信息；full build 不允许吞掉单文件错误后继续宣称完整。

## Selected and full coverage

`SELECTED_FILES` 精确保留调用方分别声明的 semantic/test/text knowledge paths。所有 path 必须是当前 commit 的 tracked file，且 scanner 必须精确解析；显式请求 scanner policy 排除路径时失败，不悄悄删去该请求或把它计为 processed。selected snapshot 永不升级成 full。为覆盖 clangd references/calls 与 framework extraction 可能接触的 tracked header/macro，v1 对 selected build 也保守地 fingerprint 完整 Git tracked source inventory；这是 source/build-dependency provenance，不改变 selected knowledge coverage。

`FULL_REPOSITORY` 不信任调用方文件列表，而从一次稳定 Git observation 推导：

- `SourceFingerprint.files` 与 `tracked_files` 表示完整 Git tracked inventory，包括 generated 等 policy-excluded paths；这些文件变化仍触发 source drift/freshness/no-op 检查；
- 通过 P1 公共 `RepositoryScanner.excluded_directory(RepositoryFile)` 查询配置中明确排除的祖先目录；该查询与扫描共用 `excluded_directories` policy，按原规则大小写不敏感匹配，不读取 scan 结果来猜 exclusion。P1 generated exclusion 没有改变；
- semantic scope 是排除上述路径后，tracked inventory 中 scanner 分类为 C/C++ source/header 的全集；test scope 是其中分类为 test 的全集；
- text scope 保持为全部 tracked paths。scanner 排除只限制 semantic/test 建立范围，不撤销既有 revision-bound text 能力；generated paths 可以是 text-only，但不能冒充 semantic/test coverage；
- scanner 实际返回的 tracked 集合必须与独立推导的支持集合相等；任何应支持文件的遗漏或意外返回 excluded path 都硬失败，diagnostic 列出 missing/unexpected paths。缺文件、不可读等不是目录排除的证据；provider/test discovery operational failure 同样失败整个 attempt，不静默减少 scope。

这里的 full 表示当前 producer + scanner policy 支持的完整范围，不声称穷尽 runtime 行为。scope derivation 版本与实际 excluded-directory policy 进入 production configuration fingerprint，变化阻止错误 no-op。

`RefreshCoverage.exclusions` 保存 typed `PolicyExclusion`：status=`excluded`、reason=`CoverageReason.UNSUPPORTED_BY_POLICY`（`unsupported_by_policy`）、path、受影响 channel 与具体目录原因。每个被排除的 C/C++/test path 记录对应 semantic/test exclusion；非 C/C++ 被 scanner 排除的路径以 channel=null 保留审计信息，不虚构 semantic/test 支持。它们不会产生对应的 semantic/test processed record，但 full text 通道仍可用。selected 的 exclusions 同样审计完整 tracked inventory 的 policy 排除，而非声明这些路径属于 selected scope；selected 显式请求 excluded 路径仍遵循其既有 scanner gate。

`RefreshCoverage.to_dict()` 输出完整 tracked total、支持的 semantic/test/text scope 列表与数量、实际 processed 通道计数、excluded 唯一路径数量与分通道数量、excluded_other_files（channel=null 数量）、逐路径 typed exclusions、framework/failure diagnostics。no-op 保留推导的 scope/exclusions，processed 为零，不把未执行重建当作新处理记录。新 generation 保存相同结构的 `coverage.json`，它是 audit report，不是新增的 P3-B query artifact；是否发布成功仍以 manifest 为准。manifest 的 `BuildScope` 与 `SourceFingerprint` 分别持久表达知识范围与完整源清单，不能相互替代。

## Bounded semantic processing and reporting

生产 provider 使用 P1 的 fixed-scope、两阶段 bounded document lifecycle（见 [P1 semantic normalization](../repository-intelligence/semantic-symbol-normalization.md)），不减少 semantic/test scope、不重启进程清空跨文件索引、不修改 canonical conflict 规则。该 lifecycle 版本和最大 open 数进入 BuildConfiguration，避免旧策略产物错误 no-op。全仓 index/observations 本身仍随知识规模增长，不宣称总内存恒定。

semantic failure 摘要包含 stage、声明文件总数、最多三个 sample 和 provider 的 request/file/process/progress 诊断；不展开声明文件全集。service 对任意 failure 保留最多 4096 字符的首尾摘要，再附 generation report 相对路径。manifest 保持原有 B 模型：限制的是 failure diagnostic，不删减 last_usable 中必须完整的 scope/source inventory。

失败 generation 的 `failure.json` 保存完整错误，`coverage.json` 保存完整逐文件状态和 exclusions；未完成文件不声称已建立知识，每行引用 failure report，绝不重复整段错误。报告通过 streaming JSON atomic write 保存，报告写入失败另行显式返回且不覆盖原始 build failure。报告不能将失败 generation 变成 usable。

CLI 通过 `RefreshCoverage.summary()` 直接生成有界 stdout，不先展开完整报告再截断：输出 scope kind、各通道数量、processed/failed/excluded 数量、最多三个限长 exclusion/diagnostic sample 和 coverage_report 路径。完整 scope/path lists 只在 generation report 中。CLI 参数和退出码不变；selected 使用同一报告规则。

## Cancellation and progress

`KeyboardInterrupt` / Ctrl+C 在 refresh orchestration 内收尾，返回 `RefreshStatus.CANCELLED`，CLI exit code 130。已创建 attempt 使用 `BuildStatus.CANCELLED`、finished_at 和有界 `Build cancelled by user` diagnostic；沿用同一 manifest，不增加第二套 lifecycle。选择明确枚举而不是 FAILED 文本标签，避免消费者猜测取消原因。B 的 freshness 映射见 read contract。

取消前的 last_usable 不变；未发布 generation 保留为不可用 orphan，`orphan.json` 标记 attempt/generation/status/usable=false，并保留 failure/coverage audit。refresh 从不通过扫描目录恢复或 bind orphan，下次新建 generation 从头构建，不 checkpoint/resume、不自动 GC。graph 的独立 generation-keyed artifact 同样不被新 manifest 引用。Ctrl+C 在 atomic publication 已提交后到达时保留 succeeded，不回滚已提交 snapshot。首次 source observation 中的取消也有终态 attempt（revision 可为 null）；在拿锁之前取消则没有新 attempt。

owned clangd cleanup 仍有界，清理异常附加到取消原因、不取代它；SIGINT 在短暂 cleanup/terminal publication/lease release 临界区内延后或合并，防止重复 Ctrl+C 留下 building。manifest/report 写盘本身失败时显式报告，不能宣称已持久化终态；kill/断电不是可捕获取消，本轮不实现 crash recovery。

`<knowledge-root>/progress.json` 是 best-effort 旁路 telemetry，不能作为 publication/bind 权威。schema_version=1；固定字段：attempt_id、generation、phase、current、total、percent、current_file（最多300字符或null）、updated_at（带时区）、status。percent 是当前阶段比例，不是整个 rebuild 的估算；total=0 表示未知/空阶段，percent=null。no-op 指向实际复用的 attempt/generation。

实际阶段为 source_inventory（开始与发布前 source hash 检查）、test_discovery、semantic_prepare、semantic_collect、semantic_relations、canonicalize、symbol_index、graph_build（projection/domain/extraction）、artifact_persistence、artifact_validation、publish。文件阶段报告已完成文件数，例如 2402/14497；relations 报告 symbol 数，无法细分的单次操作使用0/1，不虚构内部进度。P1 公共 `set_progress_observer` 上报 prepare/collect；BuildContext.progress 连接 producer 阶段；GitSourceReader.observe 的可选 progress callback 上报 source hashing。可选 provider 不支持 observer 时仍可报告外围阶段。

同阶段 running 更新最多每2秒写一次；阶段切换和终态立即写。status=running/succeeded/failed/cancelled/no_op。通过同目录临时文件 + flush/fsync + atomic replace 写入，不输出持续 CLI spam，不记录 file list/diagnostics list。旁路 I/O 异常不使 build 失败，返回 bounded reporting diagnostic；磁盘不可写时终态可能无法落盘，必须结合 manifest 判断。writer conflict 不覆盖当前 writer 的 progress。

手动读取即可：`Get-Content var/knowledge/<root>/progress.json`。full refresh 的原 CLI 参数保持不变。

## Validation boundaries

Targeted unit/integration tests覆盖首次发布与 C1–E consumption、no-op、force、失败保留、drift、旧 session、writer conflict、config/tool/rule 变化、selected/full 和 publication failure。真实 ArkUI selected smoke 与 full-repository acceptance 由用户显式运行；P3-F 不自动启动昂贵 clangd build。
