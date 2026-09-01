# P0 — Engineering Foundation

- **Phase Status:** Not Started
- **Phase Goal:** 建立 Repository Intelligence 可以安全复用的最小工程基础。
- **Source of Truth:** `docs/architecture/technical-roadmap.md`
- **Phase Boundary:** `docs/exec-plans/phase-map.md`

## P0-A — Repository Workspace & Configuration

- **Status:** Completed

### Goal

建立统一的外部 target repository workspace/config 边界，使后续模块无需自行处理 ArkUI repository 路径、规范化和 root boundary。

### Scope

- `RepositoryWorkspace`
- explicit repository path
- `ARKUI_REPO_ROOT`
- normalized absolute root
- repository-relative path resolution
- path traversal protection
- read-only semantics
- configuration errors

### Non-goals

- recursive repository scanning
- C/C++ source file discovery
- Symbol model
- Clang / clangd
- Index
- Retrieval
- CLI
- ArkUI directory recognition
- source editing

### Dependencies

- project package baseline
- `pathlib`
- standard-library test tooling or current project test framework

### Deliverables

建议最小实现位置：

```text
src/arkui_agent/repository/workspace.py
tests/unit/repository/test_workspace.py
```

可根据现有 package 结构做小幅调整，但不应扩展成复杂 configuration framework。

### Acceptance Criteria

1. 可以通过显式路径创建 workspace。
2. root 规范化为绝对路径。
3. repository root 不存在时明确失败。
4. repository root 是文件而不是目录时明确失败。
5. 可以显式调用从 `ARKUI_REPO_ROOT` 创建 workspace。
6. module import 时不得自动读取环境变量。
7. 缺失或空 `ARKUI_REPO_ROOT` 时明确失败。
8. repository-relative path 可以解析为 root 下的规范绝对路径。
9. `..` 等 path traversal 不能逃逸 root。
10. absolute path 不能绕过 root。
11. 默认 read-only。
12. API 不提供 target repository 写入/删除能力。
13. 不绑定 `frameworks/`、`components_ng/` 等 ArkUI 特定目录。

### Tests / Validation

至少覆盖：

- valid root
- nonexistent root
- file-as-root
- environment variable success
- missing environment variable
- empty environment variable
- valid relative resolution
- path traversal rejection
- absolute-path rejection
- temporary repository fixture

### Known Limitations

本 milestone 不负责证明目标 repository 是 ArkUI Ace Engine，也不负责检查 repository 内容完整性。

## P0-B — Test / Fixture Foundation

- **Status:** Not Started

### Goal

建立后续 P1 repository / semantic integration tests 可复用的轻量测试基础。

### Scope

- temporary repository fixture
- small synthetic C++ fixture layout
- unit vs integration test convention
- generated/runtime artifact isolation
- stable local test command

### Non-goals

- 建立大规模 mock framework
- 复制 ArkUI 源码作为 fixture
- Clang semantic integration
- benchmark dataset
- build system abstraction

### Dependencies

- P0-A completed

### Deliverables

建议包含：

```text
tests/fixtures/
tests/unit/
tests/integration/
```

以及必要的测试 helper。

Synthetic C++ fixture 应保持极小，只表达后续 semantic test 所需语言结构，例如：

- namespace
- class
- declaration
- definition
- method call
- inheritance
- simple test-like macro sample

不要提前模拟完整 ArkUI。

### Acceptance Criteria

1. automated tests 可以创建完全隔离的 temporary repository。
2. fixture 不依赖开发者机器路径。
3. fixture 不修改真实 target repository。
4. unit 与 integration test 边界明确。
5. 项目存在稳定的一条全量 test command。
6. generated/runtime test artifacts 不进入 Git。
7. fixture 足够支持 P1 的 scanner/model/provider contract tests。

### Tests / Validation

- fixture creation
- fixture cleanup
- repository layout assertions
- baseline project test command

### Known Limitations

P0-B 只建立测试基础，不保证任何 C++ semantic correctness。

# P0 Definition of Done

P0 只有在 P0-A 和 P0-B 均 Completed 后才能标记 Completed。

完成后应满足：

```text
外部 Repo 可安全打开
        +
测试 Repo 可稳定构造
        ↓
P1 Repository Intelligence 可以开始
```
