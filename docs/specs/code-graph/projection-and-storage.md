# Projection and Storage Specification

对应 P2-B。实现位于 `src/arkui_agent/graph/projection.py` 和 `storage.py`。

## P1 projection

`project_index(index, repository_key=..., snapshot_key=...)` 只消费已构建的 P1 index；不启动 semantic provider、不读 C++ 源码、不执行 test discovery，也不识别 ArkUI role。

| P1 fact | Graph projection | Evidence precision |
| --- | --- | --- |
| Symbol declaration/definition | file → symbol，DECLARE/DEFINE | 原始 P1 source range |
| references(target identity) | reference file → target symbol，REFERENCE | 原始 occurrence；不推断 enclosing function |
| callers/callees | caller → callee，CALL | caller definition，回退 declaration |
| TestFixture/TestCase | 同一 P1 identity 的 test node | fixture/case token range；case 保留 body range |
| TestCase.fixture_identity | fixture → case，TEST | fixture membership |
| TestedSymbolMapping | case → symbol，TEST | case body 中 P1 direct references；不表示覆盖率 |

- TEST 的两种语义由 endpoint kind 和 provenance 区分。不推导 fixture → tested symbol 的传递关系。
- 同一 P1 identity 同时存在于 Symbol 和 test entity 时，test kind/name 优先并合并 anchors；同名不同 identity 保持独立。
- 无法解析的 CALL endpoint 使用 symbol-only node，不伪造名称或位置。
- P1 当前未提供的 INHERIT/OVERRIDE 列入 `GraphSnapshot.unavailable_relations`，不从名称、parent 或文本推断。

## Snapshot

`GraphSnapshot` 是 P2-A records 的规范化快照。它通过 MemoryGraph 校验冲突、合并 evidence 并保持 canonical record order；`snapshot.query()` 返回独立只读查询对象。

snapshot 必须保存 `repository_key` 和 `snapshot_key`。调用方负责将这些 keys 与正确的 repository/P1 snapshot 绑定，并保证 projection 期间 P1 index 不被并发 rebuild。

## Storage lifecycle

`GraphStore` 将 snapshot 保存到：

```text
<runtime>/graph/<sha256(repository_key)>/<sha256(snapshot_key)>/code-graph.json
```

- scope key 经过 UTF-8 SHA-256 映射到路径；文件内容仍保存并校验原始完整 keys。
- JSON 包含显式 schema/projection version 和 canonical records，不写时间戳。同一输入生成相同 bytes。
- `save` 使用同目录临时文件和原子替换；`rebuild` 完整投影成功后才发布。
- rebuild 是全量替换，会移除 stale records；`delete` 幂等且只删除当前 scope 的派生文件。
- 缺失、损坏、版本不兼容、scope mismatch 和 I/O 错误抛 `GraphStorageError`，不能冒充空图。
- P1 query 失败原样传播，不发布 partial graph。
- graph/index/report 均是可重建 runtime data，必须位于 target repository 之外且不进入 Git。

当前 adapter 使用 JSON 全量加载和替换；不提供增量 graph、自动 freshness 检测、跨进程 writer lock 或 crash-durability 承诺。
