---
status: current
last_verified: 2026-08-27
related: [glossary.md, ARCHITECTURE.md, RISKS_AND_DEBT.md]
---

# 项目概览

## 项目目标

ADBLab 是面向 Android 设备调试、应用测试和性能诊断的 PySide6 桌面工具。它把 ADB、scrcpy、logcat、dumpsys、Monkey 和移植版 MobilePerf 组织成图形化工作台，主入口为 `main.py::_run_gui()`，当前版本由 `utils/app_metadata.py::APP_VERSION` 定义为 3.2.10。

## 核心用户

- Android 开发、测试和设备实验室人员：连接设备、查看属性、执行应用生命周期操作和收集诊断材料。
- 性能与稳定性测试人员：运行 Monkey、MobilePerf、logcat、bugreport、ANR 和基础性能命令。
- 需要低门槛投屏和远程输入的调试人员：通过 scrcpy 和持久 ADB shell 控制设备。

仓库没有用户研究、权限角色或商业部署资料，因此实际用户规模、组织方式和生产 SLA 均为待确认。

## 主要业务能力

1. 设备发现与连接：轮询 `adb devices`，连接/配对/断开 TCP 设备，读取设备属性并持久化设备列表。
2. 应用管理：安装、卸载、启停、清数据、权限操作、备份/恢复、批量安装（Gate C 批次）、当前前台应用检测和 APK 信息解析。
3. 测试与诊断：Monkey、截图、录屏、logcat、bugreport、ANR、进程/电池/系统信息。
4. 文件操作：浏览设备文件、上传/下载、编辑、复制/移动/删除、权限修改、APK 安装和脚本执行。
5. Remote：启动 scrcpy、查看 FPS、发送按键/滑动/旋转和窗口聚焦。
6. MobilePerf：在隔离子进程中采集 CPU、内存、流量、FPS、FD、线程数和可选 Monkey，输出 CSV/XLSX 与设备信息。
7. 辅助工具：主题/字体/窗口设置（含响应式重排与屏幕适配）、日志面板和结果文件查看。

## 应用类型与边界

- 类型：单进程 Qt 桌面 GUI；MobilePerf、scrcpy、logcat、Monkey 等长任务会派生外部进程或子线程。
- 入站接口：没有 Web 服务器、HTTP 路由、RPC 服务或消息消费者。
- 数据库：没有关系型/文档数据库和 ORM；持久化使用 JSON、YAML 与结果文件。
- 主要外部边界：Android ADB server/device、scrcpy、可选 `aapt`、Java/JAR、Perfetto 网站（浏览器打开）和本地文件系统；主应用没有出站 HTTP 客户端。
- 主要平台：Windows 是主支持目标并内置 adb/scrcpy；仓库没有 Windows 10/11 的版本兼容矩阵。
  CI 还构建 macOS/Linux，但这两类包不包含 scrcpy，完整功能状态待实机确认。

## 技术栈

| 类别 | 技术 | 证据 |
| --- | --- | --- |
| 语言 | Python；少量 YAML/JSON/TOML/PowerShell/Bash | `*.py`、工作流与配置文件 |
| GUI | PySide6 6.8.1.1，Qt Signal/Slot、QThread、QRunnable/QThreadPool；qfluentwidgets（PySide6-Fluent-Widgets 1.11.3）Fluent 风格组件与主题 | `requirements.txt`、`gui/`、`models/adb_model.py` |
| 配置 | JSON、PyYAML | `core/settings_manager.py`、`models/device_store.py` |
| 外部命令 | ADB、scrcpy、aapt、Java | `core/exec.py`、`core/adb_bridge.py`、`services/remote/`、`models/adb_testing.py` |
| 性能采集 | 移植版 MobilePerf、CSV、XLSXWriter | `services/mobileperf_runner.py`、`mobileperf/android/` |
| 测试 | pytest 9.1.1、Ruff 0.16.3 | `requirements-dev.txt`、`ruff.toml`、`tests/` |
| 格式/检查 | Ruff/Black，行宽 100，目标 Python 3.10 语法 | `ruff.toml`（门禁）、`pyproject.toml` |
| 打包/发布 | PyInstaller 6.22.2、GitHub Actions、GitHub Release | `requirements-build.txt`、`ADBLab.spec`、`.github/workflows/Build-exe.yaml` |

## 运行环境

- CI 和 README 的标准解释器为 Python 3.11；仓库内开发环境统一为 `.venv`，完整工具链由
  `requirements-dev.txt` 安装；`pyproject.toml` 的格式/静态检查目标是 Python 3.10 语法兼容。
- Windows 开发运行使用仓库内 `scrcpy-win64/adb.exe` 和 `scrcpy.exe`（scrcpy 4.1、ADB 37.0.0）。
- 用户可写数据根目录由 `utils/user_data.py::user_data_root()` 决定：Windows 默认 `%LOCALAPPDATA%/ADBLab`；非 Windows 使用 XDG 配置目录或 `~/.config/ADBLab`。
- 开发模式直接引用仓库资源；PyInstaller onefile 场景由 `utils/runtime_tools.py::bundled_tool_path()` 把长生命周期工具复制到稳定的用户运行时缓存。

## 当前状态

- 活跃版本：3.2.10；2026-08-27 扫描 `dev` 当前工作树，Git HEAD 锚点为 `adfd254`，
  main 历史基线为 `8b84f8d`。
- 2026-08-18 在 Python 3.11 下实际执行 `py -3.11 -m pytest -q`，930 项全部通过（约 11 分钟）；
  `py -3.11 main.py --self-check packaging` 与 `ruff check .`（0 错误）通过。
- 历史执行记录：2026-08-21 在不含 Pillow、按当时 `requirements-dev.txt` 安装的 Python 3.11.9
  环境中，961 项测试全部通过（350.61 秒），测试收集、Ruff 与 packaging self-check 同步通过；2026-08-23 HEAD `5cee5ca` 下 `--collect-only` 收集到 1062 项；
  该记录不替代后续工作树的重新验证。最新全量执行记录（2026-08-25 离屏 1107 项通过、
  331.12 秒）见 [guides/TESTING_GUIDE.md](../guides/TESTING_GUIDE.md)。
- 打包 CI（`Build-exe.yaml`）不运行 pytest：Windows 安装开发依赖后仅执行 ruff lint 与
  pyright 类型检查；macOS/Linux 构建前执行源码打包自检。三平台均构建，Windows 另对产物
  执行打包后自检。
- README 的性能章节与目录树已于 2026-08-19 修正（移除 `models/performance/`、`gui/performance_web/`、旧性能对话框、`core/mail/`、`batch_tracker.py` 等过时条目，目录树同步 `services/` 与 `adblab/`）。
- Git 快照（2026-08-27，HEAD `adfd254`）：347 个提交、4 个作者标识，最近三个月有
  2 个作者标识活跃；这是动态指标快照，知识集中程度仍待结合模块所有权确认。

## 关键术语

- **CommandRunner**：短生命周期命令的同步执行边界，返回 `CommandResult`。
- **ProcessRunner**：长生命周期外部进程的注册、停止和全局兜底管理器。
- **ADBController**：多个控制器 mixin 组合的 GUI 协调层。
- **async_command**：把 model 方法放入 QThreadPool 的装饰器；`long_running=True` 走每模型长任务池。
- **DeviceStore**：已连接设备元数据的 YAML 存储。
- **Remote**：scrcpy 投屏与 ADB 输入控制功能。
- **MobilePerf**：独立子进程性能采集内核，不等同于 README 中已删除的旧 `models/performance/`。

更多定义见 [glossary.md](glossary.md)。
