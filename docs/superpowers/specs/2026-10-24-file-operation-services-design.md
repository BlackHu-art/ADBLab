# 文件事务纯服务设计

日期：2026-10-24。状态：实施、独立任务审阅及最终综合审阅均已通过。

## 目标与裁定

将 `models/file_explorer_worker.py` 的目录读取、正文读取、远端正文保存、本地正文保存四个完整事务移至单个 `services/file_operations.py`。worker 保留原类、构造参数、QThread/Signal、Event、结果转发及 Qt 日志适配，目录不迁移。收益是四个事务可以在禁止导入 Qt 的进程中用假执行器直接验证，资源归属和命令序列有独立所有者；不是按文件行数拆分。

采用有限执行/取消/值回调，不采用统一返回 DTO：目录成功在临时目录清理后发布，但命令失败在其内部发布；正文 decoded/raw 均在其内部发布。把结果统一延后会改变清理失败的结果数量、同步取消以及页面状态。也不采用通用事件流、操作对象基类、十余依赖 getter 或反向导入 worker。

保留原位是可行的零迁移方案，但四段实现具有完整事务边界且不需要 Qt；仅凭当前 QThread 执行测试会掩盖服务的 Qt 依赖。因此这里的真实分层收益足够。`ADBWorker` 已是薄壳，不再套服务；`TransferWorker` 含 ProcessRunner 生命周期，完整保留。`SafeFileDownload` 仍只由 TransferWorker 调用，四个新事务不需要它，不能为了满足早期审计的概括而增加无用导入或复制实现。

## 文件与职责所有权

| 文件 | 本阶段最终职责/允许变化 |
| --- | --- |
| `services/file_operations.py`（新） | 四事务、正文构造期命令函数、远端 resolve/shell 私有辅助、有限回调类型；局部临时文件与远端 owned 列表唯一所有者 |
| `models/file_explorer_worker.py` | 四原类保持原位，run 委托；TextRead 添加窄 decoded 发布方法；TextSave 日志回调；移出 `_shell/_resolve_target`；按实际残余消费者整理导入 |
| `services/file_explorer.py` | 原协议、路径校验、命令构造、解析、TextPreview 定义唯一所有者；不改、不复制 |
| `services/file_download.py`、`core/exec.py` | 不改；分别保持下载事务与执行基础设施 |
| `tests/test_file_operations.py`（新） | 无 Qt 服务完整 fake 事务、发布/清理/异常顺序、独立子进程导入与执行边界 |
| `tests/test_file_operation_adapters.py`（新） | 原构造期契约、信号参数、decoded 同步取消、原 Event 取消语义 |
| `tests/test_file_explorer_text.py`、`tests/test_file_listing_security.py` | 仅必要私有 patch owner 迁移，保留断言与现有参数矩阵 |
| GUI、监督器、TransferWorker、ADBWorker、其余测试 | 不改；只选确切关联节点验证 |
| 正式 docs / 类型 / packaging 集成 | root 统一负责；本 agent 不改、不执行 |

## 服务接口冻结

模块采用 `from __future__ import annotations`。复用 `services.file_explorer.DirectoryListing/TextPreview` 与 `core.exec.CommandResult/command_outcome`；后者当前导入链无 Qt。禁止 `core.log_service`、models、gui、adblab.presentation、PySide6/qfluentwidgets 导入。新模块导入不创建执行器、不读取当前设备、不启动任务或解析用户数据目录。

```python
CancelCheck = Callable[[], bool]
DirectoryPublish = Callable[[DirectoryListing | str, bool], None]
TextPublish = Callable[[bytes | str, bool], None]
SavePublish = Callable[[str, bool], None]

class RunCommand(Protocol):
    def __call__(self, cmd: list[str], *, timeout: float,
                 cancelled: CancelCheck | None) -> CommandResult: ...

class CaptureCommand(Protocol):
    def __call__(self, cmd: list[str], output_path: str, *, timeout: float,
                 cancelled: CancelCheck | None) -> CommandResult: ...

def text_read_arguments(path: str, use_root: bool, byte_limit: int,
                        completion_marker: bytes) -> list[str]: ...

def read_directory(device: str, path: str, use_root: bool,
                   completion_marker: bytes, *, timeout: float,
                   capture: CaptureCommand, cancelled: CancelCheck,
                   publish: DirectoryPublish) -> None: ...

def read_text(device: str, args: list[str], byte_limit: int,
              completion_marker: bytes, *, timeout: float,
              capture: CaptureCommand, cancelled: CancelCheck,
              decoded: Callable[[TextPreview], None], publish: TextPublish) -> None: ...

def save_device_text(device: str, path: str, content: bytes, use_root: bool, *,
                     timeout: float, run: RunCommand, capture: CaptureCommand,
                     cancelled: CancelCheck, publish: SavePublish,
                     warning: Callable[[str], None]) -> None: ...

def save_local_text(path: str, content: bytes, *, cancelled: CancelCheck,
                    publish: SavePublish) -> None: ...
```

