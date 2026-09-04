# ADBLab

ADBLab 是一款基于 Python 3.11、PySide6 和 PySide6-Fluent-Widgets 的 Android
设备管理、自动化测试与性能诊断桌面应用，主要面向 Windows。项目将 ADB、scrcpy、
logcat、dumpsys、Monkey、文件管理和性能采集能力整合到统一界面，并对长任务、外部进程、
配置写入和窗口关闭进行集中管理。

应用版本以 [`utils/app_metadata.py`](utils/app_metadata.py) 为唯一来源。

## 界面与功能

主窗口使用左侧分组导航，不再为主要工具创建独立顶层窗口：

- **设备与控制**：设备连接与选择、文件管理、屏幕镜像、按键与手势控制。
- **应用与自动化**：日常应用操作、应用包管理、Monkey 测试、诊断工具和截图结果。
- **系统与诊断**：系统命令、连接与服务、设备设置、实时 Logcat 和性能采集。
- **任务中心 / 操作日志**：查看运行中及最近完成的任务和诊断记录。
- **设置**：主题、字体、窗口、路径、日志及设备扫描配置；About 信息也位于设置页。

文件管理、应用管理、实时 Logcat 和性能采集按单设备上下文在工作区内创建、复用和关闭；
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

- Qt 控件只在 GUI 主线程操作；耗时 ADB、I/O 和进程等待通过现有 worker 或任务设施执行。
- 短命令使用 `core.exec.CommandRunner`；受控长进程使用 `ProcessRunner`。
- 动态设备值必须经过现有校验和 quoting 边界，不在 UI 中拼接复杂 shell 命令。
- 配置和设备元数据写入 `utils/user_data.py` 提供的用户目录；日志主要保存在内存，截图、报告等
  结果写入用户选择的目录。
- 资源通过项目资源解析接口访问，同时兼容源码和 PyInstaller 环境。
- 外部 ZIP 使用 `utils.archive.safe_extract_zip()` 解压。
- 当前 UI 栈是 PySide6；查询 qfluentwidgets 行为时以活动环境中的 PySide6 包为准。

更完整的实现契约见
[`ARCHITECTURE.md`](docs/project-knowledge/ARCHITECTURE.md) 和
[`DEPENDENCY_MAP.md`](docs/project-knowledge/DEPENDENCY_MAP.md)。

## 测试与打包

先运行直接相关测试，再按调用链扩大范围。测试分层、完整门禁和 Qt 平台设置统一维护在
[`TESTING_GUIDE.md`](docs/guides/TESTING_GUIDE.md)。构建和 PyInstaller 流程见
[`BUILD_AND_RUN.md`](docs/guides/BUILD_AND_RUN.md)。

常用检查示例：

```powershell
.\.venv\Scripts\python.exe -m pytest -q <test-file-or-node>
.\.venv\Scripts\python.exe -m ruff check <changed-python-files>
.\.venv\Scripts\python.exe -m pyright <affected-production-paths>
.\.venv\Scripts\python.exe scripts/check_doc_links.py
.\.venv\Scripts\python.exe main.py --self-check packaging
git diff --check
```

## 第三方代码与许可

项目运行时依赖 PySide6-Fluent-Widgets，并包含经适配的 MobilePerf、XlsxWriter 及平台工具。
来源、修改边界和许可要求见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 及各组件随附的
许可文件。对外分发前必须完成相应许可核验。

Copyright (c) 2026 Frankie Hu
