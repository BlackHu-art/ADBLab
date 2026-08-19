# ADBLab 项目知识库

本知识库是 ADBLab 当前实现的长期维护入口。结论以仓库代码、配置、测试和构建脚本为依据；不能由仓库确认的内容统一标记为“待确认”。修改代码时，先从本页定位必读文档，再追踪入口、调用链、失败路径、线程/进程清理和现有测试。

## 基线与状态

| 项目 | 当前记录 |
| --- | --- |
| 事实基线 | `dev` 分支 HEAD，扫描日期 2026-08-19 |
| 本次整理 | 2026-08-19，当前仓库 `dev`，版本 3.1.69 |
| 基线以来变更 | `dev` 自 main 基线 `8b84f8d`（3.1.14）重做：7 个实现提交（`70be33e` 卫生、`481175d` 安装批次 Gate C、`e36e3e6` Remote/MobilePerf 修复、`6ae6fea` 响应式框架控件、`3492159` 响应式面板/对话框/主窗口、`2f999eb` screen adapter 抽取与几何扫描提速、`d099b39` 知识库校准），以及随后的文档锚点同步提交 |
| 文档范围 | 根入口、`controllers/`、`core/`、`gui/`、`models/`、`utils/`、`adblab/`、`tests/`、`.github/workflows/`、`mobileperf/` 核心代码，以及资源和内置工具用途 |
| 文档 owner | 待确认；未指定具名维护人前，不把这些文档视为正式受控 SOP |
| 敏感信息规则 | 不记录密钥、Token、密码、私有证书、真实设备唯一标识、邮件正文或验证码 |

## 快速阅读路径

| 场景 | 先读 | 再读 |
| --- | --- | --- |
| 快速理解项目 | [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)、[glossary.md](glossary.md) | [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md) |
| 修改启动、分层、线程或关闭逻辑 | [ARCHITECTURE.md](ARCHITECTURE.md)、[MODULE_MAP.md](MODULE_MAP.md) | [BUSINESS_FLOW.md](BUSINESS_FLOW.md)、[TESTING_GUIDE.md](TESTING_GUIDE.md) |
| 修改具体功能模块 | [MODULE_MAP.md](MODULE_MAP.md) | 对应 [BUSINESS_FLOW.md](BUSINESS_FLOW.md) 章节、[TESTING_GUIDE.md](TESTING_GUIDE.md) |
| 修改 ADB/HTTP/外部命令边界 | [API_MAP.md](API_MAP.md)、[DEPENDENCY_MAP.md](DEPENDENCY_MAP.md) | [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md) |
| 修改配置、持久化或用户数据 | [DATABASE_MAP.md](DATABASE_MAP.md)、[DATA_FLOW.md](DATA_FLOW.md) | [BUILD_AND_RUN.md](BUILD_AND_RUN.md) |
| 修改 Remote 或 MobilePerf | [BUSINESS_FLOW.md](BUSINESS_FLOW.md)、[MODULE_MAP.md](MODULE_MAP.md) | [DEPENDENCY_MAP.md](DEPENDENCY_MAP.md)、[TESTING_GUIDE.md](TESTING_GUIDE.md) |
| 修改日志、注释或文档字符串 | [ARCHITECTURE.md](ARCHITECTURE.md)、[COMMENT_STYLE.md](COMMENT_STYLE.md) | [TESTING_GUIDE.md](TESTING_GUIDE.md) |
| 构建、打包、发布或 CI | [BUILD_AND_RUN.md](BUILD_AND_RUN.md)、[TESTING_GUIDE.md](TESTING_GUIDE.md) | [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md) |

## 文档地图

### 产品与术语

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)：项目目标、用户、能力、技术栈、运行环境、当前状态与关键术语入口。
- [glossary.md](glossary.md)：项目专有名词、通用缩写和对应代码概念。

### 架构与模块

- [ARCHITECTURE.md](ARCHITECTURE.md)：总体分层、运行时组件、初始化/关闭、线程/进程模型和架构限制。
- [MODULE_MAP.md](MODULE_MAP.md)：模块职责、接口、上下游、配置、数据、测试与风险。
- [DEPENDENCY_MAP.md](DEPENDENCY_MAP.md)：内部依赖方向、第三方依赖、外部系统和依赖治理建议。

### 流程与数据

- [BUSINESS_FLOW.md](BUSINESS_FLOW.md)：启动、设备、应用、安装批次、Monkey、诊断、文件、Remote、MobilePerf 和关闭链路。
- [DATA_FLOW.md](DATA_FLOW.md)：核心数据对象、来源、转换、存储、生命周期和状态变化。
- [DATABASE_MAP.md](DATABASE_MAP.md)：无数据库结论，以及 JSON/YAML/普通文件型持久化映射。

