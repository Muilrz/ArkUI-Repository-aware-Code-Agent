# Knowledge Snapshot Read Contract v1

P3-B 的 authoritative contract。公开入口为 `arkui_agent.knowledge`；P3-A 输入规范保持不变。此模块只读 manifest、P1/P2 artifacts 和 source workspace，不负责生产、修复、刷新、发布或调度知识，也不执行 retrieval。

## Manifest and identity

`KnowledgeManifest(last_usable, latest_attempt)` 同时保留最后成功 generation 与最新构建尝试；两者均可显式为 null。无 last usable 不会生成空 index/graph。Manifest 必须由调用方显式指定文件位置及 artifact root。

| Typed record | Fields / contract |
| --- | --- |
| `SnapshotIdentity` | snapshot_id、generation、repository、revision；revision 只能是完整小写 SHA-1/SHA-256 Git commit ID 或 null，不接受 HEAD/ref 名称，不自动解析/补齐 |
| `KnowledgeSnapshot` | identity、scope、source、configuration、artifacts、build |
| `BuildScope` | kind=selected_files/full_repository；独立 semantic_files、test_files、text_files，均为排序且无重复的 repository-relative POSIX paths |
| `FileHash` / `SourceFingerprint` | 排序且无重复的 path/SHA-256 列表；整体 digest 对 ASCII-escaped、紧凑 JSON 的 `(path,sha256)` 列表计算 SHA-256；至少覆盖所有 scope files，可额外包括构建依赖 |
| `BuildConfiguration` | configuration/toolchain SHA-256；symbol/graph/domain schema version；text reader、test rules、projection、domain ruleset、framework rules、scanner policy versions；compiler flags、relative include directories、可选 compile database SHA-256 |
| `ArtifactReference` | kind、identity、完整 SnapshotIdentity、artifact-root-relative path、SHA-256、schema_version |
| `KnowledgeArtifacts` | symbols/tests/graph/domain 四个固定角色，以及 TextKnowledge；不能用任意 dict 代替 |
| `TextKnowledge` | identity、SnapshotIdentity、source digest、reader version；P1 text 当前读取 source workspace，不虚构持久化 text database |
| `SnapshotBuild` | attempt_id、status、built_at、producer、provenance=verified_build/unverified、构建所使用的 source digest |
| `BuildAttempt` | attempt_id、target SnapshotIdentity、status=succeeded/building/failed、reason、started_at、finished_at、failure |

时间为带时区的 ISO-8601；结束时间不得早于开始时间。building 没有 finished_at/failure，failed 必须有 failure。last_usable 的 build 必须 succeeded；最新 succeeded 必须匹配 last_usable 的 identity/attempt_id，built_at 在该 attempt 时间范围内。新的 building/failed attempt 必须使用不同 generation，不得覆盖旧 generation。

P1 symbol/test 共用同一个 sealed SQLite 文件、hash、schema version；分别保留知识角色 identity。P2 Graph 的 identity 对应其已有 snapshot_key，DomainMap 的 snapshot_key 必须匹配 Graph，ruleset_identity 必须匹配 configuration。**snapshot_key 是 artifact scope key，不是 Git revision 的证明。** artifact 的 repository/revision/generation/snapshot_id 必须与 KnowledgeSnapshot 完全一致。跨 generation 不作兼容猜测。

P1/domain 文件没有内嵌全局 artifact ID，因此其 identity 必须为 `sha256:<文件摘要>`，由实际 bytes 验证，不能填入任意字符串。TextKnowledge.identity 同样为 `sha256:<source inventory 摘要>`。Graph 保留既有 scope identity，同时额外校验实际文件摘要。

### Provenance trust boundary

P1 index/P2 graph 的历史格式并不自带完整 Git 构建证明。B 不能仅根据文件存在或 snapshot_key 字符串重建这种证明。`verified_build` 是受信生产者/显式验证流程对完整 manifest 的声明：它把 source/revision/config/generation 与这些准确的 artifact bytes 关联。B 验证该声明内部一致性、格式和当前文件/source 校验值，不重新运行 semantic build，也不认证生产者或证明任意手工填写的声明真实。

调用方应只把已有可信构建/验证记录标为 verified_build；缺 provenance 的遗留数据标为 unverified，返回 unknown，等待 F 或独立验证。不能仅修改该枚举来把遗留 artifact“升级”为 fresh。Manifest 不需要也不包含平台私有 PR schema。

## Freshness, coverage and diagnostics

`QueryRequirement(repository, revision, scope, configuration)` 显式声明本次查询的目标与兼容条件。配置/工具指纹由调用方提供；B 不启动 clangd/rg 来猜测版本或自行发现 build configuration。

`FreshnessResult` 包含：