精确私有辅助为 `_resolve_text_target(device, path, use_root, *, capture, cancelled) -> str` 与 `_text_shell(device, command, *, root, cleanup=False, run, cancelled) -> CommandResult`，其参数分别使用上述类型。它们不成为新公共兼容承诺；不设计一个兼容旧 worker 任意私有属性的代理。

worker 每次进入 run 时传 `CommandRunner.run/run_to_file`、`self._aborted.is_set`、既有 Signal.emit。这样构造前或构造后、run 前对执行器类方法的实际现有 patch 都有效；不捕获在构造函数、不用函数默认参数绑定执行器。没有已发现的“执行中热替换执行器函数”消费，不为该私有测试行为增加动态 getter。helper 使用注入的执行器，不能偷偷调用 CommandRunner。

值回调同步执行，使用原 try/with/finally 内相同调用位置；服务不额外 catch 回调异常、不排队、不合并结果。Qt 跨线程排队仍由现有连接类型决定。`decoded` 适配方法只做 `decoded_available = True; decoded_ready.emit(preview)`；`warning` 适配方法只做 `LogService().log("WARNING", message)`。

## 构造期与原接口

六个 worker 的类名、模块、继承、Signal 和构造参数不改；不加 parent、kwargs 或 executor 参数。原 `ADBWorker.result_ready(str,bool)`、Directory/Text 的 `Signal(object,bool)`、Text 的 `decoded_ready(object)` 以及 QThread.finished 均保留。无新 QObject 或线程。

- Directory 构造仍先 super(device, [], timeout=30)，保存 path/use_root，再生成 `ADBLAB_LIST_END_<uuidhex>` ASCII bytes；**命令与路径校验在 run 中**。marker 保留 worker 字段 `_completion_marker`。
- TextRead 仍在 super 前生成 `ADBLAB_TEXT_END_<uuidhex>` bytes，并调用 `text_read_arguments`，后者原样组合 `head_command(path, byte_limit + 1)`、printf marker、root_command，返回 `["exec-out", command]`。命令验证异常仍在构造时发生。super 接收这些 args，timeout 默认 30；随后设置 byte_limit、decoded_available=False。run 接收实际 self.args/marker，不重新构造命令或生成 marker。
- TextSave 原 `(device_ip,path,content,use_root)`、timeout=120、args=[]；LocalTextSave 原 `(path,content)`、device=""、args=[]。都不在构造时执行 IO。
- 所有四事务只传 Event.is_set；不得顺手增加 Qt interruption 联合查询。ADBWorker 原本具有的 interruption 检查原样保留。

## 事务时序与异常冻结

| 事务 | 发布位置 | 清理/取消与异常要求 |
| --- | --- | --- |
| Directory 成功 | TemporaryDirectory 正常退出后，复核 Event，再发布 listing/False | 清理 OSError 时不发成功；原安全本机错误类别 |
| Directory 命令失败 | TemporaryDirectory 内，分类后发布 message/True，再 return | command_outcome cancelled 静默；若退出清理又抛 OSError，且未取消，可再发布固定本机错误。不能强制“一事务只一个结果” |
| TextRead 成功 | TemporaryDirectory 内 decoded 回调（先 flag）后 raw/False | decoded 同步接收者即使 abort，紧接的 raw 仍发布；不得加 gate。退出清理 OSError 可再发 error（此时若 Event 已置位则抑制） |
| TextRead 执行失败 | TemporaryDirectory 内 result.error/True | 执行后只查 Event；不能引入 Directory 的 command_outcome cancelled 分类 |
| TextSave | **远端清理循环所在 finally 内**，全部正常返回后查 Event，再发 error 或 OK | 本地上传临时目录先退出，再逆序远端清理，再终态；提前 return 也执行 finally；不可把终态移至 finally 后 |
| LocalTextSave | **finally 内** unlink 后查 Event，再发 error 或 OK | replace 成功而 unlink 抛 OSError 时仍可能结果失败；保留 error 优先规则；不可把终态移至 finally 后 |

Directory：exec-out 原始字节，读取 `DIRECTORY_LIST_LIMIT + len(marker) + 1`，超限或没有尾 marker 拒绝；仅完整 payload 交给原 `parse_directory_listing`。原 UnicodeError/ValueError/OSError 分类与中文文本逐字保留，stderr 不透传。命令组括号、`&& printf %s` 与 quote 不改。

TextRead：捕获 argv 为 `["adb","-s",device]+args`；只读取 `byte_limit + 1 + len(marker)`，不增加目录式多读一个字节，不调整旧截断语义；尾标记缺失 OSError 固定英文错误。decode 调用原函数，原 UnicodeError/ValueError 捕获仍保留；有 decoded 则先回调，然后发布原 raw bytes。外层只捕获 OSError 并按 Event 抑制。BOM、混合换行、无效 UTF-8、超限只读判定仍属 TextPreview。