### 边界、交付与质量

- [API_MAP.md](API_MAP.md)：入站 API 结论、ADB 命令接口和文件/进程安全约定。
- [BUILD_AND_RUN.md](BUILD_AND_RUN.md)：经仓库或实际执行验证的安装、启动、测试、PyInstaller 和 CI/CD 方法。
- [TESTING_GUIDE.md](TESTING_GUIDE.md)：测试分层、目录、Mock 方式、已验证命令、覆盖缺口和提交前门禁。
- [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md)：按严重程度排序的缺陷、安全风险、技术债、历史热点和修复优先级。
- [COMMENT_STYLE.md](COMMENT_STYLE.md)：中文注释和文档字符串规范、受控范围及静态检查方法。

## 维护热点

修改以下区域前，优先按“入口 → 调用链 → 失败路径 → 清理路径 → 测试”的顺序追踪：

- `gui/main_frame.py`：主窗口（约 2,500 行）、设备扫描、工具栏溢出、面板懒加载、信号接线和关闭清理。
- `adblab/application/`：`operations.py`（OperationManager 单元接口）与 `install_batch.py`（安装批次 Gate C 用例）。
- `controllers/`：批次状态与所有权/generation 边界、异步结果分派、截图/录屏共享状态和危险操作入口。
- `models/base/`、`core/adb_bridge.py`：短命令、长进程和持久 shell 边界。
- `gui/widgets/responsive_controller.py`、`gui/widgets/responsive_layout.py`、`gui/screen_adapter.py`：响应式重排协调器、语义布局和屏幕适配协议。
- `gui/dialogs/app_manager.py`、`models/app_manager_worker.py`：批量应用操作、备份恢复和失败传播。
- `gui/panels/remote_panel.py`、`models/remote/`：scrcpy 预检、输入映射、会话所有权/watchdog 和关闭清理。
- `models/mobileperf/`、`mobileperf/android/`：隔离子进程、采样线程、报告落盘和遗留 ADB 实现（`shell=True` 未重写）。

## 知识库维护规则

1. 修改架构、对外接口、配置键、数据结构、主要业务链路、构建或测试命令后，同步更新对应主题文档和本页导航。
2. 代码与文档冲突时，以当前可执行代码和测试为准；修正文档，不把推测写成事实。
3. 新增功能时至少更新 [MODULE_MAP.md](MODULE_MAP.md) 和相关业务/数据/边界文档；新增风险时同步 [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md)。
4. 新增术语或缩写时同步 [glossary.md](glossary.md)，避免同一词在不同文档中漂移。
5. 每个 Git 提交必须在 `utils/app_metadata.py` 中递增一次 `APP_VERSION`，默认递增补丁版本且不得复用历史版本。
6. 提交前至少运行 `py -3.11 -m pytest -q`（全量约 930 项、约 11 分钟）、`py -3.11 main.py --self-check packaging`、`ruff check .`、`git diff --check`；修改打包/资源/ADB/Remote/MobilePerf 时按 [TESTING_GUIDE.md](TESTING_GUIDE.md) 扩展验证。

## 2026-08-18 知识库卫生检查

- 已扫描 14 个 Markdown 文档；当前没有超过 365 天的陈旧页。
- 未发现同一缩写的明显定义漂移；高频缩写已集中补充到 [glossary.md](glossary.md)。
- 邮件服务（`core/mail/`、邮件获取入口、邮件/验证码信号、requests/ruamel 依赖）已全部移除，知识库同步清除相关描述，仅保留历史跟踪配置的所有者轮换提醒。
- `INDEX.md` 作为入口页没有入站链接属于正常现象；不要按孤立页归档。
- 所有文档仍缺具名 owner；需要由项目维护者确认文档负责人和复审周期。

## 明确排除

- `.git/`：版本数据库，不属于运行时代码。
- `.idea/`、`.pytest_cache/`、`__pycache__/`、`logs/`：IDE、缓存或运行产物。
- `resources/icons/`：大量图标资源，只验证加载机制与打包关系。
- `scrcpy-win64-v3.3.1/`：第三方可执行文件、DLL 和脚本，只验证调用与打包关系。
- `mobileperf/extlib/xlsxwriter/`：随项目携带的第三方实现，只验证报告模块对它的依赖。
- `mobileperf/android/tools/` 内各平台 ADB 二进制，以及仓库中的 JAR、图片、GIF、日志和其他媒体/生成文件：只验证调用位置与用途，不作为核心源码分析对象。
- `pyright_output.json`：静态分析输出产物，不作为实现事实来源。
