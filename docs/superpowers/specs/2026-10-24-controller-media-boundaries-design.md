# Controller 媒体职责边界设计

日期：2026-10-24。状态：实施、独立任务审阅及最终综合审阅均已通过。
本阶段承接持续重构授权；不要求重复批准，不提交。事实来源为当前脏工作树，既有改动为前置资产。

## 意图与范围

`controllers/_media.py` 把三种不同的协调职责放在同一个类：截图的 Operation 身份与产物交付、录屏的批次保存/重试、诊断命令的输入验证与结果呈现。本次让它们各有明确实现所有者，保留 `controllers._media.ADBMediaMixin` 作为组合入口。收益是修改截图协议时无需遍历录屏重试与设备诊断，独立审阅职责、注册表和 globals；不宣称启动性能提升或消除所有 Controller 耦合。

不改命令、信号、结果文案、状态机、关闭/取消顺序、数据格式、路径规则、参数校验、GUI、模型或用例。尤其不把 `_app.py` 的 Bugreport/ANR 合并进来，不抽取通用协调框架，不增加依赖、版本、CI、线程或资源所有者。

## 方案裁定

1. **采用：三职责子类 + 旧组合类。** 沿用 `ADBAppMixin(ADBAppInstallMixin, ADBAppMonkeyMixin)` 现有模式，职责类继承同一 `_ADBControllerBase`，旧类只组合。保留消费者接口与单一基础初始化；代价是增加三层 MRO 节点，必须证实协议链与反射注册。
2. **不采用：新服务对象/依赖接口替换全部 mixin。** 需要迁移共享 OperationManager、ScreenRecordUseCase、signals 与关闭资源边界，当前收益不足以支持新增状态/协调协议。
3. **不采用：只把诊断搬出去、截图与录屏继续共类。** 风险略低但留下两种独立产物生命周期；现有截图、录屏测试足以分别验收，完整职责拆分更符合本阶段目标。

`diagnostics.py` 保留电池设置/复位与 PID 操作，文档称“设备诊断与控制”而非只读诊断。它们共享轻量参数准入→advanced_model→结果反馈的协调模式；不按几十行再拆 battery/process 模块。`_get_screenshot_dir()` 仍由 base 提供；录屏与日志沿用这个历史命名，不为目录重构更改保存语义。

## 文件与类型所有权

| 文件 | 精确所有者与内容 |
| --- | --- |
| 新 `controllers/media/__init__.py` | 仅中文包说明；不导出/聚合三类、不启动对象、不引入加载钩子 |
| 新 `controllers/media/screenshot.py` | `ADBScreenshotMixin(_ADBControllerBase)`；原 `_media.py:110-456` 的全部 12 个截图方法，包括两个同名协议覆写；唯一 `_operation_handlers={"take_screenshot": "_process_screenshot_operation_result"}` |
| 新 `controllers/media/recording.py` | `ADBRecordingMixin(_ADBControllerBase)`；原 `:461-692` 的 7 个录屏方法、模块函数 `_emit_record_target_finished`；仅三个录屏 `_handlers` |
| 新 `controllers/media/diagnostics.py` | `ADBDiagnosticsMixin(_ADBControllerBase)`；原 `:696-981` 的全部 27 个诊断/设备控制方法、模块函数 `_emit_readonly_diagnostic_result`；仅 14 个诊断 `_handlers` |
| 修改 `controllers/_media.py` | `class ADBMediaMixin(ADBScreenshotMixin, ADBRecordingMixin, ADBDiagnosticsMixin)`；中文兼容说明、三个显式 import、`__all__ = ["ADBMediaMixin"]`；无业务方法、注册字典、构造器或通用动态代理 |
| 保留 `controllers/__init__.py` | 继续从旧 `_media` 导入 `ADBMediaMixin`，公开 `ADBController` 基类顺序和构造器不动 |
| 保留 `_base.py/_app_install.py/_app.py` | 基础装配、反射注册、安装生命周期、协议链实现均不变 |

