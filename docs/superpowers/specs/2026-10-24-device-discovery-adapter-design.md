# 设备发现 Qt 适配器边界设计

日期：2026-10-24。状态：实施、独立任务审阅及最终综合审阅均已通过。
设计阶段仅写指定草案；现已按正式计划实施，验证事实见实施计划末尾记录。

## 目标与裁定

把 `gui/main_frame.py:121-339` 的两个带发现代次的载荷和完整扫描线程移入 `adblab/presentation/qt_device_discovery.py`。旧模块静态重导出原类对象，MainFrame 保持窗口组合、300ms 防抖、发现准入和关闭所有权。

实际收益是扫描循环、运行时准入和原生清理成为完整 Qt 适配器，可独立导入、阅读和测试；不再因扫描测试而必须导入 MainFrame/Fluent 页面树。它仍使用现有 core/models 执行接口，不宣称性能提升、无 Qt/模型依赖或修复既有线程问题。

**推荐同对象静态别名，明确迁移扫描测试的私有 globals patch。** 主任务复核后确认，必须兼容的是功能、数据、公开入口以及类级使用，旧私有 globals 的 patch 地址不是必须永久保留的公共契约。此前以全部旧 patch 地址冻结为前提的十 callback 方案不采用。

## 方案比较与真实成本

| 方案 | 收益与成本 | 裁定 |
| --- | --- | --- |
| 完整线程迁移、旧类同对象静态别名、扫描私有 patch 改实际 owner | 原六方法及两个载荷构造可以完全原样移动；旧类 identity、构造、继承、__new__、class-level start/msleep 都保持；只改五个既有测试文件中的扫描 patch 地址 | 推荐。没有依赖对象、wrapper、反向导入或额外状态 |
| 新类 + 薄兼容子类 + 十 callback | 可永久保留旧 runtime/runner/clock/acquire/release/local-server/drain/close/Event globals 地址；但增加依赖类型、十个字段/闭包、构造参数及每个调用点改写，还使旧类与新类成为父子关系而非同对象 | 不采用。实际消费者仅仓库内部扫描测试；为未要求的私有 patch 地址承担更多生产契约和类型/测试成本，不划算 |
| 全部保留原位 | 零兼容迁移成本，约220行算法继续随大型窗口聚合 | 可接受备选，但当前同对象别名已能以有限测试调整保留行为，扫描职责有完整生命周期和直接测试，归位收益明确 |

不移 MainFrame、CloseController、QtTaskSupervisor、窗口 timer/关闭策略、工具根计算；不抽新状态机/通用依赖注入框架，不改命令、timeout、数据、依赖、版本、CI。新模块不得反向 import gui.main_frame，不用 ModuleType、sys.modules 或 globals 动态代理。

## 精确文件和符号边界

| 文件 | 内容与约束 |
| --- | --- |
| 新 `adblab/presentation/qt_device_discovery.py` | 实际定义原名 `_ScannedDevices`、`_ScanDiscoveryState`、`_ScanThread(QThread)`；完整六方法与类常量/两种 signals 原样移动，不改名，不新增 public API |
| 修改 `gui/main_frame.py` | 显式 `from adblab.presentation.qt_device_discovery import _ScanThread as _ScanThread`，两个载荷同样 `as` 重导出；移除原三类；保持所有 MainFrame 方法原样 |
| 保留 `adblab/presentation/__init__.py` | 不新增聚合导出、单例或初始化逻辑 |
| 保留 `gui/close_controller.py` | 原地登记、停止、断开、等待 MainFrame 持有的同一个线程实例 |
| 新 `tests/test_device_discovery_adapter.py` | 新旧对象兼容、独立导入、真实 globals 替换命中、queued token 与清理顺序 |
| 修改五个既有测试文件 | `test_model_mainframe.py`、`test_qt_adb_runtime.py`、`test_device_scan_cleanup.py`、`test_device_scan_lifecycle.py`、`test_ui_delivery_order.py`：仅扫描职责的 globals patch 迁到新 owner，不改业务断言 |

