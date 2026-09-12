arkui-repository-aware-code-review-service/
├── src/                                      # Agent 产品源码，不展开
│
├── docs/                                     # 持久化、纳入 Git 的工程文档
│   ├── README.md                             # 文档导航及各目录权威职责
│   │
│   ├── architecture/                        # 长期架构、模块职责和依赖边界
│   │   ├── technical-roadmap.md              # 项目长期路线；最高层架构依据
│   │   ├── repository-knowledge-architecture.md # 增量 Repository Knowledge 专题架构
│   │   ├── code-graph-architecture.md        # P2 Code Graph 专题架构
│   │   └── code-review-architecture.md       # GitCode-first 在线代码检视专题架构
│   │
│   ├── specs/                               # 当前已实现能力的规范来源
│   │   ├── code-graph/                       # P2 Graph 已实现 contract
│   │   │   ├── README.md
│   │   │   ├── graph-model-and-query.md
│   │   │   ├── projection-and-storage.md
│   │   │   ├── domain-role-mapping.md
│   │   │   ├── framework-relations.md
│   │   │   └── traces/
│   │   │       ├── creation.md
│   │   │       ├── property-update.md
│   │   │       ├── measure-layout.md
│   │   │       └── overlay-show-close.md
│   │   └── task-change-context/              # P3 已实现 contract；A～E 保留
│   │       ├── README.md
│   │       ├── input-v1.md
│   │       ├── knowledge-snapshot-v1.md
│   │       ├── candidate-retrieval-v1.md
│   │       ├── change-range-mapping-v1.md
│   │       ├── graph-expansion-v1.md
│   │       └── context-candidates-v1.md
│   │
│   ├── exec-plans/                          # 开发阶段和执行状态
│   │   ├── phase-map.md                      # Phase 边界与 Definition of Done
│   │   ├── active/
│   │   │   └── P3-task-change-context.md     # 当前 P3；F1～F6 为增量知识生命周期演进
│   │   └── completed/
│   │       ├── P0-engineering-foundation.md
│   │       ├── P1-repository-intelligence.md
│   │       └── P2-arkui-code-graph.md
│   │
│   ├── decisions/                           # 长期架构决策
│   │   ├── ADR-0001-development-phase-model.md
│   │   ├── ADR-0002-document-authority-and-specifications.md
│   │   ├── ADR-0003-multi-capability-engineering-agent.md
│   │   └── ADR-0004-incremental-repository-knowledge.md
│   │
│   └── evaluation/                          # baseline / frozen annotations / smoke 验收
│       ├── p1-retrieval-baseline.md
│       ├── p2-code-graph-baseline.md
│       └── p3-*                              # P3 A～E 已有标注与验收文件继续保留
│
├── benchmarks/                              # 纳入 Git 的静态评估输入
├── tests/                                   # 产品代码及工程工具测试
├── scripts/                                 # 项目命令行入口
├── .codex/                                  # Codex Hook 配置
├── var/                                     # Git 忽略、可重建的运行数据
├── AGENTS.md                                # Codex 开发、架构边界及文档维护规则
├── pyproject.toml
├── .gitignore
└── .git/

说明：
1. `architecture/` 描述未来/长期目标；`specs/` 只描述已经实现的行为，不能因为路线变更提前改写成未来状态。
2. P3-A～E 的现有 specs、evaluation、fixtures 保留；本次路线变更从 P3-F 开始迁移为 F1～F6。
3. Repository Knowledge 默认维护路线为 dependency-driven incremental refresh；full rebuild 只作为 bootstrap/recovery/incompatible/wide-impact/force fallback。
4. KnowledgeSnapshot 保留，但主要作为 revision/generation/freshness 和知识分片版本的一致性清单；普通查询不扫描所有 shard。
5. 本覆盖包应直接解压到工作区根目录并覆盖同名文件，不要先删除现有 `docs/`，以免删除工作区中本包未重复携带的已完成 specs/evaluation 文件。
