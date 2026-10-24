# AppManager 查询服务提取设计

日期：2026-10-24。实施、独立任务审阅及最终综合审阅均已通过。
承接 忽略目录中的 Qt worker 业务边界审计 的 A1/A2，
以当前 `services/apps/helper.py` 和 `gui/features/app_manager/` 已存在的工作树为基线。

## 目的、范围与选择

把 AppManagerWorker 的包信息解析和完整只读查询事务交给 `services/apps/`，让查询预算、
fallback、用户核验及失败语义可用注入执行器独立测试。Qt worker 仍负责线程身份、取消适配、
信号发布、翻译、写操作和归档。收益是形成可直接使用和测试的业务入口，不只是移动正则。

考虑过三种方案：仅搬纯解析函数改动小，但查询事务仍与 QThread 绑定；整体移动 worker 到
presentation 只改变目录且同时扩大兼容风险；本方案把解析和完整查询先抽出，保留 worker
原位，后续再独立处理 actions/archives 与 adapter 归位。推荐第三种，沿用主任务指定阶段边界。
不新增生产依赖，不更改版本、CI、配置、持久化、GUI 工厂、公开类或 Signal。

## 文件与 owner

| 文件 | 本轮责任 |
| --- | --- |
| `services/apps/package_details.py`（新） | 包 token 准入、batch marker 协议、列表与详情的纯值解析 |
| `services/apps/queries.py`（新） | 用户政策、完整列表/快照/批量详情/metadata fallback 查询事务；只消费可调用依赖 |
| `models/app_manager_worker.py` | 显式注入 `_adb`、`_cancelled`、预算选择器、时钟和 metadata loader；保留全部 Qt 身份与写入/归档实现 |
| `tests/test_app_package_details.py`（新） | 精确解析契约 |
| `tests/test_app_queries.py`（新） | 纯服务命令、取消、预算、用户、失败与回调契约 |
| `tests/test_app_query_boundary.py`（新） | 独立解释器阻断 Qt/GUI/models 的导入和 fake 执行验证 |
| 既有 worker 测试的相关节点 | 最少量 adapter 信号与旧 patch 接缝回归 |

一个实施 owner 顺序完成两个服务及 worker 接入，避免多 owner 同时编辑同一 worker。
主任务独占正式 docs 同步、整批 Pyright、源码 packaging 自检和最终集成验收。
`services/apps/__init__.py` 保持轻量，不聚合新服务；app_metadata/app_icons/helper/app_permissions
继续各自拥有协议、传输与权限解析，不复制它们。当前 QThread 不迁目录、不改 parent 或关闭监督。

## 冻结的数据与纯函数接口

新模块使用 Python 3.11 已支持的普通别名，保持现有载荷，不引入 DTO 类层次：

```python
InstalledApp = tuple[str, str, str, str]  # name, package, state, type
PackageDetail = tuple[str, str, str, str]  # package, label, version, installed
AppDetails = dict[str, str]

def is_safe_package(package: object) -> bool: ...
def split_package_detail_sections(output: str, count: int) -> dict[int, str]: ...
def has_package_detail(output: str) -> bool: ...
def parse_installed_apps(package_output: str, disabled_output: str) -> list[InstalledApp]: ...
def parse_batch_detail(package: str, output: str) -> PackageDetail: ...
def parse_app_details(package: str, output: str) -> AppDetails: ...
```

所有函数无 I/O，无 Qt；parse 函数不替调用方判定命令成功，batch/snapshot 调用方先检查
`has_package_detail`，而兼容 `_emit_package_detail` 按既有语义直接解析。

- 包名仍用 `^[A-Za-z0-9_.]+$` 配合 `str(package or "")` 和 fullmatch；不能替换为更严格的
  normalize_android_package。写操作继续复用同一函数，准入集合不变。
- marker 原样为 `__ADBLAB_PKG_BEGIN_{}__` / `__ADBLAB_PKG_END_{}__`。
  去掉行首尾空白后识别 marker，正文保留原行；只有相同索引的结束 marker 封闭片段。
  开始 marker 重置该索引临时正文，非匹配结束 marker 不关闭当前段；沿用既有重复/交错处理。
