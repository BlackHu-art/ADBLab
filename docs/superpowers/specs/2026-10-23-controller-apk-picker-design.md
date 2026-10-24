# Controller 的 APK 文件选择依赖收敛设计

状态：2026-10-23 已按批准方案完成代码实施与独立审阅；验证结果、既有失败及人工边界见实施计划。
本设计承接[设备上下文独立化](2026-10-22-device-context-design.md)，对应
[实施计划](../plans/2026-10-23-controller-apk-picker.md)。

## 1. 目标与阶段定位

用户目标是渐进式全项目重构，保持现有功能与数据兼容。本阶段进入 Controller 边界整理，
先将 APK 文件选择的 Qt 实现与 Controller 的业务编排分离，使安装、批量安装、APK 分析
能通过显式注入的选择接口测试，不再在业务 mixin 中直接调用 QFileDialog。

这一批只完成 APK 选择交互解耦。后续再分别评估窗口生命周期依赖、Controller 装配与业务用例、
执行器、持久化和目录归并；不把这些方向的具体设计提前视为已批准。

## 2. 实施前代码依据

| 现状 | 依据与影响 |
| --- | --- |
| 公开 Controller 是 mixin 组合门面 | `controllers/__init__.py::ADBController`；没有 `controllers/adb_controller.py` |
| Controller 没有直接导入 gui | 实际交互依赖是 `_app.py::parse_apk_info`、`_app_install.py::install_apk/batch_install_apk` 三次 QFileDialog |
| 界面只有两个对应信号路由 | `MainFrame._device_signal_map/_app_signal_map` 映射批量安装和解析；单 APK 安装仍是保留公共入口 |
| 设备目标在选择文件前固定 | `gui/action_feedback.py::ActionFeedbackPresenter.dispatch` 复制并去重 GUI 提交的目标 |
| 请求在选择文件前进入 running | `ActionResults.run` 创建 request 并在整个同步 callback 内保持 scope；实际模型提交才创建 ActionJob |
| 安装执行已有独立用例 | `_start_install_batch` 复用 InstallBatchUseCase；本轮无需新增一套路径型命令 API |
| window_owner 不只服务文件框 | `_device.py::accept_wireless_connection/restart_adb/_process_restart_adb_result` 仍依赖配对状态和运行时通知 |

