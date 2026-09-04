---
status: current
last_verified: 2026-09-04
related: [glossary.md, ARCHITECTURE.md, RISKS_AND_DEBT.md]
---

# 项目概览

## 项目目标

ADBLab 是面向 Android 设备调试、应用测试和性能诊断的 PySide6 桌面工具。它把 ADB、scrcpy、
logcat、dumpsys、Monkey 和移植版 MobilePerf 组织成图形化工作台，主入口为
`main.py::_run_gui()`；版本只以 `utils/app_metadata.py::APP_VERSION` 为准。

## 核心用户

- Android 开发、测试和设备实验室人员：连接设备、查看属性、执行应用生命周期操作和收集诊断材料。
- 性能与稳定性测试人员：运行 Monkey、MobilePerf、logcat、bugreport、ANR 和基础性能命令。
- 需要低门槛投屏和远程输入的调试人员：通过 scrcpy 和持久 ADB shell 控制设备。

仓库没有用户研究、权限角色或商业部署资料，因此实际用户规模、组织方式和生产 SLA 均为待确认。

## 主要业务能力

1. 设备发现与连接：轮询 `adb devices`，连接/配对/断开 TCP 设备，读取设备属性并持久化设备列表。
2. 应用管理：安装、卸载、启停、清数据、权限操作、备份/恢复、批量安装、当前前台应用检测和 APK 信息解析。
3. 测试与诊断：Monkey、截图、录屏、logcat、bugreport、ANR、进程/电池/系统信息。
4. 文件操作：浏览设备文件、上传/下载、编辑、复制/移动/删除、权限修改、APK 安装和脚本执行。
5. Remote：启动 scrcpy、查看 FPS、发送按键/滑动/旋转和窗口聚焦。
6. MobilePerf：在隔离子进程中采集 CPU、内存、流量、FPS、FD、线程数和可选 Monkey，输出 CSV/XLSX 与设备信息。
7. 辅助工具：主题/字体/窗口设置（含响应式重排与屏幕适配）、日志面板和结果文件查看。

当前主界面直接使用 qfluentwidgets `FluentWindow`：Home、三个业务宿主页、Tasks、Logs、Settings
组成七个物理页面，Remote 已归入设备与控制。唯一的主左栏以设备、应用、系统三个折叠树分组
承载具体功能叶节点；窄窗由 qfluentwidgets 原生 Flyout 展示同一导航树，内容区不再出现模块 Tab
或“当前功能”下拉。`WorkspaceFeatureHost` 只负责路由、内容栈和会话；面板内部
`AdaptiveCategoryStack` 只保留内容栈职责，其 Pivot/ComboBox 不再显示。设备页复选用于多设备批量
目标；单设备深层功能和 Remote 使用独立会话设备，多个批量目标或无批量目标且多台在线时要求
显式选择，不静默取第一台。Devices
内嵌文件管理及 Remote，Apps 内嵌应用管理和截图结果，System 内嵌实时 Logcat 和性能采集；深层
功能按功能、设备和代次懒创建并复用，短屏上由宿主滚动保证底部动作可达。About 直接位于
Settings，`SidePanel` 只保留面板所有权、共享设备状态和信号兼容职责，不是可见导航。

## 应用类型与边界

- 类型：Qt 桌面应用；MobilePerf、scrcpy、logcat、Monkey 等长任务会派生受控外部进程或线程。
- 入站接口：没有 Web 服务器、HTTP 路由、RPC 服务或消息消费者。
- 数据库：没有关系型/文档数据库和 ORM；持久化使用 JSON、YAML 与结果文件。
- 主要外部边界：Android ADB server/device、scrcpy、可选 `aapt`、Java/JAR、Perfetto 网站（浏览器打开）和本地文件系统；主应用没有出站 HTTP 客户端。
- 主要平台：Windows 是主支持目标并内置 adb/scrcpy；仓库没有 Windows 10/11 的版本兼容矩阵。
  CI 还构建 macOS/Linux，但这两类包不包含 scrcpy，完整功能状态待实机确认。

## 技术栈

| 类别 | 技术 | 证据 |
| --- | --- | --- |
| 语言 | Python；少量 YAML/JSON/TOML/PowerShell/Bash | `*.py`、工作流与配置文件 |
| GUI | PySide6 提供布局、事件、Signal/Slot、QWidget/QDialog/QFileDialog、QThread 与 QThreadPool；通用控件、导航和主题使用 PySide6-Fluent-Widgets；长期任务使用主页面内嵌 QWidget，瞬态消息/输入经过 `gui/dialogs/fluent_dialog.py` | `requirements.txt`、`gui/`、`models/adb_model.py` |
| 配置 | JSON、PyYAML | `core/settings_manager.py`、`models/device_store.py` |
| 外部命令 | ADB、scrcpy、aapt、Java | `core/exec.py`、`core/adb_bridge.py`、`services/remote/`、`models/adb_testing.py` |
| 性能采集 | 移植版 MobilePerf、CSV、XLSXWriter | `services/mobileperf_runner.py`、`mobileperf/android/` |
| 测试与静态检查 | pytest、Ruff、Pyright | `requirements-dev.txt`、`ruff.toml`、`pyproject.toml`、`tests/` |
| 打包/发布 | PyInstaller、GitHub Actions、GitHub Release | `requirements-build.txt`、`ADBLab.spec`、`.github/workflows/Build-exe.yaml` |

## 运行环境

- CI 和 README 的标准解释器为 Python 3.11；仓库内开发环境统一为 `.venv`，完整工具链由
  `requirements-dev.txt` 安装；`pyproject.toml` 的格式/静态检查目标是 Python 3.10 语法兼容。
- Windows 开发运行优先使用仓库内 `scrcpy-win64/adb.exe` 和 `scrcpy.exe`；具体版本以工具本身为准。
- 用户可写数据根目录由 `utils/user_data.py::user_data_root()` 决定：Windows 默认 `%LOCALAPPDATA%/ADBLab`；非 Windows 使用 XDG 配置目录或 `~/.config/ADBLab`。
- 开发模式直接引用仓库资源；PyInstaller onefile 场景由 `utils/runtime_tools.py::bundled_tool_path()` 把长生命周期工具复制到稳定的用户运行时缓存。

## 当前实现边界

- 主窗口固定为 Home、设备与控制、应用与自动化、系统与诊断、Tasks、Logs、Settings 七个页面；
  Remote 位于设备与控制。长期功能会话由 `WorkspaceFeatureHost` 按功能、设备和代次管理；所有在线
  设备均可作为会话候选，已有离线会话继续保留并标记。About 位于 Settings；消息、文本输入、
  短操作表单和系统文件选择器仍为瞬态窗口。
- 打包 CI 当前不运行 pytest；验证策略与覆盖缺口见
  [TESTING_GUIDE](../guides/TESTING_GUIDE.md)。
- 当前未解决的安全、并发、平台和发布问题只在 [RISKS_AND_DEBT](RISKS_AND_DEBT.md) 维护。

项目术语统一见 [glossary.md](glossary.md)。