- 是否有详情仍为 `r"\bversionCode=\d+"` 搜索，不要求匹配目标包块，不顺便收紧协议。
- batch label 用 `nonLocalizedLabel[=:]\s*(\S.+)`，缺失/空值时包尾段原大小写；
  独立详情缺失 label 用尾段 `.capitalize()`。单字符 label、Unicode 分隔符的现有正则行为保持。
- batch 有 versionName 才返回 `name (code)`，否则版本空字符串；安装日期只取 YYYY-MM-DD。
  详情恰好六个 key：`App Name`、`Package`、`Path`、`Version`、`Min SDK`、`Target SDK`；
  Version 为 `name (code code)` 的既有格式，如 `1.2 (code 7)`；缺失值使用 `?`。
  Path 捕获整行剩余文本，不能新增 strip。
- 列表按原顺序保留重复项，最后一个 `=` 后是包名，之前全部重组为路径；按 /data/app/、
  /system/、/vendor/ 顺序分类 User/System/Vendor/Other，名称替换下划线后 capitalize；
  Disabled/Enabled、空包跳过、无 `=` 行的现有行为保持，不新增过滤。

## 查询函数与依赖接缝

`queries.py` 使用 `from __future__ import annotations`。CommandResult、AppMetadata、MetadataBatch
只在 TYPE_CHECKING 下引用现有定义；服务运行时只依赖标准库和 package_details。
`QueryExecutor` 是唯一窄 callable Protocol，用于精确描述关键字，不是 DI 容器：

```python
class QueryExecutor(Protocol):
    def __call__(self, *args: str, timeout: float = 30,
                 cancellable: bool = False) -> CommandResult: ...

Cancelled = Callable[[], bool]
Clock = Callable[[], float]
QueryBudget = Callable[[], float]
MetadataLoader = Callable[[str, Sequence[str], Cancelled], "MetadataBatch"]

class QueryError(Exception):
    """预期查询失败；str(error) 是沿用的可操作错误文案。"""

def validate_loaded_user(user_id: object, *, required: bool) -> None: ...
def parse_current_user(output: str) -> int | None: ...
def read_current_user(*, execute: QueryExecutor, cancelled: Cancelled,
                      timeout: float) -> int | None: ...
def bind_current_user(expected_user: int | None, *,
                      read_user: Callable[[], int | None],
                      cancelled: Cancelled) -> int | None: ...
def load_installed_apps(user_id: int, *, execute: QueryExecutor,
                        cancelled: Cancelled) -> list[InstalledApp] | None: ...
def read_package_snapshot(package: str, part: Literal["details", "permissions"], *,
                          execute: QueryExecutor, cancelled: Cancelled) -> str | None: ...
def load_package_details(packages: Sequence[str], *, execute: QueryExecutor,
                         cancelled: Cancelled, query_budget: QueryBudget, clock: Clock,
                         on_detail: Callable[[PackageDetail], None],
                         log: Callable[[str], None], deadline: float | None = None) -> None: ...
def load_metadata_with_fallback(device_id: str, packages: Sequence[str], *,
                                expected_user: int | None, execute: QueryExecutor,
                                cancelled: Cancelled, query_budget: QueryBudget, clock: Clock,
                                metadata_loader: MetadataLoader,
                                on_metadata: Callable[[AppMetadata], None],
                                on_detail: Callable[[PackageDetail], None],
                                log: Callable[[str], None],
                                failure: Callable[[str], None]) -> None: ...
```

不新增自有 CommandResult 或 MetadataBatch，不接受 worker/self、Signal 或 QWidget。callback
只收到值，service 不持有它们到函数返回之后，不创建线程、Timer、单例或后台任务。
Python 3.11 的类型别名仍在运行时求值；TYPE_CHECKING 下的类型在别名里必须使用字符串前向引用，
不能只依赖 future annotations 避免 NameError。函数/Protocol 的注解由 future annotations 延迟。
`clock` 和 `metadata_loader` 必须显式提供，不通过默认参数提前绑定模块函数。
worker 在调用时传 `monotonic` / `load_app_metadata`；query_budget 传零参 lambda，内部才调用
`query_timeout(self.device_ip, 5)`，确保只在真正开始 detail 查询时选择预算，metadata 成功时不调用它。
所有设备参数通过已有 `_adb` 固定，service 不能重新读取全局设备。

## 用户政策与错误语义

