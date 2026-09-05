# ADBLab

ADBLab 是一款基于 Python 3.11、PySide6 和 PySide6-Fluent-Widgets 的 Android
设备管理、自动化测试与性能诊断桌面应用，主要面向 Windows。项目将 ADB、scrcpy、
logcat、dumpsys、Monkey、文件管理和性能采集能力整合到统一界面，并对长任务、外部进程、
配置写入和窗口关闭进行集中管理。

应用版本以 [`utils/app_metadata.py`](utils/app_metadata.py) 为唯一来源。

## 界面与功能

主窗口左侧直接选择具体功能，页面内不再重复展示功能页签，主要工具在窗口内运行：

- **设备概览 / 文件管理 / 远程控制**：设备卡支持多选和直接打开该设备的工具；屏幕镜像与按键手势合并。
- **应用管理 / 截图与诊断 / 截图结果**：应用管理显示单设备应用列表；应用包管理和 APK 工具在截图与诊断页顶部常显，与 Monkey 共用包名输入。
- **系统工具 / 实时 Logcat / 性能采集**：系统命令与设备配置在同一页面，其余工具独立直达。
- **任务中心**：查看运行中及最近完成的任务；展开“运行记录”筛选应用操作结果与异常。
- **设置**：主题、字体、显示缩放、窗口、路径、日志、设备扫描配置及 ADB 维护；About 信息也位于设置页。

除首页外，各页面顶部常驻设备栏，支持多选、连接和刷新；固定设备功能在同一区域选择“当前查看”的设备。
信息和断开操作位于设备栏的“更多”菜单。Monkey 与截图录屏、应用诊断位于同一页，开始前先获取所有目标设备的测试包信息。设置中的显示缩放支持跟随系统及 100%～200%，重启后生效；
字号使用 pt，既有字号保持不变，可选择 11 pt 获得更紧凑的界面。
文件管理、已安装应用列表、实时 Logcat 和性能采集按单设备上下文在窗口内创建、复用和关闭；
截图结果使用独立的无设备会话。需要确认、短文本输入或系统文件选择时才使用临时窗口。

主要能力包括：

- USB/IP 设备发现、连接、断开、重启和设备信息读取。
- 应用安装、卸载、启停、清理、备份恢复、权限与包信息管理。
- Monkey、Bugreport、ANR、meminfo、gfxinfo、wakelock、netstats 等测试与诊断。
- 设备文件浏览、搜索、推送、拉取、重命名、删除、预览和脚本执行。
- 基于 scrcpy 的投屏、录制、编码参数和 ADB 按键/手势控制。
- 隔离子进程运行的 MobilePerf 采集与报告生成。

## 快速启动

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
```

依赖按用途分层：

- `requirements.txt`：运行依赖。
- `requirements-build.txt`：运行依赖和 PyInstaller。
- `requirements-dev.txt`：构建、测试、Lint、类型检查和 pre-commit 工具。

开发时直接调用 `.venv\Scripts\python.exe`，避免把依赖安装到系统 Python。

## 项目结构

| 路径 | 职责 |
| --- | --- |
| `main.py` | GUI、打包自检和 MobilePerf worker 入口 |
| `gui/` | 页面、工作区宿主、主题和 Qt 控件 |
| `controllers/` | 信号路由与用例协调 |
| `models/` | ADB 模型、设备存储及专用 worker |
| `services/` | 文件、Remote、MobilePerf 等服务边界 |
| `core/` | 命令、进程、设置和日志基础设施 |
| `adblab/` | 应用用例、任务状态及 Qt 适配 |
| `mobileperf/` | 随项目移植的 MobilePerf 内核 |
| `resources/` | 运行所需配置、图标及辅助工具 |
| `tests/` | 单元、UI、集成及生命周期回归测试 |
| `docs/` | 当前知识、架构决策、指南与历史归档 |

模块职责、完整业务路由和依赖方向不在本页重复维护，请从
[`docs/README.md`](docs/README.md) 进入项目知识库。

## 开发约束

协作、修改、清理和授权边界统一维护在 [`AGENTS.md`](AGENTS.md)，
各类约束的索引见 [`docs/README.md`](docs/README.md#当前约束入口)。实现契约见
[`ARCHITECTURE.md`](docs/project-knowledge/ARCHITECTURE.md) 和
[`DEPENDENCY_MAP.md`](docs/project-knowledge/DEPENDENCY_MAP.md)。

## 测试与打包

先运行直接相关测试，再按调用链扩大范围。测试分层、完整门禁和 Qt 平台设置统一维护在
[`TESTING_GUIDE.md`](docs/guides/TESTING_GUIDE.md)。构建和 PyInstaller 流程见
[`BUILD_AND_RUN.md`](docs/guides/BUILD_AND_RUN.md)。

## 第三方代码与许可

项目运行时依赖 PySide6-Fluent-Widgets，并包含经适配的 MobilePerf、XlsxWriter 及平台工具。
来源、修改边界和许可要求见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 及各组件随附的
许可文件。对外分发前必须完成相应许可核验。

Copyright (c) 2026 Frankie Hu