现有设计和验收依据参见[架构](../../project-knowledge/ARCHITECTURE.md)、
[应用安装流程](../../project-knowledge/BUSINESS_FLOW.md#3-应用管理与安装批次)。

## 3. 方案比较与选择

| 方案 | 收益 | 代价与结论 |
| --- | --- | --- |
| **注入选择接口，保留 Controller 入口（推荐）** | 集中 Qt 交互；业务测试无需替换 Qt 全局方法；保持现有调用栈 | 公开构造门面暂留默认 Qt 适配，边界明确且可独立验收 |
| GUI 先选择，再调用新增路径型命令 | Controller 入口更接近纯命令 | 要同时迁移信号路由与 ActionResults 包装位置，旧 API 还需兼容壳；当前没有额外消费者，本批不采用 |
| 一次性移除全部 window_owner 和模型装配 | 清理范围更完整 | 涉及配对代次、后台读、重启通知和关闭排空；拆为后续单独设计 |

选择第一种。保留同步选择过程，不新增 GUI 编排器、通用服务容器或事件总线。

## 4. 组件和接口

### 4.1 纯 Python 选择接口

新增 `adblab/application/apk_selection.py`，只依赖标准库：

```python
class ApkFilePicker(Protocol):
    def select_one(self) -> str | None: ...
    def select_many(self) -> tuple[str, ...]: ...
```

单选取消返回 `None`；多选取消返回 `()`。保留原始路径、顺序及重复项，不校验后缀或存在性，
不排序、去重、展开用户目录、规范化分隔符，不记录选择历史。异常原样传播，不能伪装为取消。
接口放在 application，避免导入 `controllers` 包时连带执行其 Qt 门面装配；不修改 application 的包导出。

### 4.2 Qt 适配器

新增 `adblab/presentation/qt_apk_file_picker.py::QtApkFilePicker`：

```python
def __init__(self, parent_provider: Callable[[], QWidget | None]) -> None: ...
def select_one(self) -> str | None: ...
def select_many(self) -> tuple[str, ...]: ...
```

普通 Python 对象，不继承 QObject，不拥有线程、Timer 或后台任务。构造只保存回调，不访问回调、
不创建控件、不打开对话框；两个选择方法仅在 GUI 主线程同步调用。每次选择时重新取得父窗口。

沿用 `QCoreApplication.translate("ADBLab", ...)` 及以下原文，不改翻译资源：

| 参数 | 单选 | 多选 |
| --- | --- | --- |
| 方法 | `QFileDialog.getOpenFileName` | `QFileDialog.getOpenFileNames` |
| 标题 | `Select APK File` | `Select APK files to install` |
| 初始目录 | 空字符串 | 空字符串 |
| 过滤器 | `APK Files (*.apk);;All Files (*)` | 同左 |

适配器只提取返回值中的路径；不持有 Controller、DeviceContext、ActionResults 或模型引用。
不主动检测窗口关闭、改变取消含义或新增结果提交逻辑。

### 4.3 Controller 装配与兼容默认值

公开 `ADBController` 新增一个可选的仅关键字参数：

```python
def __init__(
    self, log_service: LogService, *,
    load_device_history: bool = True,
    apk_picker: ApkFilePicker | None = None,
) -> None: ...
```

显式传入时原样保存对象，使用 `is None` 判断缺省，不能用真值判断替换一个合法的假值对象。
未传入时，只有公开门面在该分支内导入并构造同一个 QtApkFilePicker，父窗口回调在调用时读取
`self.window_owner`。这样保留“先构造 Controller，后设置 window_owner”的旧用法。

`_ADBControllerBase.__init__` 增加必填仅关键字 `apk_picker: ApkFilePicker`，保存为
`self.apk_picker`；其余模型装配、历史加载、信号、锁、线程池及 handler 构造顺序保持原样。
仓库内未发现直接调用该私有构造器的生产入口；通过 `__new__` 装配的测试必须显式补齐依赖。
各 mixin 不创建默认适配器，不保留第二套 QFileDialog 回退路径。

MainFrame 在原 Controller 构造位置创建一个 `QtApkFilePicker(lambda: self)` 并注入；同步启动、
分段启动及 `load_device_history=False` 分支共享同一装配规则。继续设置 window_owner，保留原 signal map。

## 5. 行为和数据兼容契约

1. `install_apk(devices)`、`batch_install_apk(devices)`、`parse_apk_info()` 的参数、返回和信号不变。
2. 安装仍先调用 `_require_devices`，无目标不打开文件框；解析仍不需要设备。
3. 安装单选/多选取消仍发送 `APK selection canceled` 的兼容失败消息；经 ActionResults 时结算
   `failed`。解析取消仍不发该消息、不提交模型，零任务请求结算 `cancelled`。
4. 解析继续接受现存的大小写不敏感 `.apk` 文件；无效文件沿用原失败消息。安装不新增文件校验。
5. 多文件安装保持“文件外层、设备内层”请求顺序；路径不改写，重复文件不去重。
6. GUI dispatch 已固定的设备列表在选框后继续使用；不重新读取 DeviceContext。Controller 直接调用
   仍沿用传入列表的现有语义，不顺便增加另一轮目标去重。
7. 保留 `dispatch → ActionResults.run → Controller → picker → model` 的同步调用栈；选框前不创建
   安装 operation/unit，异步提交沿用原 request/job 归属，不新增 ActionResults.run 或异步续接。
8. 取消、选框异常、提交失败后 scope 正常退出；同 key 重入和关闭前拒绝仍由原入口控制。
9. 不改变安装 owner/generation、失败项重试、结果路由、信号次数、历史预加载、持久化格式或路径。

## 6. 修改边界

- 生产文件：新增上述接口与适配器；修改 `controllers/__init__.py`、`_base.py`、`_app.py`、
  `_app_install.py` 及 `gui/main_frame.py` 的相关装配和三处调用。
- 测试：替换旧 `controllers._app.QFileDialog` patch 为 picker 假对象；将父窗口/翻译断言保留在
  Qt 层；同步两个 MainFrame 构造工厂的显式关键字签名，增加适配器和调用链回归。
- 实施完成才更新 ARCHITECTURE、MODULE_MAP 的现状说明；本轮仅新增本设计、计划及入口链接。
- 不改 `_device.py`、ActionResults、InstallBatchUseCase、async_command、CloseController、DeviceContext、
  DeviceStore、AppSettings、命令执行器、版本、依赖或 CI/CD。

本阶段保持 Python 3.11、PySide6 和现有依赖，不新增生产依赖。
保留现有界面、信号签名、功能路由、JSON/YAML 格式和存储路径。
不新增全局单例、线程、Timer、事件总线或持久化状态。
保留既有未提交修改，生产注释使用中文；本计划不授权 commit、push 或发布。

## 7. 验收与已知验证边界

验收分三层：选择适配器参数/返回值；三个 Controller 入口与默认构造；真实 GUI 信号路由下的
任务作用域、目标快照、取消、异常、重入及关闭前拒绝。具体节点和命令只在实施计划维护。
保留已有安装批次和 APK 结果路由测试的有效业务断言，不以改 patch 为由删除覆盖。

本批改变 GUI 装配导入路径，实施后运行源码 packaging self-check；不因此默认启动 PyInstaller 构建。
原生系统文件框、真实设备安装和实际打包产物仍需人工或专门环境验收。

现有 `test_shutdown_during_modal_submission_does_not_access_cleared_request` 只验证 callback 内
关闭 ActionResults 后能退出，不证明“窗口关闭后文件框仍返回非空路径”的提交安全。该路径列为
关闭生命周期的独立验证缺口；本批不增加关闭过滤来暗中改写返回值，也不宣称已解决此竞态。
若实施测试暴露前置关闭缺陷，应单独记录复现与影响，再评估修复范围；若由本批引入，必须在本批修复。

验收后仍保留 Controller 对 Qt signals 和 window_owner 的依赖，不能表述为 Controller 已完全无 Qt。