TextSave：resolve 的命令构造仍在其 try 之前；exec-out timeout30，读8193、有效长度<=8192，严格 `b"ADBLAB_TARGET:"` / `b"\n:END"`、UTF-8、绝对路径、NUL/CR/LF 检查；不 strip 空白。`InterruptedError` 属 OSError，仍包装成 `OSError("Unable to resolve writable text file")`，外层取消最终不发结果。resolve 临时目录清理完成后才解析并返回目标；token 在成功 resolve 后生成。

owned 中先登记目标同目录 staging，再执行 prepare；root 模式再登记 `/data/local/tmp/adblab-save-<token>`，仍先登记后 prepare。两者 root 标记分别 use_root/False。写本地内容后查取消、push timeout=self.timeout、查取消、publish；content 不进 argv。普通 shell timeout30；cleanup 逆序、timeout15、`cancelled=None`，不受新操作准入或设备切换影响。清理结果失败只调用固定 warning，不覆盖已有 error。

保留异常边界的非理想情况：主体只捕获 OSError，其他异常可在 finally 发出当前 error/OK 后继续传播；cleanup 执行器或 warning 若抛异常，现有循环会中断、后续清理/终态可能不执行。不得新增 catch-all、继续清理策略或成功校验来美化 DTO；这类强化如需做，另立行为变更。值回调抛 OSError 时也仍位于原捕获边界。

LocalTextSave：目标同目录 `mkstemp(prefix=".adblab-save-")`，fdopen 写 bytes；写完查 Event，os.replace；finally 对 temporary unlink(missing_ok=True)，OSError 仅补 `error = error or str(exc)`。保留旧文件与原终态位置，不改直接覆盖，不引入 fsync/新权限策略。

## 实际消费者与私有 patch 裁定

| 旧消费 | 证据与本阶段处理 |
| --- | --- |
| `_completion_marker` | `test_text_reader_preserves_mixed_newlines_on_legacy_shell` 直接读取；字段与字节类型保留，不迁测试 |
| `worker.args` | `test_file_explorer_visual.py::test_file_double_click_menu_reaches_transfer_or_inline_preview` 检查 exec-out/head/marker；构造期冻结，断言不改 |
| `decoded_available` | `gui/features/file_explorer/view.py:137`；保留先 flag 后 decoded 信号，raw 接收可读该 flag |
| `worker._resolve_target/_shell` | 搜索仅 TextSave 内部以及 `test_text_save_cleanup_failure_keeps_success_result` 两个 monkeypatch；生产外部无直接消费者。私有方法移出，测试 patch 新 `_resolve_text_target/_text_shell`，调整假函数签名，保留旧 worker 构造和 OK/cleanup 次数断言 |
| `models.file_explorer_worker.tempfile.TemporaryDirectory` | 仅 `test_directory_reader_reports_safe_failure_category`；改 patch `services.file_operations.tempfile.TemporaryDirectory` |
| `workers.os.replace` | 仅 `test_local_save_runs_off_gui_and_preserves_preview_bytes`；改实际 owner `file_operations.os.replace`，保留阻塞/线程/bytes 断言。worker 中 os 仍供 TransferWorker 用，不应以旧地址偶然生效作为契约 |
| `workers.CommandRunner.run/run_to_file` | 现有许多 fake 通过同一个类 patch，worker 继续运行时注入，均保留；不批量迁移 |
| uuid / tempfile / posixpath / Path globals | 只保留 worker 实际需要的导入：uuid 仍生成两种 marker；os/Path 是否保留据残余代码，不能机械清空。服务自己的保存 token/本地文件依赖属于新 owner，不反向读取旧 globals |

既有旧 worker 公开入口保持；不承诺所有私有 patch 地址永远不变，也不引入动态 ModuleType/globals 代理。源代码证明没有外部消费者不等于所有环境都不存在私有依赖，最终报告明确这一内部地址变化。

## 验收边界

新增无 Qt 导入及完整 fake 执行证明实际分层；原 worker 的信号、取消、页面关闭回归证明适配兼容。源代码 parity 检查逐事务对照命令参数/捕获范围/emit位置，ADBWorker 与 TransferWorker 全类 AST 不变。root 统一执行相关类型、隔离临时数据环境的 packaging self-check、必要 docs 更新。任何测试/自检均不等价于真实设备、真实 GUI 或安装产物验收。以上为设计时的验收约束；实施结果及未验证项见正式实施计划末尾。

## 主任务裁定

范围及补充裁定见正式实施计划；源码自检使用全部数据环境变量隔离，不仅草案简写的两个目录入口。
