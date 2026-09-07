# Domain Role Mapping Specification

对应 P2-C。实现位于 `src/arkui_agent/graph/domain.py` 和 `arkui_rules.py`。

## Contract

`default_role_mapper().map(index, graph)` 返回 immutable `DomainMap`，保留 repository/snapshot scope、ruleset fingerprint、每个 symbol 的 role decision 和有证据的 Component nodes。它不修改 P1 model、identity 或 P2 generic graph。

- `lookup(identity)` 返回该 identity 的完整 decision。
- `members(component)` 只返回无歧义归属到该 Component 的 mappings。
- `to_dict()` 导出 JSON-compatible evidence；输出属于可重建 runtime data。

## Rules

默认 mapper 是经源码审查的有界 catalog，不是任意组件发现器。每条 rule 同时约束 P1 CLASS、完整 qualified name、精确 authoritative header、显式 role 和可选 Component key。

source path 优先使用 definition，缺失时回退 declaration。已知 definition 不在登记文件时，即使 forward declaration 路径匹配也保持 unknown。

Component identity 使用 `NodeIdentity("arkui.component", key)`。至少有一个确定成员时才生成 Component node，其 evidence 来源于已验证成员。rules 按 ID 排序，并对完整配置计算带版本 SHA-256 fingerprint。

当前 catalog 覆盖 Button、Text、Menu 的 Model、Pattern、LayoutProperty、PaintProperty、LayoutAlgorithm、Bridge，以及无 Component 归属的 shared OverlayManager。未登记近名、派生类和 member 不继承角色。

## Decisions

- `recognized`：全部有效 evidence 得到唯一 `(role, component)`；等价规则合并 evidence。
- `unknown`：缺 symbol、kind 不符、无规则或 authoritative source 不匹配；保留 reason 和 graph anchors，不分配 Component。
- `ambiguous`：得到多组 role/component 候选；保留全部候选及 evidence，`resolved=None`，不加入 membership。

P1 symbol 与 graph 的 name/range 不一致时抛 snapshot mismatch。Role mapping 不依赖 LLM，不从名称后缀、共同目录、inheritance 文本或 fixture membership 传播。

具体真实角色预期由 `tests/fixtures/arkui_role_cases.py` 维护。