旧路径与新路径 `_ScanThread is _ScanThread`，两个载荷也 `is` 同一对象；类名、方法、构造签名不变。移动必然改变类 `__module__`，不宣称内部实现路径字符串不变；未发现 pickle、字符串反射加载或 `__module__` 消费者。`__new__` 不新增覆写，Qt 构造/父对象行为不变；不使用危险的未初始化 QThread运行来证明兼容，类对象/同一继承构造机制已保证旧入口与新入口一致。

## 新模块的准确接口与依赖

接口全部来自当前 AST，不新增 callback 类型：

```python
class _ScannedDevices(list[str]):
    def __init__(self, devices: list[str], token: tuple[int, int] | None): ...

class _ScanDiscoveryState(str):
    discovery_token: tuple[int, int] | None
    def __new__(cls, state: str, token: tuple[int, int] | None): ...

class _ScanThread(QThread):
    SCAN_CALL_TIMEOUT_S = 15.0
    devices_changed = Signal(object)
    discovery_state_changed = Signal(object)
    def __init__(self, parent=None, interval_ms: int = 15000): ...
    def stop(self): ...
    def invalidate_snapshot(self) -> None: ...
    def run(self): ...
    def _run_devices_scan(
        self, runner: ProcessRunner, *, deadline: float | None = None,
    ) -> str | None: ...
    def _sleep_interruptibly(self, delay_ms: int) -> bool: ...
```

新模块运行时 import 原来的 subprocess/threading/time、Callable、QThread/Signal、local_server_environment、CommandCancelled/acquire_adb_client、CommandRunner/ProcessRunner/adb_client_lock/adb_runtime、cancel_and_drain_native/close_native_pipes。不改真实执行器类型，不为隔离 import 而造新依赖门面。

`models.adb_device.parse_connected_devices` 继续在 run 首部延迟 import；`core.adb_transport.capture` 继续在版本握手失败且本地服务获准分支延迟 import。新模块只依赖现有 core/models，不能反向到 GUI。

新模块 globals 的语义与旧实现相同：runtime 每轮取得一次并在该轮复用；CommandRunner 每次使用时解析当前绑定；ProcessRunner 首次 native 分支创建，随后在该次 run 里缓存同一实例；time.monotonic 每次读取当前模块绑定；release 每次读取当前 adb_client_lock；Event 仅构造时创建。测试在新模块构造前后替换同名绑定都生效。没有默认参数捕获或 constructor 缓存引入。

## 私有 patch 迁移与窗口隔离

不是搜索替换所有 `gui.main_frame`。以下映射只适用于扫描测试，测试仍从旧路径 import/call `_ScanThread`，证明 alias 实际运行新 owner 的 globals。

| 旧替换点 | 新位置/保留裁定 | 已核实消费者 |
| --- | --- | --- |
| `gui.main_frame.ProcessRunner` 扫描用途 | `adblab.presentation.qt_device_discovery.ProcessRunner` | model_mainframe 的扫描节点；qt_adb_runtime fast/native/admission节点；ui_delivery_order 两个扫描代次节点 |
| `gui.main_frame.CommandRunner.active_count` | 新模块的同属性 | model_mainframe 的 busy/轮询节点；ui_delivery_order 两节点。现有直接 patch `core.exec.CommandRunner` 保持，因为新模块仍引用同一个类 |
| `gui.main_frame.adb_runtime` 或 `setattr(main_frame, 'adb_runtime', ...)` | 新模块同名绑定 | qt_adb_runtime 六扫描节点、cleanup/lifecycle fixtures、ui_delivery_order 两节点 |
| `gui.main_frame.time` 整模块替换 | 新模块 time，保留 core.adb_transport.time 的对应 patch | qt_adb_runtime::test_scan_admission_and_native_process_share_one_deadline；device_scan_lifecycle fixture。两处只推进扫描预算，不调用窗口perf_counter |
| `setattr(main_frame, 'adb_client_lock', lock)` | 新模块同名绑定，transport lock patch 原样 | cleanup::test_scan_waiting_for_client_can_stop |
| `gui.main_frame.ProcessRunner` 窗口终端用途 | **保留旧位置** | model_mainframe::test_main_frame_open_cmd_launches_terminal_via_process_runner 第27行；它调用 MainFrame._open_cmd，不是扫描 |
| `_ScanThread.start/msleep`、整个 `gui.main_frame._ScanThread` | **全部保持** | class-level patch仍指向同一个新实现类；MainFrame._start_scan_thread仍从旧模块全局读取工厂 |
| main_frame.time/threading 的窗口用途 | **保留旧模块import** | 启动 perf_counter 和 _stop_scan_thread 的 Python Thread；只迁扫描测试的patch，不替换窗口代码 |