- `state`：fresh/stale/building/failed/unknown，整体读取状态；
- `snapshot_state`：fresh/stale/unknown，单独描述 last_usable 与当前目标的兼容性；
- `coverage`：sufficient/insufficient/unknown；
- snapshot identity、latest attempt、typed diagnostics（Reason enum、detail、可选 artifact kind）；
- 派生 `can_bind`：仅 state=fresh 且 coverage=sufficient 为 true。

| Observation | Rule |
| --- | --- |
| 完整、可信 manifest，artifact/source/config/revision 一致且 clean | snapshot_state=fresh |
| 已知 revision transition、dirty workspace、源内容 hash 不同 | snapshot_state=stale |
| config/compiler/include/compile database/toolchain/rule/schema requirement 变化 | snapshot_state=stale，诊断区分 configuration/toolchain/rule |
| 任一 revision 未知、repository 不匹配、缺 build provenance | snapshot_state=unknown |
| artifact generation/revision 不一致、SHA-256 不符、身份/header/schema 不符、artifact 缺失/损坏 | snapshot_state=unknown |
| source 不可读或观察期间变化导致无法取得一致观察 | snapshot_state=unknown，保留 source_unavailable/source_drift |
| manifest 缺失/损坏/不支持 schema | state=unknown，无 snapshot；manifest_missing/manifest_corrupt |
| 最新 attempt=building/failed | state=building/failed，同时保留独立 snapshot_state 和旧 snapshot identity |
| scope 不满足 requirement | coverage=insufficient；本身兼容的 snapshot 仍然是 fresh |

多个问题可并存，diagnostics 按固定验证顺序保留。兼容性计算 unknown 优先于 stale；若 manifest 的最新 attempt 为 building/failed，其整体 state 优先反映该 attempt，而 snapshot_state 保留兼容性问题。缺失/损坏 manifest 无法可信读取 attempt，因此整体 unknown。

例如 latest=failed、last_usable 的 bytes/source 仍兼容时，结果为 `state=failed, snapshot_state=fresh`，旧 snapshot 完整保留，`can_bind=false`。B v1 使用严格策略，**不提供 stale/degraded/failed-latest 的读取开关**；不会替 P5 判断旧知识是否业务可接受。已建立的 session 使用绑定时的 manifest，后续失败尝试不追溯破坏其固定 generation。

`evaluate_freshness` 是纯判定函数；供 adapter 传入 source observation 与 artifact validation diagnostics。未传 artifact 验证（默认 None）返回 unknown；空 tuple 表示 adapter 已检查且没有错误，不能用于绕过实际验证。普通调用方使用 `PrebuiltSnapshotReader.inspect/bind`。

## Build scope

selected_files 只能证明列出的各通道文件范围；semantic scope 不自动升级为 test scope。要求 full_repository 时，selected_files 永远 insufficient，即使显式请求的文件都命中。full_repository 也是生产者针对 P1/P2 支持事实的完整覆盖声明，不代表穷尽 C++ runtime 语义。

B 不重新扫描/构建语义索引来证明生产者的 coverage 声明；它检查 scope 路径都进入 source inventory，semantic/test 文件都在 P1 公共 files() 返回值内，full_repository 的 source fingerprint 包含全部当前 Git tracked paths。未跟踪/ignored 文件不能作为 revision-bound source inventory。source inventory 可以比知识 scope 更大，以涵盖头文件和其他构建依赖。

### Existing P2 preparation compatibility

人工代码核对：P2 baseline 的 graph preparation 读取 `benchmarks/p1/arkui-button-text-menu.preparation.json`，分别指定 semantic_files 和 test_files；`prepare_p1_index` 只扫描指定集合。B 可原样表达为 selected_files 的 semantic/test 列表，text scope 单独声明，fallback include directories 和 C++ flags 放入 BuildConfiguration。不会将该 preparation 标为 full_repository。

P2 creation/property/layout/overlay preparation 同样按入口/目标文件收集有限 symbol，并以已观察 source ranges 形成 index file 集合；对应 manifest 应列出该 generation 的实际覆盖和依赖指纹，不能把不同临时 indices 合并成同一 generation。该核对不运行 P2 baseline，也不从 frozen expected 生产知识。

## Read-only prebuilt adapter

```python
source = GitSourceReader(explicit_source_root, repository=repository_id)
reader = PrebuiltSnapshotReader(explicit_manifest_path,
                               artifact_root=explicit_artifact_root, source=source)
report = reader.inspect(requirement)
with reader.bind(requirement) as session:
    with session.read() as knowledge:
        reference = knowledge.reference  # 所有 channel 共用
        # C1 以后只在这里消费 index / graph / domain / workspace
    # 成功退出 read 后才能接受/发布该批读取结果
```

`inspect` 返回 typed report；`bind` 不可用时抛 `SnapshotReadError`，其 `.result` 保留同一 diagnostic contract。源 root 必须是调用方明确提供的 Git worktree root；repository 标识与 checkout 的关联由调用方配置，B 不用 remote URL 推测 repository ownership。

