# 测试指南

## 基础约定

- 使用 pytest；`pyproject.toml` 把项目根加入 `pythonpath`。
- `tests/conftest.py` 保持 session 级 QApplication，并在每个用例后恢复主题、字体和顶层窗口状态。
- 测试主要使用 monkeypatch、临时目录和轻量 fake/stub，不默认连接真实 Android 设备。
- `ui` 与 `integration` marker 由 `tests/conftest.py` 集中附加；新增 Qt 测试文件时同步登记。
  `unit` marker 已注册但尚未系统分配，不能把 `not ui` 等同为显式 unit 集。

## 测试域

| 测试域 | 代表性入口 | 主要覆盖 |
| --- | --- | --- |
| 执行、配置与存储 | `test_model_*.py`、`test_settings_persistence.py`、`test_device_store_concurrency.py` | CommandRunner/ProcessRunner、ADB model、设置迁移、原子写与故障恢复 |
| Operation 与 Controller | `test_phase1_operations.py`、`test_device_batch_use_case.py`、`test_phase2_install_batch_*.py` | operation 身份、批次状态、取消、晚到结果与路由 |
| Workspace 与任务中心 | `test_workspace_feature_host.py`、`test_task_center.py`、`test_task_history.py` | 深层路由、稳定会话、异步释放、活动任务和进程内历史 |
| UI、主题与响应式 | `test_main_window_layout.py`、`test_responsive_*.py`、`test_*typography.py` | 导航、主题、字体、DPI、断点重排、无障碍与瞬态交互 |
| App、文件与媒体 | `test_app_manager_selection.py`、`test_file_explorer_service.py`、`test_screenshot_page.py` | 应用管理、路径/传输、截图批次和页面交互 |
| Remote 与 MobilePerf | `test_remote_services.py`、`test_model_mobileperf.py`、`test_mobileperf_runner_concurrency.py` | scrcpy/输入、隔离子进程、报告与并发排空 |
| 生命周期与探针 | `test_model_shutdown_admission.py`、`test_window_lifecycle.py`、`live_logcat_close_probe.py` | 关闭准入、QObject 晚到回调、线程/进程释放 |
| 静态与构建契约 | `test_ci_contracts.py`、`test_comment_language.py`、`test_runtime_tools.py` | workflow 权限、注释规则、资源和打包路径 |

## 执行命令

### 增量验证策略

本地修复和日常开发必须优先选择“最小但充分”的测试集，不把全量测试作为每次代码修改后的
默认动作：

1. 先运行直接覆盖修改行为的测试节点或测试文件。
2. 根据入口、调用链、共享数据结构、线程/进程生命周期和失败路径，补充受影响模块测试。
3. 只有关联测试无法界定影响范围时才扩大测试集；不得仅因“可能有用”而运行无关模块。
4. 代码、测试或方案仍可能继续变化时不得启动全量测试。确需全量时，在代码冻结后集中执行。
5. 全量测试只由以下条件触发：用户明确要求；发布验收；改动横跨多个共享核心边界且无法可靠
   界定影响范围；专门测试工作流的固定门禁。dev 推送 main 本身不触发本地全量测试；当前 Build
   工作流不执行 pytest。若缺少合并前测试门禁，只报告 main 可能先进入失败提交的风险，不以此
   为由擅自运行本地全量。
6. 全量测试后若又发生局部修改，先重跑该修改的直接与关联测试；仅当发布/合并仍要求完整快照时
   才重新执行全量测试。
7. 纯文档修改不运行 pytest；只执行 `scripts/check_doc_links.py`、适用的文档规范检查和
   `git diff --check`。

例如，只修改 LiveLogcat 包过滤时，优先执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_phase2_live_logcat_gate.py `
  tests/test_model_meta.py `
  tests/test_model_apps.py
```

最终报告必须列出实际运行的关联测试及结果，并明确说明是否执行全量测试；未满足全量触发条件而
未运行全量测试，不应标记为验证缺失。

### 完整门禁命令

完整门禁只在增量策略列出的触发条件成立时执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py --self-check packaging
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pyright
git diff --check
```

`pytest --collect-only` 只用于发现和选择测试，不属于完整门禁：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

