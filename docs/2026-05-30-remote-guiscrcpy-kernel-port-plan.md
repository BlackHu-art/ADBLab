# Remote 内核移植与适配层计划

## 目标

在保留 ADBLab 现有 Remote UI 的前提下，把投屏、遥控、预检、参数组装、进程生命周期等能力沉到 ADBLab 原生 service 层。guiscrcpy 只作为临时参考源码，用来识别行为和交互语义；不把它的 UI、launcher、配置体系或包导入 ADBLab，也不让生产代码依赖 `guiscrcpy.*`。

## 边界原则

- UI 边界：保留 `gui/panels/remote_panel.py` 的 ADBLab 交互入口，只做必要接线和控件补充。
- 内核边界：新增或扩展 `models/remote/`，由 `ScrcpyService`、`RemoteControlService` 和纯函数映射承接行为。
- 进程边界：短命令继续走 `CommandRunner.run()`；scrcpy 长进程继续走 `ProcessRunner.start()`，但只能由 `ScrcpyService` 间接调用。
- 源码边界：不 import、不注册、不打包 guiscrcpy 目录；参考完成后删除本地参考目录。
- 迁移方式：优先按行为重新实现；确有价值的小逻辑迁入时必须改成 ADBLab 命名、ADBLab 类型和现有日志/错误语义。
- 验证边界：每一阶段必须有对应单元测试或命令验证，防止 UI 能点但底层漏接。

## 分层设计

| 层级 | 文件 | 职责 |
| --- | --- | --- |
| Remote UI | `gui/panels/remote_panel.py` | 读取用户设置、显示状态、发出 start/stop/key/gesture 请求 |
| Scrcpy service | `models/remote/scrcpy_service.py` | 版本识别、设备信息、预检、编码器检测、启动/停止 scrcpy |
| 参数构造 | `models/remote/scrcpy_args.py` | 纯函数构造 scrcpy 参数，便于测试 |
| 遥控 service | `models/remote/control_service.py` | keyevent、swipe、通知栏、旋转等设备控制 |
| 映射/坐标 | `models/remote/control_mapping.py` | keycode 表、屏幕尺寸解析、手势坐标计算 |
| 类型 | `models/remote/types.py` | `ScrcpyConfig`、`ScrcpyLaunchPlan`、`PreflightResult` |

## 分阶段实施

### P0 现状隔离

- 明确 guiscrcpy 是参考目录，不参与 import、lint first-party、打包和提交。
- 检查 RemotePanel 是否还直接调用 `subprocess`、`ProcessRunner` 或 guiscrcpy。
- 验证命令：`Select-String -Path gui,models,controllers,core,utils -Pattern "guiscrcpy|subprocess.Popen|subprocess.run"`。

### P1 Scrcpy 启动内核

- 将版本检测、`wm size`、USB 预检、硬件编码器检测、参数构造迁入 `ScrcpyService`。
- RemotePanel 只负责创建 `ScrcpyConfig` 和接收 `ScrcpyLaunchPlan`。
- 启动/停止必须通过 `ScrcpyService.start()` / `ScrcpyService.stop()`。
- 验证点：参数组合、默认值省略、预检失败仍可启动、FPS 解析、service 启停委托。

### P2 遥控适配层

- 将 keyevent 和 swipe 坐标从 UI 拆到 `RemoteControlService`。
- 增加通知栏展开/收起、上下左右滑动、横竖屏旋转。
- 对尺寸获取失败设置安全默认坐标，避免 UI 按钮无响应。
- 验证点：keycode 映射、尺寸解析、手势坐标、旋转 fallback。

### P3 UI 接线收敛

- RemotePanel 不再保存底层 runner，只保存 service。
- UI 事件只调用 service 方法，不拼接 ADB shell 字符串。
- 启动 worker 失败时状态从 Checking 变为 Error；用户中断时回到 Idle。
- 验证点：`_on_launch_ready()` 调用 service.start，`_stop_scrcpy()` 调用 service.stop。

### P4 后续可迁移能力

