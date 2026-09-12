---
status: current
last_verified: 2026-09-12
related: [glossary.md, ARCHITECTURE.md, BUSINESS_FLOW.md, RISKS_AND_DEBT.md]
---

# 项目概览

## 项目目标

ADBLab 是面向 Android 设备调试、应用测试和性能诊断的 PySide6 桌面工具。它把 ADB、scrcpy、
logcat、dumpsys、Monkey 和移植版 MobilePerf 组织成图形化工作台，主入口为
`main.py::_run_gui()`；版本只以 `utils/app_metadata.py::APP_VERSION` 为准。

## 主要业务能力

1. 设备发现与连接：轮询 `adb devices`，连接/断开 TCP 设备，缓存设备属性；仅 IP 连接历史及其元数据
   跨会话保存，范围见 [DATA_FLOW](DATA_FLOW.md#设备发现与元数据流)。全局设备栏管理操作目标，
   固定设备功能使用独立会话。无线配对已有 Controller/model 接口，当前没有可见配对表单。
2. 应用管理：安装、卸载、启停、清数据、权限操作、备份/恢复、批量安装、当前前台应用检测、
   APK 信息解析和设备端原生应用图标。
3. 测试与诊断：Monkey、截图、录屏、logcat、bugreport、ANR、进程/电池/系统信息。
4. 文件操作：浏览设备文件、上传/下载、编辑、复制/移动/删除、权限修改、APK 安装和脚本执行。
5. Remote：启动 scrcpy、查看 FPS、发送按键/滑动/旋转和窗口聚焦。
6. MobilePerf：在隔离子进程中采集 CPU、内存、流量、FPS、FD、线程数和可选 Monkey，输出
   CSV/XLSX 与设备信息，采集结束后展示静态结果图表。
7. 界面与环境设置：主题、云母效果、字体、显示缩放、窗口适配与多语言，支持查看 ADB 自动适配状态、固定本地 ADB 客户端，
   并选择本次运行的执行模式（自动/手动快速/手动原生）；具体生效时机见 [BUILD_AND_RUN](../guides/BUILD_AND_RUN.md#启动)
   与 [ADB_FAST](../guides/ADB_FAST.md)。
8. 结果管理：任务中心保留本次操作的逐台结果、正文与附件；Monkey/性能测试另有跨重启归档和命名
   参数方案，支持回填参数而不自动开始测试。应用诊断可在设置页导出。

当前主界面是 qfluentwidgets `FluentWindow` 工作台；长期功能内嵌，纯消息在窗口内提示，
输入与系统文件选择保留瞬态交互。完整页面路由与设备选择规则见
[BUSINESS_FLOW](BUSINESS_FLOW.md#workspace-路由目录)，组件与会话边界见 [ARCHITECTURE](ARCHITECTURE.md)。

## 应用类型与边界

- 类型：Qt 桌面应用；MobilePerf、scrcpy、logcat、Monkey 等长任务会派生受控外部进程或线程。
- 入站接口：没有 Web 服务器、HTTP 路由、RPC 服务或消息消费者。
- 数据库：没有关系型/文档数据库和 ORM；持久化使用 JSON、YAML 与结果文件。
- 主要外部边界：Android ADB server/device、scrcpy、可选 `aapt`、Java/JAR、Perfetto 网站（浏览器打开）、本地文件系统，以及应用更新检查对 GitHub 公共 Releases API 的匿名 HTTPS 只读请求。除该更新检查外，主应用没有其他出站 HTTP 客户端。
- 主要平台：Windows 是主支持目标并内置 adb/scrcpy；仓库没有 Windows 10/11 的版本兼容矩阵。
  CI 还构建 macOS/Linux，但这两类包不包含 scrcpy，完整功能状态待实机确认。

## 技术栈

| 类别 | 技术 | 证据 |
| --- | --- | --- |
| 语言 | Python；少量 YAML/JSON/TOML/PowerShell/Bash | `*.py`、工作流与配置文件 |
| GUI | PySide6 提供 Qt 组件与线程模型；通用控件、导航和主题使用 PySide6-Fluent-Widgets | `requirements.txt`、`gui/`、`models/adb_model.py` |
| 配置 | JSON、PyYAML | `core/settings_manager.py`、`models/device_store.py` |
| 外部命令 | ADB、scrcpy、aapt、Java | `core/exec.py`、`core/adb_bridge.py`、`services/remote/`、`models/adb_testing.py` |
| 性能采集 | 移植版 MobilePerf、CSV、XLSXWriter | `services/mobileperf_runner.py`、`mobileperf/android/` |
| 测试与静态检查 | pytest、Ruff、Pyright | `requirements-dev.txt`、`ruff.toml`、`pyproject.toml`、`tests/` |
| 打包/发布 | PyInstaller、GitHub Actions、GitHub Release | `requirements-build.txt`、`ADBLab.spec`、`.github/workflows/Build-exe.yaml` |

## 运行环境入口

Python 与平台支持、环境安装和打包方法见 [BUILD_AND_RUN](../guides/BUILD_AND_RUN.md)。
配置与结果进入平台用户目录；资源定位和 onefile 工具缓存见 [DATA_FLOW](DATA_FLOW.md#文件型存储)。

当前页面和设备选择规则见 [BUSINESS_FLOW](BUSINESS_FLOW.md)，未闭环事项见
[RISKS_AND_DEBT](RISKS_AND_DEBT.md)。
