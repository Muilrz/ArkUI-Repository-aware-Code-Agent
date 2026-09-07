# Task / Change input v1

## Boundary and API

`arkui_agent.context` 提供 immutable dataclasses、`parse_task`、`parse_unified_diff`、`to_dict/from_dict`、`dumps/loads`。数据构造和解码均检查字段类型及不变量；列表必须显式转成 tuple，枚举不自动接受字符串，整数不接受 bool/float。

这是共享输入 contract，不是最终 Context Pack schema。parser 只依赖标准库和 P1 `RepositoryFile` 的路径验证规则，不读取文件、Git、环境变量、index、clangd 或网络，不调用 LLM，不产出 SymbolIdentity、repository facts 或 retrieval candidates。

```python
parse_task(text, *, repository, target_revision, source_id, hints=())
parse_unified_diff(raw_diff, *, repository, base_revision, head_revision, source_id)
```

revision 参数必须显式传入，可传 `None`，不可省略后自动补全。`repository` 是调用方声明的非空仓库标识，不是自动推断的 checkout 路径；`source_id` 是非空输入来源标识，可为请求编号或调用方指定的 diff 标识，平台私有 schema 不进入本模块。

## Models

| Model | Fields / semantics |
| --- | --- |
| `Task` | `repository`, `target_revision: Revision`, 原始 `text`, 有序 `hints: tuple[Hint,...]`, `provenance`；允许纯结构化 hints + 空 text，text/hints 不可同时为空 |
| `Hint` | `kind` = component/symbol/property/action/test_intent，原样 `value`，`provenance`；只表达声明/提取线索，派生 `resolution` 恒为 unresolved |
| `Revision` | `value: str \| None`；派生 status 为 declared/unresolved；declared 不表示 revision 已存在或已被验证 |
| `Change` | `repository`, `base_revision`, `head_revision`, 有序 `files`, `raw_diff: str \| None`, `provenance`；structured Change 可无 raw_diff，不可无 files |
| `FileChange` | `old_path/new_path: str \| None`, `kind`, 有序 `hunks`, 原样 metadata 行 tuple, `provenance`；同侧文件路径不可重复 |
| `Hunk` | old/new `LineRange`, 原样 header 尾部 `section`, 有序 `DiffLine` tuple, `provenance` |
| `DiffLine` | context/add/delete/no_newline 和 `text`；源码行不包含 diff 前缀或行结束符；no_newline 保留完整 marker 文本 |
| `Provenance` | `source_id`, origin=input/explicit/extracted/diff, 可选 `TextSpan`, 可选 `rule`；extracted/diff 必须有 span 和 rule/version |
| `ParseResult` | status, `value: Task \| Change \| None`, diagnostics tuple, 完整 `raw_input`, 输入 provenance |
| `Diagnostic` | `code`, `message`, `field`；诊断不是 repository evidence |

modify 必须 old_path = new_path；add 只有 new_path；delete 只有 old_path；rename 两侧路径非空且不同。路径不等于 symbol identity。Hunk 的区间包含上下文行，不代表每一行都被修改；精确增删可由 `DiffLine.kind` 分辨，但 P3-A 不做 changed-symbol mapping。

文件/hunk provenance 的 span 指向完整原 diff 对应段（包括 header 和行结束符）；Task hint span 指向原文 value。解析文件/hunk 的 source_id 与 Change 输入一致，span 必须在 raw_diff 内；提取 hint 的 span 必须在 Task text 内且切片严格等于 value。structured provenance 是调用方声明，不视作对外部内容的认证。

## Range coordinate contract

两种坐标具有不同用途，不能混用：

- 源文件 `LineRange` 的 **line/column 都为 1-based**，范围为 **`[start, end)`**，end exclusive。P3-A 只有 whole-line 精度，start_column/end_column 均固定为 1；不生成 C++ token/字节/UTF-16 列位置。
- `TextSpan` 是输入 Python 字符串内 **0-based Unicode code-point offset**，同样 end exclusive；既不是字节偏移，也不是源文件坐标。span 不可为空。

`LineRange.side=old` 绑定 Change 的 base_revision/old_path；new 绑定 head_revision/new_path。Hunk 两侧字段不能互换。P1 SourceRange 同为 1-based 半开区间，但本模型额外保留 side，不强制为不存在的一侧捏造 RepositoryFile。