- 多设备启动策略：保留现有选中设备优先，后续可支持同配置批量启动多个 scrcpy key。
- 无线调试辅助：复用 ADBLab 现有 connect/tcpip 能力，不迁入 guiscrcpy 网络 UI。
- 剪贴板/窗口快捷键：优先使用 scrcpy 参数或 ADB shell 能力，不迁入平台窗口自动化。
- 录制增强：保留 ADBLab 保存路径和命名规则，扩展格式/路径校验。

### P5 清理与文档

- README Remote 功能表同步 service 化后的能力。
- guiscrcpy 参考目录已无生产引用，直接从工作区删除。
- 每次阶段完成后更新本文件的状态和验证结果。

## 整体架构审查

### 当前分层结论

- `gui/`：只负责 Qt 控件、状态显示和用户事件接线。Remote 面板已经不再拼接底层 ADB/scrcpy 命令。
- `controllers/`：仍是 UI 信号与模型调用之间的协调层，Remote 当前不需要新 controller，避免为了单页功能增加空转层。
- `models/`：承接业务能力。Remote 新增 `models/remote/` 是合理的，因为 scrcpy 参数、预检、手势坐标和进程生命周期都属于可测试的业务/服务逻辑。
- `models/base/`：保留统一命令与进程入口，Remote 通过 `ScrcpyService` 间接调用 `ProcessRunner`，符合现有规则。
- `core/`：保留基础设施能力，例如 `ADBBridge`、`LogService`、`AppSettings`。Remote 只依赖 `ADBBridge`，没有绕开基础设施。
- `utils/`：保留路径、元数据、批处理等纯工具，不放业务逻辑。

### core/logger 结论

`core/logger/` 目录没有被 git 跟踪，实际只剩 `__pycache__`，没有可用源码。当前项目日志中心是 `core/log_service.py`，并且 `core/__init__.py`、controller、LogPanel 都从 `core.log_service` 引用。继续保留 `core/logger` 会造成两个日志入口的误解，因此本轮删除该遗留目录，不再给它分配新代码。

### 性能优化结论

- `ScrcpyService.version()` 按 scrcpy 可执行路径缓存版本，避免每次启动都重复执行 `scrcpy --version`。
- `ScrcpyService.build_launch_plan()` 先做设备响应/USB 预检，预检失败时跳过 `wm size`，减少离线设备的等待。
- `RemoteControlService` 缓存 `wm size` 结果，连续手势/通知栏操作不再反复同步查询设备尺寸。
- RemotePanel 在 scrcpy 预检得到 `device_info` 后把尺寸写入遥控 service，首个手势也可直接复用启动阶段的尺寸。
- 旋转/重置旋转会清理尺寸缓存，避免横竖屏切换后继续用旧坐标。

## 防漏检查清单

- [x] 生产代码不 import `guiscrcpy`。
- [x] `guiscrcpy/` 已无生产引用并从工作区删除。
- [x] RemotePanel 启动/停止 scrcpy 走 `ScrcpyService`。
- [x] RemotePanel 遥控按钮走 `RemoteControlService`。
- [x] 参数构造、预检、FPS、手势、旋转有测试覆盖。
- [x] 遥控尺寸缓存、scrcpy 版本缓存和预检失败快路径有测试覆盖。
- [x] `core/logger` 遗留目录审查并清理，日志入口保持 `core/log_service.py`。
- [x] README Remote 小节同步最终说明。
- [ ] 真机验证 Start/Stop、FPS 状态、D-Pad、通知栏、旋转和录制。

## 本轮验证命令

```powershell
py -3.11 -m compileall -q gui controllers models core utils main.py
py -3.11 -m pytest tests
git diff --check
```

## 当前状态

2026-05-30：已完成 P0-P3 的首轮实现和一次架构审查。`models/remote/` 已成为 Remote 的原生内核边界，RemotePanel 保留原有 UI 并通过 service 接线到底层能力。guiscrcpy 参考目录和 `core/logger` 遗留 pycache 已删除；README 已同步架构说明，单元测试和编译验证通过；P4 的能力扩展留作后续增量，真机验证仍需在有设备时执行。

验证结果：

```text
compileall: passed
pytest: 57 passed
git diff --check: passed
production guiscrcpy import scan: none found
```