`validate_loaded_user` 是输入身份准入唯一所有者：required=False 时允许 None；其他值必须
`type(value) is int and 0 <= value < 2**31`，拒绝 bool。非法值抛 QueryError：
`尚未确认应用所属用户，请刷新应用列表后重试。`。当前 run 在已识别 operation 且未取消后调用它，
required 的六个写操作集合保持原样（含 backup/restore）。未知 operation 仍静默不执行。

`parse_current_user` 只接受 strip 后 1..10 位 ASCII 数字及上述范围；失败返回 None，不猜 0。
`read_current_user` 执行一次 `shell am get-current-user`，cancellable=True；取消、失败或无效输出
返回 None。`bind_current_user` 调用 read_user 一次，优先检查取消后返回 None；未知用户抛
`无法确认设备当前用户，请检查设备并刷新应用列表。`，与 expected_user 不同则抛
`设备用户已切换，请刷新应用列表后重试。`；成功返回确认用户。
共享范围谓词可为 queries 私有函数，禁止 worker 再保留一份数值政策。

run 仍在 dispatch 前绑定除 load_metadata_batch/load_icon_batch/load_detail_batch 外的 operation。
因此列表/快照查询函数消费已绑定 user；准入与查询分别是完整可复用边界，不进行第二次用户探测。
三个 batch 本轮绝不新增 `am get-current-user`。metadata 身份来自记录；有 expected_user 时
逐条比较，错用户发 failure 后继续其他记录。None 时不读取 item.user_id，以保留既有 fixture 与
无预绑定消费行为。图标 user/fingerprint 传递维持现状，不加入本服务。

列表：先 -f 后 -d，两条命令同一个显式 --user，timeout 维持默认 30，均 cancellable=True。
取消返回 None，空列表成功返回 []。第一条失败抛 `Failed to list apps: {error or 'adb command failed'}`，
error 仅使用原 error.strip；第二条失败抛 `Failed to read disabled app states; refresh to retry`。
adapter 保留列表原有 try 范围：QueryError 转 `_report_failure(str(error))`；其他 Exception
仍以 `Error: {error}` 报错，不为其他查询新增 broad catch 或伪成功结果。

快照：无效包抛 `Invalid package: {package}`；一次 dumpsys、timeout 默认 30、cancellable=True。
取消返回 None；命令失败或没有 versionCode 抛 `Failed to read app {part}; retry after checking the device`。
成功只返回同一次原文，权限仍调用 services.app_permissions，不能查询第二次。

batch 查询失败只发既有 log，不提升为 operation_feedback；取消和耗尽预算静默结束，不抛异常。
metadata loader 的异常仍向上传播；正常坏协议/超时由原 loader 返回空结果，不自行解释为 unsupported。
所有输出文案、级别和调用次数保持；本轮不增加通用错误码/事件流。

## deadline、fallback 与结果时序

1. 普通 detail 在非空且未取消后调用 query_budget 一次；无外来 deadline 时用
   `clock() + max(command_budget, len(packages) * 2)`，长度是过滤前的原列表，不能去重。
2. 过滤无效包时保持原日志。batch shell 使用完全相同的 echo/dumpsys/echo 与 ` ; ` 拼接。
   timeout 是整段 deadline-clock()，不截成 command_budget；取消/非正余量不发命令。
3. 成功 batch 按请求顺序处理完整片段；有 versionCode 的立即 on_detail；未闭合才加入 fallback。
   完整但无版本字段不重试、不发布空值。每 i%10==0 发原 `Details: i+1/N` 日志。
4. 命令失败、取消或预算耗尽不启动 fallback。逐包 fallback timeout=min(command_budget, remaining)，
   失败记录既有失败日志并停止整批；成功但缺版本字段只跳过该包。到 deadline 恰好完成的成功包
   仍按现有行为发布，只在下一条命令前再判剩余时间，不能新增完成后超时丢弃。
5. metadata 初始 deadline=clock()+30.0；调用 loader 一次。只有 unsupported 且 records 为空并
   clock()<deadline 时调用同一个 load_package_details，传原 deadline；不重建预算。
   有记录即不走 fallback，包括 unsupported=True 且存在记录。记录按 values 顺序逐条发布。
   `len(records)<len(set(packages))` 才发原缺失日志；错用户记录仍计入原 records 长度。