unified `N,C` 规范化：C > 0 时得到 `[(N,1),(N+C,1))` 且 N >= 1；C = 0 时表示第 N 行之后的 gap，得到 `[(N+1,1),(N+1,1))` 且 N >= 0。省略 `,C` 表示 C=1。

| Unified header side | Internal line interval | Meaning |
| --- | --- | --- |
| `-0,0` | old `[1,1)` | 文件开头/不存在旧文件的插入锚点 |
| `-3,0` | old `[4,4)` | 旧文件第 3 行之后插入 |
| `+0,0` | new `[1,1)` | 开头删除后/不存在新文件的锚点 |
| `+3,0` | new `[4,4)` | 删除后新文件第 3 行之后的 gap |
| `-4,2` | old `[4,6)` | 旧文件第 4、5 行 |

add 的每个 old range、delete 的每个 new range 都必须为 `[1,1)`。两侧都零长度的 hunk 无效。context/delete 消耗 old 行，context/add 消耗 new 行；marker 不消耗行。header count 与 body 必须完全相符。同一文件 hunks 在两侧均按坐标升序且不重叠。parser 不访问源码，因此不证明坐标在实际文件长度内、diff 可应用、revision 内容匹配，或两个远隔 hunks 之间的源码一致。

## Revision absence and unresolved

缺失 revision 使用 `Revision(None)`，其 status 为 unresolved；空白字符串为 invalid_revision。Task 缺 target，Change 缺 base 或 head 时，解析结果仍保留全部合法 text/hints/files/hunks，整体 status=unresolved，并为每个缺失字段给出 missing_revision diagnostic。缺少 JSON 字段属于 malformed schema，区别于明确 null。

不隐式使用当前 HEAD、工作树、另一侧 revision、环境变量或默认 revision；diff `index` metadata 的 blob ID 也不会填入 base/head。调用方显式传入 `HEAD` 等名称仅是 declared intent，不被解析成 commit、不证明 fresh。后续 B/C2 负责验证/binding；不能拿 head 同行号代替 base deletion。结构化 Task/Change 即使脱离 ParseResult 也保留 Revision(None) 及可查询的 unresolved 状态。

hint 的 unresolved 与 revision 的 unresolved 是不同维度：`ParseStatus.OK` 只说明输入语法可用且 revision 已声明，不意味着 hints 已解析、符号唯一或知识可用。

## Deterministic Task parser boundary

v1 只识别以下两条固定规则，不维护已知 ArkUI component catalog：

1. `task-labels-v1`：大小写敏感的 `[component:value]`、`[symbol:value]`、`[property:value]`、`[action:value]`、`[test_intent:value]`。value 不含方括号或换行，去掉首尾空白后必须非空；只记录 value 的精确 span。未识别的标签保留原文。
2. `task-zh-ut-v1`：全文匹配 `给 <component> 的 <property> 属性补 UT`，允许空白和末尾单个 `。.!！`。component/property 仅 ASCII identifier；提取 component、property、原文动作“补”和 test_intent“UT”。例如 `给 MenuItem 的 selected 属性补 UT`。不扩展同义词，不推理否定、代词或条件。

`hints` 参数只接受 origin=explicit 的 Hint；输出先保留显式 hints 的调用方顺序，再保留标签的文本顺序（中文模板按 component/property/action/test_intent）。不覆盖、不合并重复或冲突 hints。相同输入输出相同，无随机、时间戳或外部查询。

`A::Set(int)` 与 `A::Set(float)` 都可以作为 symbol hint 独立保留；不选择 overload、不生成唯一 SymbolIdentity。未知组件与自然语言全文保持不变；没有 hint 不等于无相关代码。后续可以把原文用于 text retrieval，P3-A 不执行该 retrieval。

## Unified diff supported subset

支持完整的 traditional `--- path / +++ path` unified diff，以及 `diff --git a/path b/path` Git unified diff；多文件、多 hunk、context/add/delete、rename（仅 metadata 或包含 edits）、add/delete（包括 mode metadata 声明的空文件）、mode-only 修改均可表达。