方法签名、staticmethod、docstring、方法体逐项移动；只允许下列三处类名引用改写：`_auto_pull`、`stop_screen_record`、`_process_stop_screen_record_result` 内 `ADBMediaMixin._submit_recording_pull(self, ...)` 改为 `ADBRecordingMixin._submit_recording_pull(self, ...)`。保留显式类调用，因为旧公开方法被非本类的 `SimpleNamespace` 替身调用，改成 `self._submit_recording_pull` 会改变该调用契约。不通过反向导入 `_media` 解决引用。

只在实际使用它的文件保留 import；类型声明按使用者归位（截图 testing_model/signals/log_service，录屏 advanced_model/signals，诊断 advanced_model）。base 已声明/初始化的共享属性继续来自 base，不新增只为类型检查的假初始化。旧 `executor/last_save_dir` 注解不要求复制：它们实际由 base 拥有，不用于新三类的业务方法。

## MRO、构造与注册不变量

现状 C3（仅 AST 提取基类后用无方法合成类验证，未 import 生产模块）：

```text
ADBController → ADBDeviceMixin → ADBInputMixin → ADBMediaMixin
→ ADBAppMixin → ADBAppInstallMixin → ADBAppMonkeyMixin
→ ADBFileMixin → ADBSystemControllerMixin → _ADBControllerBase → object
```

目标只在 `ADBMediaMixin` 后插入 `ADBScreenshotMixin → ADBRecordingMixin → ADBDiagnosticsMixin`。公共根顺序不变；base 在 MRO 中仍恰好一次。三类和组合类均不定义 `__init__`，仍只运行现有 base 初始化；`ADBMediaMixin.__new__(ADBMediaMixin)` 后手工注入状态的旧用例继续工作。

`_base._build_handler_map` 使用 `reversed(type(self).__mro__)` 与每一类自己的 `__dict__.get(...)`，之后 `getattr(self, handler_name)`。因此禁止在旧组合类复制/汇总子类注册表，也不能给它设为子类字典别名。每个键必须恰好出现在一个所属类的 classdict；通过继承看到同一字典不算新的注册声明。

当前静态全映射是普通 77 项、operation 2 项，均无碰撞。此次媒体普通 17 项必须原样分为录屏 3 项、诊断 14 项；operation 中保留截图和安装两个键。所有键→方法名、绑定实例、普通与 operation 路由方式都保持。诊断键先于录屏键插入字典是 reversed MRO 的自然结果；当前消费者仅 `.get` 查找，没有注册字典顺序消费，不把字典插入顺序作为新增公共契约。

录屏键：`start_screen_record/stop_screen_record/pull_recorded_video`。
诊断键：`dumpsys_meminfo/dumpsys_cpuinfo/dumpsys_battery/top_snapshot/gfxinfo/wakelocks/netstats_detail/battery_set_level/battery_set_status/battery_reset/logcat_filtered/list_processes/kill_process/get_device_uptime`。
对应 handler 名全部沿用旧表；尤其 `device_uptime` 入口的返回键仍是 `get_device_uptime`。

协议链完整保留：

- `_operation_metadata_matches`：Screenshot 对缺 generation 的截图先拒绝；`super()` 经过 Recording/Diagnostics（不覆写）、App，再到 Install 的 claim 与 generation 校验，最终到 Base 的 method/kind/generation 校验。
- `_fail_operation_protocol`：Screenshot kind 用截图终态门面；install/batch_install 继续经 Install 的 `fail_snapshot` 与 `_publish_install_terminal`；generic 继续 Base.finish。禁止显式调用 Base 绕过 Install，禁止把两个同名方法当重复代码删除。
- 完整 Controller 的安装 claim/release/invoke 方法照旧来自 Install；截图单独的旧组合实例没有安装类，super 直接到 Base，这是现有独立测试契约。

## 公开符号与私有 patch 契约

