# ADBLab 项目知识库

本知识库是 ADBLab 当前实现的长期维护入口。内容基于 `dev` 分支提交 `1f86f3f9378c`，扫描日期为 2026-07-23。结论以代码、配置、测试和构建脚本为依据；不能由仓库确认的内容统一标记为“待确认”。

## 使用方式

开始开发任务前先阅读本页，再按任务类型选择对应文档：

| 任务类型 | 必读文档 |
| --- | --- |
| 理解产品与边界 | [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)、[glossary.md](glossary.md) |
| 修改启动、分层或线程模型 | [ARCHITECTURE.md](ARCHITECTURE.md)、[DEPENDENCY_MAP.md](DEPENDENCY_MAP.md) |
| 修改具体模块 | [MODULE_MAP.md](MODULE_MAP.md)、[TESTING_GUIDE.md](TESTING_GUIDE.md) |
| 修改设备操作或业务流程 | [BUSINESS_FLOW.md](BUSINESS_FLOW.md)、[DATA_FLOW.md](DATA_FLOW.md) |
| 修改 HTTP/ADB 边界 | [API_MAP.md](API_MAP.md)、[RISKS_AND_DEBT.md](RISKS_AND_DEBT.md) |
| 修改配置或持久化 | [DATABASE_MAP.md](DATABASE_MAP.md)、[BUILD_AND_RUN.md](BUILD_AND_RUN.md) |
| 构建、测试、发布 | [BUILD_AND_RUN.md](BUILD_AND_RUN.md)、[TESTING_GUIDE.md](TESTING_GUIDE.md) |

## 文档导航

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)：项目目标、用户、能力、技术栈、状态与术语入口。
- [ARCHITECTURE.md](ARCHITECTURE.md)：总体分层、运行时组件、线程/进程模型和架构限制。
- [MODULE_MAP.md](MODULE_MAP.md)：模块职责、接口、上下游、配置、数据、测试与风险。
- [DEPENDENCY_MAP.md](DEPENDENCY_MAP.md)：内部、第三方和外部系统依赖及依赖方向。
- [DATA_FLOW.md](DATA_FLOW.md)：核心数据对象、来源、转换、存储、生命周期和状态变化。
- [BUSINESS_FLOW.md](BUSINESS_FLOW.md)：启动、设备、应用、文件、Remote、MobilePerf、邮件等链路。
- [API_MAP.md](API_MAP.md)：入站 API 结论、外部临时邮箱 HTTP API 与主要命令边界。
- [DATABASE_MAP.md](DATABASE_MAP.md)：无数据库结论以及 JSON/YAML/文件型持久化映射。
- [BUILD_AND_RUN.md](BUILD_AND_RUN.md)：经过仓库或实际执行验证的安装、启动、测试和打包方法。
- [TESTING_GUIDE.md](TESTING_GUIDE.md)：测试分层、目录、Mock 方式、已验证命令与覆盖缺口。
- [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md)：按严重程度排列的缺陷、安全风险与技术债。
- [glossary.md](glossary.md)：项目专有名词、缩写和对应代码概念。

## 扫描范围与方法

- 已分析：根入口和配置、`controllers/`、`core/`、`gui/`、`models/`、`utils/`、`tests/`、`.github/workflows/`、`mobileperf/` 的核心采集代码，以及资源和内置工具的用途。
- 当前仓库有 1,726 个 Git 跟踪文件，其中 1,512 个为 SVG 图标；排除 `mobileperf/extlib/` 后，纳入源代码结构分析的 Python 文件为 108 个，约 26,786 行。
- 深读原则：定位入口、核心类、调用者、命令边界、状态存储和关闭清理；对图标、二进制和第三方实现只确认用途，不逐字分析。
- 历史辅助：检查全部 244 个提交，以变更频率和修复频率识别维护热点；历史热点包括 `gui/main_frame.py`、`models/adb_model.py`、`gui/dialogs/app_manager.py`、`gui/dialogs/screenshot_viewer.py` 和已删除的旧控制器文件。

## 明确排除

- `.git/`：版本数据库，不属于运行时代码。
- `.idea/`、`.pytest_cache/`、`__pycache__/`、`logs/`：IDE、缓存或运行产物。
- `resources/icons/`：1,512 个图标资源，仅验证加载机制与打包关系。
- `scrcpy-win64-v3.3.1/`：第三方可执行文件、DLL 和脚本，仅验证调用与打包关系。
- `mobileperf/extlib/xlsxwriter/`：随项目携带的第三方实现，仅验证报告模块对它的依赖。
- `mobileperf/android/tools/` 内的各平台 ADB 二进制，以及仓库中的 JAR、图片、GIF、日志和其他媒体/生成文件：只验证调用位置与用途，不作为核心源码分析。
- `pyright_output.json`：静态分析输出产物，不作为实现事实来源。

## 维护规则

修改架构、对外接口、配置键、数据结构、主要业务链路、构建/测试命令后，必须同步更新对应文档和本页导航。代码与文档冲突时，以当前可执行代码和测试为准，并修正文档；不得把推测写成事实，不得在知识库中记录密钥、Token、密码、私钥、设备唯一标识或邮件正文。