测试数量、耗时和通过结果只属于执行当时的工作树，写入任务/发布记录，不作为长期指南内容。
`not ui` 会选择 integration 和其他未标为 UI 的项目，不能把它等同为显式 unit 集：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not ui"
```

新增 UI 类测试文件时同步登记 conftest 映射。Build 工作流不执行 pytest；开发和发布验收仅在
全量触发条件成立时执行完整命令。

## 隔离与替身

- pytest `monkeypatch` 替换 subprocess、路径解析、设置和 platform/frozen 状态。
- fake process 实现 `poll/terminate/kill/wait/stdout` 等协议，验证 ProcessRunner 和 MobilePerfRunner。
- `tmp_path` 隔离 JSON/YAML/截图/报告/临时配置。
- Qt 测试直接验证可观察行为，并替换外部 service；不依赖无业务意义的私有字段不存在断言。
- 测试工作流 YAML 的关键文本/结构，防止打包模式和发布资产回归。

## 当前覆盖缺口

活动测试缺口统一维护在 [RISKS_AND_DEBT](../project-knowledge/RISKS_AND_DEBT.md)，本指南不重复
风险清单。新增缺口在风险账本登记后，再在本页补充对应测试域、选择方式或门禁命令。

## 注释与文档风格

### 目标

生产代码中的注释和文档字符串统一使用规范中文，重点记录业务原因、边界条件、失败语义、线程或
进程归属以及资源生命周期。ADB、Qt、API、类名、字段名、命令和协议名称保留原文，不做生硬翻译。

### 编写规则

1. 每个生产模块应提供简短的中文模块文档字符串，说明职责和关键边界。
2. 公共类、公共接口以及涉及线程、进程、取消、超时、危险 ADB 操作、持久化和清理的函数，
   应使用中文文档字符串说明契约。
3. 注释解释"为什么"和"必须满足什么约束"，不复述赋值、分支或界面布局等显然代码。
4. 不保留注释掉的历史代码、无上下文的阶段编号或已经失效的实现说明。
5. 修改注释时必须人工核对相邻实现；禁止脱离调用链批量机械翻译。
6. 用户界面文案、异常消息、协议字段和外部命令输出不属于注释语言治理范围。

以下内容允许保持英文或机器格式：

- shebang、源文件编码声明；
- `noqa`、`type: ignore`、`pylint`、`ruff`、`fmt` 等工具指令；
- URL、许可证和版权声明；
- 可直接执行的 `py`、`python`、`pytest`、`ruff`、`git`、`adb` 等命令；
- 单独出现的技术标识，例如 `OperationState.SUCCEEDED`。

### 渐进门禁

检查器位于 `scripts/check_comment_language.py`，使用 `tokenize` 识别真实注释，使用 AST 识别模块、
类和函数的文档字符串，避免把普通字符串误判为注释。检查器还会独立识别 Unicode 替换符和 `锛`、
`銆`、`鈥` 等常见误解码片段，含乱码的中文不会被当作合规内容。

当前受控范围：`adblab/`、`controllers/`、`core/`、`gui/`、`models/`、`utils/`、`main.py`、
`mobileperf/common/`、`mobileperf/android/`（包括其中一方 Python 适配代码）。以上一方源码已经
完成人工治理并进入默认门禁。第三方、生成文件、缓存、资源、二进制工具、`mobileperf/extlib/` 和
平台二进制工具始终排除；新增一方源码必须同步纳入受控目录，不得通过扩大排除表规避检查。

运行默认门禁：

```powershell
.\.venv\Scripts\python.exe scripts/check_comment_language.py
```

评审待治理目录时可以显式传入路径；该方式用于生成债务清单，不代表该目录已经进入默认门禁：

```powershell
.\.venv\Scripts\python.exe scripts/check_comment_language.py controllers gui
```

门禁只解决可自动判断的语言一致性问题。注释是否准确、是否提供必要的生命周期和失败语义，仍需
代码评审结合入口、调用链、失败路径和清理路径确认。

## 提交与发布门禁

版本与发布规则只在 [BUILD_AND_RUN](BUILD_AND_RUN.md) 维护。

普通本地修改的最低门禁是关联测试、修改文件的 Ruff/适用静态检查以及 `git diff --check`。
纯文档修改按增量策略只运行文档检查。发布验收、用户明确要求或无法可靠界定影响范围的共享
核心改动按 [完整门禁命令](#完整门禁命令) 执行；Build 工作流不执行 pytest，dev 推送 main 本身
不触发本地全量测试。

若修改 PyInstaller/资源/入口，再执行 spec 构建和打包后 self-check。若修改 ADB 命令、Remote 或 MobilePerf，除单测外应在授权测试设备上执行最小实机验证，并确保日志不含真实敏感值。

## 质量工具链

除 pytest/ruff 外，`requirements-dev.txt` 提供以下工具（配置随仓库）：

- **pyright**（类型检查）：范围和排除项见 `pyrightconfig.json`；运行
  `.\.venv\Scripts\python.exe -m pyright`。
- **pytest-cov**（覆盖率）：`.\.venv\Scripts\python.exe -m pytest -q -m "not ui" --cov=adblab --cov=services --cov-report=term-missing`。
- **pytest-xdist**（并行）：`.\.venv\Scripts\python.exe -m pytest -q -n auto`。注意：含子进程探针的
  `test_phase2_live_logcat_gate.py` 在并行 worker 下不稳定，并行运行请限定纯逻辑子集
  （如 `-n 4 -m "not ui" --ignore=tests/test_phase2_live_logcat_gate.py`）；人工全量验证仍建议串行执行。
- **pre-commit**（本地钩子）：`.pre-commit-config.yaml` 已配置 ruff、中文注释门禁与
  文档链接校验三个本地钩子；首次使用执行
  `.\.venv\Scripts\python.exe -m pre_commit install`。
