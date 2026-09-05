# 测试指南

## 基础约定

- 使用 pytest；`pyproject.toml` 把项目根加入 `pythonpath`。
- 使用仓库 `.venv`，诊断导入问题时核实 `sys.executable`、PySide6 和 pytest 的实际来源。
- `tests/conftest.py` 保持 session 级 QApplication，并在每个用例后恢复主题、字体和顶层窗口状态。
- Windows 离屏平台若未提供系统字体库，测试夹具只读注册现有 Windows 字体，确保中文字形和
  实际字体尺寸参与布局验证；生产应用仍使用正常的 Qt 字体发现机制。
- 测试主要使用 monkeypatch、临时目录和轻量 fake/stub，不默认连接真实 Android 设备。
- `ui` 与 `integration` marker 由 `tests/conftest.py` 集中附加；新增 Qt 测试文件时同步登记，
  混合文件按节点标记 Qt 用例，不能因为文件名像纯逻辑就漏标。
  `unit` marker 已注册但尚未系统分配，不能把 `not ui` 等同为显式 unit 集。
- 当前全局 autouse 夹具仍初始化 QApplication，`not ui` 只改变测试选择，不承诺完全不导入 Qt。

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

先按本轮变更建立“行为或边界 → 直接测试 → 关联消费者”映射。已有脏工作树中此前验收的文件
不是本轮新增范围；检查知识库、代码规范或测试规范也不自动等于要求执行所有测试。

| 本轮修改 | 首先执行 | 何时扩大 |
| --- | --- | --- |
| 纯文档、规则文字或普通注释 | 文档检查、注释检查、`git diff --check` | 注释为 doctest/工具指令，或改了检查器时运行其直接测试 |
| 单函数、单页面或明确缺陷 | 覆盖当前入口与失败行为的节点/文件 | 受影响调用方、同页状态或共享控件的关联测试 |
| 测试替身、断言或收集 marker | 修改文件的直接测试；marker 用 collect-only 核对选择 | 混合文件的 UI/非 UI 边界或相邻契约 |
| Qt 夹具、主题、布局或生命周期 | 直接回归及共享该状态的代表性组合 | 有顺序污染证据时重现原始组合与销毁/晚到回调 |
| 命令、设置、并发或进程边界 | 成功、失败、取消、重复启动、关闭的直接测试 | 实际消费者和调用链，无法界定时才评估全量 |
| 入口、资源、运行时路径或打包 | 对应测试与源码 packaging self-check | 构建和实际产物自检按构建指南及授权范围执行 |

全量 pytest 只由以下任一条件触发，并须等相关生产代码、测试和方案稳定后集中执行：

1. 用户明确要求“全量测试/完整测试套件”；“检查并验证”“完成长任务”不等同于该要求。
2. 当前任务是正式发布验收，或已有明确的合并验收要求指定完整快照。
3. 已沿调用链分析，但共享核心改动的影响范围仍无法可靠界定；说明具体无法界定的边界。
4. 当前实际工作流要求完整测试。现有 Build 与本地 pre-commit 都不运行 pytest，不能假设存在
   这项门禁；dev 推送 main 本身也不触发本地全量。

执行全量前记录触发项、关联验证结论和代码已稳定的依据。多 agent 各自只跑直接与关联测试，
主任务合并检查清单并决定一次集成验证，避免每个子任务重复全量。

失败后先定位失败节点和污染组合；修复后先重跑直接及关联集，不能因“上次全量失败”自动再跑
全量。只有上述触发条件仍成立且需要新的完整快照，或关联集仍无法界定影响时才重跑，并记录
新的原因。全量通过后发生局部修改也适用同一规则。

已通过且没有新改动、新失败或未解决疑点的检查不重复执行。报告给出实际命令、结果和本轮验证
范围；历史全量通过仅是历史快照。没有触发全量而未跑全量，不是验证缺失。

### 完整门禁命令

完整门禁只在增量策略列出的触发条件成立时执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
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