6. 保留旧检查的具体位置：metadata 在每条记录的身份校验之前检查一次；detail 在每条循环入口
   与解析前分别保留原检查，解析完成后不新增门禁。纯发布 adapter 只映射及发送，不再次检查。
   批量记录间取消保留此前成功条，不改成全批原子交付，也不在本轮收紧取消语义。

既有信号顺序保留，尤其不能把“更严格取消”混入本轮：

- 列表：`Fetching installed apps...` → 两次查询 → `Loaded N apps.` → 一次取消门禁 →
  user_context_loaded → apps_loaded。当前两信号间没有再次取消门禁，保持原样。
- snapshot：查询成功 → user_context_loaded → details → permissions；detail/permission 各自
  现有发布门禁有效，user 信号同步回调取消可阻止后两者，details 回调取消可阻止 permissions。
- app_details 只 user→details；permissions 只 user→permissions；失败先 log_message 后 error feedback。
- metadata 仅既有 metadata/legacy 结果回调和日志，不新增 user_context_loaded 或 operation_done。

## 旧接缝与 adapter 最终形状

保留 `_adb` 原签名和实现；所有新查询都接收本次的 bound method，所以 patch.object(worker, '_adb')
仍生效。`_read_current_user` 委托 queries.read_current_user，`_bind_current_user` 调
queries.bind_current_user(read_user=self._read_current_user, ...)，成功回写 self.user_id，失败报原文案。
写操作/restore 的多次 `_bind_current_user` 继续走同一政策和现有实例 patch 接缝。

`_load_apps/_load_detail_batch/_load_metadata_batch/_read_package_snapshot` 保留窄适配 wrapper。
`_emit_package_detail`、`_emit_app_details` 仅做纯解析调用和原取消门禁/emit；前者仍有视觉测试直接消费。
新的 `_publish_package_detail(detail: PackageDetail)` 与 `_publish_metadata(item: AppMetadata)`
仅负责原有信号参数/五字段 dict 映射和发送，不增加取消检查；服务保留原检查时点。
旧 `_emit_package_detail` 的直接调用仍在解析前检查取消。发布适配不包含解析、deadline 或身份政策。
`_safe_pkg` 使用显式同对象 alias 到 is_safe_package，供未迁的 actions/archives 使用。

`_load_detail_batch_once` 搬为 queries 私有协作者，精确签名为
`_load_package_details_once(packages: Sequence[str], *, deadline: float, execute: QueryExecutor,
cancelled: Cancelled, clock: Clock, on_detail: Callable[[PackageDetail], None],
log: Callable[[str], None]) -> list[str]`；返回仅未完整片段的包，失败/取消/耗尽返回 []。
完整事务只在 service 内调用它；旧 worker 该方法以及无消费者的 `_has_package_detail` /模块 `_split...` 可在
核实当前调用消失后移除，不建立永久私有兼容层。不为 patch 模块任意属性新增 globals/ModuleType 代理。
`module.monotonic`、`module.query_timeout`、`module.load_app_metadata` 的现有测试 patch 因显式注入
仍有效；服务新测试直接注入，不把所有旧测试搬成只检查转发。旧公开类路径和 GUI 工厂完全不变。

## Qt 与验证边界

仅保证 package_details/queries 的导入和注入 fake 依赖的执行不需要 Qt、GUI、models。
`core.exec` 是文件 `core/exec.py`，`_log_if_slow` 在函数内导入 core.log_service（后者依赖 PySide6）；
真实 `_adb`/真实 metadata loader 经 CommandRunner 的执行路径仍可能触发 Qt 日志。
因此不声称真实设备查询在任意无 Qt 环境可运行，也不在本轮重构执行核心/日志。

验收以计划列出的纯服务与精确 worker 节点为准；主任务一次运行受影响生产路径 Pyright、
源码 packaging 自检与文档检查。自检用独立临时 LOCALAPPDATA/XDG_CONFIG_HOME，不能触碰真实配置。
不重跑整个 test_model_apps/test_app_manager_visual，也不因已有大工作树而触发全量。
真实 Android 多用户/OEM 输出/ADB 中途取消、真实 GUI 关闭以及 PyInstaller 产物仍需另行验收；
mock、离屏信号和源码 packaging 自检不证明这些实际环境。

## 主任务执行裁定

预审通过，详细裁定保存于本阶段忽略目录builder-check.md；本节与正式计划中的补充裁定优先。