- Git header 支持不带引号/空格的 POSIX 路径，严格去除 a/ 和 b/ 前缀；unified header 路径必须与之相符。非 rename 的 Git header 两路径必须一致。Git rename 必须有配对且匹配的 `rename from/to`。
- traditional header 路径按仓库相对路径原样处理，**不猜测去除 a/ 或 b/**；支持空格/Unicode，以及 tab 分隔的 timestamp。`/dev/null` 仅作为无该侧文件的哨兵。
- 支持 metadata：hex blob `index old..new [mode]`、old/new mode、new/deleted file mode、0–100% similarity index、rename from/to；保留原行，不据此声明 revision/facts。mode 变化必须成对，重复/矛盾 metadata 拒绝。
- 支持 LF/CRLF diff 以及最后一行无行结束符。raw_diff 完整保留，DiffLine 去除传输行结束符；不承诺从 DiffLine 推断源文件 CRLF。
- `\ No newline at end of file` 必须紧跟源码行且不能连续重复，对应侧后续不得再有源码内容。
- header body count 不符、缺 header、额外内容、越界/逆序/重叠范围、路径逃逸均拒绝。相对路径复用 P1 canonical POSIX 规则；绝对路径、Windows drive/UNC、反斜杠、`.`/`..`、空路径、重复 separator、控制字符不可接受。不会检查磁盘 symlink，因为不会读取/写入路径。

binary (`GIT binary patch` / `Binary files ... differ`) 与 combined (`diff --cc` / `diff --combined` / `@@@`) 显式 unsupported。Git quoted/escaped/带空格 header path、copy metadata 和其他 Git 扩展也 unsupported。邮件/format-patch preamble、非 unified diff、bare CR 或其他 line separator 不在支持语法内，返回 invalid；不能跳过未知内容伪装成功。一个输入中任何 unsupported/invalid 段使整体拒绝，value=None，保留完整 raw_input，无部分 Change。

## Failure model

| Status / exception | Contract |
| --- | --- |
| ok | typed value，revision 都已声明，diagnostics 为空 |
| unresolved | typed value，所有缺 revision 字段都有 diagnostic |
| invalid | 语法/不变量错误；无 value，保留原输入及 code/message/field |
| unsupported | 已识别但不支持的 diff 形式；无 value，保留原输入及诊断 |
| `InputError(code, message)` | 直接模型构造或解码失败；parser 无法构造 envelope 的错误参数（非字符串输入、无效 source_id）也抛此异常 |

parser 只捕获输入域错误和已识别 unsupported，不吞掉程序错误。missing_revision 只在语法成功后汇总；binary/combined 预检优先拒绝整个 diff，不保证报告同一拒绝输入中所有独立错误。field=input 的 parser 诊断说明输入边界错误，消息不承诺固定文案；code 和 status 可用于调用方分支。

## Serialization

输入 wire envelope 为 `{"schema_version":1,"payload":...}`，只允许 Task/Change/ParseResult 根记录。每个嵌套 record 带 `$type`（类名），dataclass 全部 fields 都写入；tuple 转 JSON array，Enum 转枚举字符串，None 转 null。派生属性 Revision.status/Hint.resolution 不重复存储，解码由 value/模型重新计算；不允许从 wire 注入 resolved 状态。

`dumps` 使用 UTF-8 可表达的 Unicode 文本、保留非 ASCII、按 key 排序、紧凑 separators；array/tuple 的输入顺序和原始文本不变。`loads(dumps(x)) == x`，重新 dumps 得到同样文本，但不承诺恢复调用方原 JSON 的 whitespace/key order。raw diff 的字面 CRLF 和 provenance offsets round-trip 不变。

decode 使用显式白名单，不动态导入类型；严格拒绝未知/缺失字段、未知 type/enum/version、重复 JSON key、错误 scalar 类型（包括 bool 当整数），并重新执行所有模型不变量。缺 revision 必须使用 Revision.value=null，不通过省略字段表达。未来破坏性修改必须提高 schema_version；v1 不猜测迁移，也不冻结后续 Context Pack。

## Contract tests

- `tests/unit/context/test_inputs.py`：中文/未知文本、explicit/extracted provenance、overload、revision absence、typed/immutable models、range、strict JSON 和 round-trip。
- `tests/unit/context/test_diff_parser.py`：多文件多 hunk、双侧坐标、零长度、add/delete/rename、EOF/CRLF、binary/combined atomic rejection、非法路径/range/metadata、revision 与 Change/result round-trip。

这些是手写 synthetic input contract，不是 ArkUI 检索 gold。运行和 milestone 状态遵循 AGENTS.md 与 execution plan。