packaging self-check、完整构建和实机测试按实际触及边界另选，见
[BUILD_AND_RUN](BUILD_AND_RUN.md#测试与检查)，不由全量 pytest 自动连带触发。

## 隔离与替身

- pytest `monkeypatch` 替换 subprocess、路径解析、设置和 platform/frozen 状态。
- fake process 实现 `poll/terminate/kill/wait/stdout` 等协议，验证 ProcessRunner 和 MobilePerfRunner。
- `tmp_path` 隔离 JSON/YAML/截图/报告/临时配置。
- Qt 测试直接验证可观察行为，并替换外部 service；不依赖无业务意义的私有字段不存在断言。
- fake/stub 必须实现被测边界实际消费的状态与失败语义，不能靠默认成功、随意的 `getattr`
  回退或自动吞错绕过真实协议。断言可以检查必要的调用参数与资源归属，不复制实现步骤。
- UI 隔离夹具关闭本用例创建的窗口后，对包括已关闭窗口在内的全部新顶层窗口安排删除，再投递
  `DeferredDelete`。仅调用 `close()` 或 `processEvents()` 不能证明 QObject 已释放；生命周期
  回归同时观察销毁信号、计时器停止和晚到回调。
- 清理夹具是兜底，不替代测试主体对关闭/取消的断言。仅已销毁 QObject 可被识别后跳过；活对象
  的 shutdown/close 异常必须暴露，失败后仍尽力释放资源，不能用宽泛 `except: pass` 掩盖问题。
- 测试工作流 YAML 的关键文本/结构，防止打包模式和发布资产回归。

## 测试代码规范与失效判定

1. 名称描述可观察行为及条件，主体按准备、操作、断言组织；参数化适用于同一契约的边界数据，
   不把不同生命周期路径压成一个难定位的大测试。
2. UI 测试先走实际路由并确认目标控件可见，再验证几何、文本、焦点与点击结果。隐藏旧页面的
   尺寸或已弃用入口返回值不能代表现有界面；大字体测试使用真实字体度量。
3. 异步验证优先信号、Event、Barrier 或有截止时间的条件等待。固定 sleep 只用于测试明确的
   时间行为，不能靠加长等待掩盖竞态；超时必须失败并给出目标状态。
4. 外部命令、真实设备和用户数据用受控替身/临时目录隔离。会写数据的测试不得只替换 UI 显示，
   还要替换真正的配置、服务或进程边界。
5. skip/xfail 只用于明确的平台或外部能力前提，并记录原因和替代验证方式；不以增加跳过、
   放宽断言、吞异常或删除有效用例让测试通过。
6. 清理旧测试前查明其原契约：功能只是换入口时迁移测试；兼容路径仍有消费者时保留覆盖；
   完全重复或只锁定失效内部字段的断言可移除，注明保留的用户行为。测试文件名中的旧阶段编号
   本身不构成无效证据，不做无关批量改名。
7. Ruff 覆盖修改的测试与工具文件。项目未配置 pytest-qt 或测试目录 Pyright 门禁，不把它们
   临时升级为必需工具；也不降低现有检查标准。

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

当前受控范围：`adblab/`、`controllers/`、`core/`、`gui/`、`models/`、`services/`、`utils/`、`main.py`、
`mobileperf/common/`、`mobileperf/android/`（包括其中一方 Python 适配代码）。以上一方源码已经
完成人工治理并进入默认门禁。第三方、生成文件、缓存、资源、二进制工具、`mobileperf/extlib/` 和
平台二进制工具始终排除；新增一方源码必须同步纳入受控目录，不得通过扩大排除表规避检查。

运行默认门禁：

```powershell
.\.venv\Scripts\python.exe scripts/check_comment_language.py
```

日常修改显式传入本轮生产路径；审计时可运行默认范围。测试/工具说明须准确清楚，但不把生产
模块 docstring 规则无差别应用到全部测试替身和第三方源码：

```powershell
.\.venv\Scripts\python.exe scripts/check_comment_language.py controllers gui
```

门禁只解决可自动判断的语言一致性问题。注释是否准确、是否提供必要的生命周期和失败语义，仍需
代码评审结合入口、调用链、失败路径和清理路径确认。

## 提交与发布门禁

版本与发布规则只在 [BUILD_AND_RUN](BUILD_AND_RUN.md) 维护。

本地验证只按上面的 [增量验证策略](#增量验证策略) 选择，不因准备提交就扩大范围。
修改 ADB 命令、Remote 或 MobilePerf 时，实机验证需使用授权设备；无法执行时明确列为未验证，
不能用更多离屏测试替代设备结论。打包验证条件见 [BUILD_AND_RUN](BUILD_AND_RUN.md)。

## 质量工具链

除 pytest/ruff 外，`requirements-dev.txt` 提供以下工具（配置随仓库）：

- **pyright**（类型检查）：范围和排除项见 `pyrightconfig.json`；日常对受影响生产路径运行。
- **pytest-cov**（覆盖率）：仅在评估具体覆盖缺口时使用，对已选测试附加 `--cov=<受影响包>`；
  覆盖率数字不能替代失败、取消、清理等行为断言。
- **pytest-xdist**（并行）：仅对已确认隔离的指定测试文件使用 `-n 4`。`not ui` 含 integration，
  不能当作并行安全证明；Qt 与子进程生命周期组合默认串行，避免无界 `-n auto`。
- **pre-commit**（本地钩子）：`.pre-commit-config.yaml` 已配置 ruff、中文注释门禁与
  文档链接校验三个本地钩子；首次使用执行
  `.\.venv\Scripts\python.exe -m pre_commit install`。

当前 pre-commit 三个钩子使用全目录静态检查且不接收文件名，未运行 pytest；Build 也只有静态
检查、构建与自检。这里描述现状，不把本地钩子范围复制为每次编辑后的验证要求。