保持：旧 `ADBMediaMixin` 类名、模块入口、继承 base 的能力、所有原方法可通过旧类/实例访问；旧公开 Controller 仍组合它。新类是职责实现入口，不复制旧类来伪造类型一致性。类 identity 只有同一进程中的旧 import 与 Controller 使用对象必须一致；跨版本不承诺新增类 `__module__/__qualname__` 不变。

选择**迁移私有模块 globals patch 到真实所有者**，不新增 clock/timer 注入层，不保留误导性的旧 `datetime` 重导出，不用 `sys.modules` 替换、`__getattr__` 转发、共享 globals 同步或反向 import。

| 现有替换点/调用 | 裁定与测试文件 |
| --- | --- |
| `controllers._media.datetime` 用于截图命名 | 改 `controllers.media.screenshot.datetime`；`tests/test_phase2_screenshot_gate.py:64`，仍从旧类运行截图方法 |
| 同一路径用于过滤日志 | 改 `controllers.media.diagnostics.datetime`；`tests/test_diagnostic_artifact_identity.py:58` |
| `monkeypatch.setattr(_media, "datetime", ...)` | 改 diagnostics 模块属性；`tests/test_diagnostic_artifact_names.py:31`，保留 `_media.ADBMediaMixin.logcat_filtered` 调用 |
| `_media.QTimer.singleShot` 用于截图批次 | 改 `controllers.media.screenshot.QTimer.singleShot`；`test_phase2_screenshot_gate.py` 的六处，保留 Qt context 参数和捕获路径元组 |
| `_media.QTimer.singleShot` 断言录屏不用时长计时器 | 改 `PySide6.QtCore.QTimer.singleShot`；`tests/test_model_media_adb.py::test_recording_start_submits_background_save_once_without_duration_timer`；录屏模块不引入无用 QTimer |
| `_media._emit_*` 私有模块函数 | 搬至各自实现模块；仓库搜索无外部调用，不加旧导出；旧类的信号行为不变 |
| `ADBMediaMixin._submit_recording_pull(controller, ...)` 与其他非绑定调用 | 保留，包括 `tests/test_action_results.py`、`test_recording_publication.py`、`test_diagnostic_artifact_names.py` 的替身调用 |

当前已知消费者是仓库内测试，没有发现外部公开的 globals 替换 API。报告明确此项是内部 patch 地址迁移，不笼统声称旧模块的所有属性完全兼容。

## 验收与限制

行为基线先跑旧测试，结构红灯来自新职责模块尚不存在；不得把现有行为通过解释成修复了 bug。新增测试通过新实现入口与旧组合入口实际提交/路由结果，验证唯一信号与拒绝非法请求；身份相同或 AST 归位只是补充证据。

直接：截图门禁、录屏 Controller 保存重试节点、两个诊断路径/命名测试及新增路由/协议边界测试。关联：完整 Controller 安装协议链、截图 action admission、每设备录屏 ActionResults、现有模型装配信号/注入。混合大文件只取明确节点，不整文件重跑。

实施前后用 AST 对照当前文件的 46 个类方法和 2 个模块函数，忽略位置，只允许上述三个类名替换；签名、装饰器、常量、调用参数和方法体剩余部分必须相同。注册表单独校验无丢键/无碰撞；这个检查不替代运行测试。

主任务在代码稳定后跑 changed-file Ruff/中文注释、root Pyright、文档检查与 diff check。新包静态可达，源码 packaging self-check 用临时 `LOCALAPPDATA/XDG_CONFIG_HOME` 与 offscreen 的子进程环境，保留运行时工具/资源真实查找；不改源码全局配置以取得通过。它仅验证源码导入/工具/资源，不等同 PyInstaller 冻结产物和实机录屏/取消/窗口关闭；不自动构建、不执行真实设备命令。

不把此前全项目已验收的其他脏文件算入此轮。是否全量由主任务依据增量策略决定，拆包本身不自动要求全量。

## 主任务执行裁定

预审通过，详细裁定保存于本阶段忽略目录builder-check.md；本节与正式计划中的补充裁定优先。