`PrebuiltArtifactReader` 校验每个 artifact 的 SHA-256 和文件 stat，使用公开 P1 `SymbolIndex.open_read_only`、P2 `GraphStore.read_file` 和 `read_domain_map` 检查实际内容。读前/读后重复检查检测替换，不执行任何 rebuild。

- P1 read-only 入口使用 sealed/immutable read-only SQLite，检查既有 schema=3 和 quick_check，不执行 CREATE/migration，不创建缺失文件，拒绝 rebuild；WAL/SHM/journal sidecars 不可接受。普通 P1 写入入口保持原行为。
- P2 Graph 复用现有 schema=1 / p1-index-v1 reader。
- Domain reader 消费现有 `DomainMap.to_dict()` 格式，恢复 typed mappings/components/evidence，验证 schema、scope 和 ruleset，不重新运行 RoleMapper。
- B 不直接访问 SQLite 私有表；schema 检查仍在 P1 storage adapter 内。

## Source validation and session lifetime

GitSourceReader 使用只读 Git 命令观察完整 commit ID、tracked path inventory 和 porcelain dirty 状态（含 untracked/submodule 变化）。对 manifest source inventory 逐文件计算 SHA-256；Git revision/status 在 source 读取前后核对，文件 stat 在逐文件及整体读取后核对。source 与 artifact 校验之间也重新观察 source。既有 Git 状态不可靠但 inventory 内 bytes 改变时，hash 仍报告 drift。

成功 binding 固定整个 immutable `BindingReference(snapshot, freshness)`，包括 generation、artifact descriptors、scope/config/source provenance；session 不再读取“最新 manifest”。新的 manifest 指向新 generation 时，旧 session 仍消费旧 generation；旧 artifacts 被删除、覆盖或替换时，旧 session 明确失效，不自动切换。

`session.read()` 在进入和退出时验证固定 manifest 下的 artifacts/source，同时比较绑定时的 file stat（device/inode/size/mtime_ns/ctime_ns）。即使替换为相同 bytes，只要 stat 能检测变化也会失效。每个 read scope 新开/关闭只读 index，graph/domain 使用该 session 初始载入的只读对象。`validate()` 可供长查询设置额外检查点；一旦检测变化 session 被关闭，后续返回 session_closed，必须重新 bind。

调用方不得在 read scope 成功退出前对外提交其结果；不得把 index 或 workspace 读取操作逃逸到 scope 外。session context 退出释放生命周期，`close()` 幂等。查询错误不会被当作成功，退出校验错误同样抛 SnapshotReadError。没有 watcher、锁定外部 writer 或事务化 source checkout。

## Serialization and failure semantics

`dumps/loads` 用独立的 `{"schema_version":1,"record":...}` envelope。每个 typed record 有固定 `type` tag；tuple 为数组、Enum 为字符串、None 为 null，所有 dataclass fields 均显式输出。按 key 排序、紧凑 JSON、保留 Unicode；round-trip 保持模型相等和再次序列化的文本一致。派生 digest/can_bind 不重复存储。

decode 使用白名单并重新校验全部类型/invariants；拒绝未知/缺失字段、未知 enum/type/version、重复 JSON keys、错误标量类型及 bool 冒充整数。模型/JSON contract 失败抛 ManifestError；文件读取入口将 manifest 错误转换为明确 unknown report，不能悄悄选取另一个 manifest 或空 artifact。

`BindingReference` 可序列化用于 evidence provenance，但解码它不创建活的 session、不证明当前仍 fresh；实际查询仍需 reader 校验。

## Limitations and tests

这是检测型一致性保护，不是防恶意 writer 的原子 filesystem snapshot。完全发生在检查点之间且恢复 bytes/stat/Git 状态的变化可能无法检测。read scopes 应有界，长查询显式增加 validate 检查点；未来 F 提供独立 generation 发布。Git submodule/外部头文件等无法完整指纹化的依赖不得冒充已验证范围。

每次 guarded read 会复核 source/artifact hashes 并读取已有格式；成本随声明范围增长。B 不添加 cache/watcher 优化，也不承诺真实 ArkUI 全仓性能。工具/config 指纹和 verified build 声明由可信调用方提供，B 不独立重做构建来验证语义正确性。

测试入口：`tests/unit/knowledge/test_manifest.py`、`tests/integration/test_knowledge_snapshot.py`；synthetic prebuilt helper 在 `tests/fixtures/knowledge_snapshot.py`。覆盖五种状态、revision transition/unknown、dirty/隐式 source drift、混合 artifacts、缺失/损坏/身份不符、scope 独立、config/tool/rule 变化、latest vs last usable、读取中漂移、固定 generation 和 round-trip。只使用 temporary Git/P1/P2 artifacts，无 ArkUI/clangd/rg 依赖。测试执行由 trusted Stop Hook 负责，真实大仓 refresh 不属于 B 验收。