新模块的 local_server_environment/acquire_adb_client/cancel_and_drain_native/close_native_pipes 继续作为直接 globals，可在新增测试精确 patch，不需要额外provider。现有 core 执行器 ProcessRunner 全局跟踪、popen_native、transport.capture patch 保持原地址。

mainwindow中扫描专用 imports 可以移除：QThread、subprocess、CommandCancelled、acquire_adb_client、local_server_environment、CommandRunner、adb_client_lock、adb_runtime、cancel_and_drain_native、close_native_pipes。保留 ProcessRunner（_open_cmd）、time（perf）、threading（关闭补等）、Callable（其他接口）、Signal（MainFrame信号）。这些归属由当前全文引用核实，实施时再检查防止前置并行更新。

## 行为与生命周期冻结

1. 构造原样传Qt parent，_stop_flag=False，interval最小3000ms，独立Event和初始 discovery_token=lambda:None；SCAN_CALL_TIMEOUT_S=15.0仍可类/实例覆盖。start/msleep不加wrapper。
2. runtime恢复检查先于busy gate，native忙时等完整interval，fast可在普通命令忙时扫描。wait admission与执行共用deadline。runtime获取/request check仍处于原try外，不顺手改变异常处理。
3. native argv=`['adb','devices']`，fast argv=`['adb','devices','-l']`；communicate每片≤0.1秒，PIPE/text/encoding/errors和fallback预算原样。
4. stop只标记，sleep仍按100ms分片；三层finally顺序为 cancel_and_drain_native(proc,timeout=0.5) → close_native_pipes(proc) → runner.release_finished('device_scan',proc)。前一步抛错仍尝试后一步，未确认退出的准确实例继续被跟踪，不终止独立持管道后代/共享服务。
5. Signal(object)传list/str子类与token，失败发unavailable而不发伪空列表；stale保持快照/状态；集合变化、恢复、invalidate、token变化仍可重发相同列表。
6. MainFrame原 `_start_scan_thread/_on_scan_thread_finished/_stop_scan_thread/_on_scan_discovery_state/_schedule_scan_refresh/_publish_scanned_devices/set_continuous_scan` 完全原地；150/6000/3000ms等待与300ms防抖原值。CloseController仍唯一监督owner。

## 验收与限制

新增独立导入测试证明新模块不加载gui.main_frame/qfluentwidgets；新模块现在会直接加载core.exec，不能靠TYPE_CHECKING造虚假边界。如果该检查发现core间接加载GUI，先报告证据，不把修core依赖混入本阶段，也不承诺未测的启动性能。

先跑旧行为基线，再写新入口/alias的结构红灯；绿灯必须包含通过旧类实际命中新globals、queued token完整、准确proc清理顺序。对移动前三类做完整AST parity，类名/方法体都无需变化；MainFrame所有方法同样前后AST一致。测试文件只允许迁import/patch地址，不删除断言。

root统一root Pyright、临时用户数据环境下源码packaging、正式文档和最终审阅。源码self-check不证明冻结产物、真机恢复/取消或实际桌面关闭；不自动构建、不全量pytest、不提交。此只读设计未运行任何验收命令。

## 主任务执行裁定

预审通过，详细裁定保存于本阶段忽略目录builder-check.md；本节与正式计划中的补充裁定优先。
