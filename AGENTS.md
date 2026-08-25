# ADBLab Codex 项目指令

## 项目与架构

- ADBLab 是 Python 3.11 + PySide6 桌面应用，入口为 `main.py`，主要面向 Windows，使用
  `requirements*.txt` 管理依赖并通过 PyInstaller 打包。
- `gui/` 负责界面；`controllers/` 负责信号路由和协调；`models/`、`services/` 负责业务与设备
  适配；`core/` 提供命令、进程、设置和日志基础设施；`adblab/` 放置应用用例与 Qt 适配；
  `tests/` 和 `docs/` 分别保存测试与知识库。
- 短命令使用 `core.exec.CommandRunner`，受控长进程使用 `ProcessRunner`。设备 shell 动态值必须
  经过现有校验/quote 边界，不在 UI 中直接拼接复杂命令。
- 配置、日志等用户数据写入 `utils/user_data.py` 提供的目录；onefile 工具缓存使用
  `utils/runtime_tools.py`；资源通过项目现有资源解析接口访问，不假设源码或安装目录可写。

## 指令优先级与必读内容

- 本文件适用于整个仓库。开始工作时，从仓库根到目标目录检查是否存在更近的
  `AGENTS.override.md` 或 `AGENTS.md`；局部规则只约束其目录范围，冲突时更近的局部规则优先。
- 先读 `docs/README.md`，再按任务读取它指向的知识文档。改变运行行为、共享状态、持久化、
  外部命令、线程/进程生命周期或公共接口时，还应阅读相关架构/模块/业务流程文档和现有测试。
- 当前代码、工程配置和可执行测试是实现事实来源；它们与文档冲突时，先核实代码，再修正文档
  或把无法确认的结论标为“待确认”。

## 开始任务前

- 明确用户目标、验收条件和最小修改范围。简单、低风险且目标明确的任务可直接执行，不输出
  冗长计划；只有信息缺失会改变实现方向或风险时才询问。
- 运行 `git status --short`，并检查目标文件现有差异。未提交修改均视为用户资产，不得覆盖、
  删除、回退、暂存或夹带提交；若目标区块冲突且无法确认原意，停止该文件修改并说明。
- 未经明确要求，不执行 `git reset --hard`、`git checkout --`、`git restore`、`git clean`、
  commit、push、rebase 或冲突解决。
- Bug 修复前先用代码证据、复现步骤或直接测试确认问题仍存在；检查入口、调用链、失败/取消路径、
  清理路径和相关测试。无法确认时不要机械修改。

## 通用修改原则

- 修复根因，采用最小、清晰、可验证的改动；不做无关重构、批量改名、全项目格式化或顺手清债。
- 默认保持公共接口、配置、用户数据格式、用户交互和平台兼容性。不要为单一需求引入无必要的
  全局状态、模块耦合或过度抽象。
- 不通过删除/跳过测试、放宽断言、降低类型或 Lint 标准让检查通过；不使用空 `except`、宽泛吞错
  或伪造成功结果掩盖失败。
- 优先复用现有依赖。运行依赖在 `requirements.txt`，构建依赖在 `requirements-build.txt`，开发
  工具在 `requirements-dev.txt`；使用仓库 `.venv`，不污染系统 Python。
- 生产代码注释和 docstring 使用规范中文，技术标识保留原文。注释解释业务原因、约束、不变量、
  失败语义和资源归属，不复述显然代码；公共边界及并发、取消、危险操作、持久化、清理接口应有
  契约说明。详细规则见 `docs/guides/TESTING_GUIDE.md`。
- 只在任务明确涉及且来源已确认时修改 `resources/icons/`、`scrcpy-win64/`、
  `mobileperf/extlib/` 或平台二进制。外部 ZIP 必须使用 `utils.archive.safe_extract_zip()`。
- 应用版本只在 `utils/app_metadata.py` 修改。普通本地/dev 任务不改版本；明确准备 dev 推 main
  或发布时按既有版本规则处理，主/次版本仅按用户要求或发布计划调整。

## PySide6 规则

- 只在 GUI 主线程操作控件；耗时 I/O、ADB 和进程等待不得阻塞 Qt 事件循环。后台任务通过信号槽
  返回数据、状态和错误，不从 `QThread`、`QRunnable` 或 Python 线程直接改 UI。
- 沿用项目已有的 QThread/QThreadPool、worker、TaskSupervisor 和 ProcessRunner 生命周期模式。
  窗口关闭时停止并等待 worker、Timer、reader 和外部进程，断开晚到回调；必要时在安全事件循环
  边界使用 `deleteLater()`。
- 明确 QObject 父子关系和所有权，避免重复连接信号、对象销毁后回调，以及 lambda 在循环中错误
  捕获变量。重复启动入口要有禁用、忙碌或幂等保护。
- 用户提示只提供可操作信息，开发诊断写日志；两者都不得暴露密钥、真实设备标识或不必要的本机
  路径。资源、图标和运行时工具路径必须同时兼容源码与 PyInstaller 环境。

## 按任务场景工作

- **只读分析/评审**：默认不改文件；结论引用文件、类或函数依据，区分已确认问题、潜在风险和
  待验证项，不为增加问题数量提出无意义重构。
- **Bug 修复**：先确认问题，能稳定表达失败时优先补回归测试，再修根因并运行直接及关联测试；
  说明无法自动覆盖的场景。
- **新功能/重构**：先确认边界和验收条件，沿用现有层次与组件。重构默认不改变行为，先取得相关
  测试基线，分步进行，不把架构迁移与业务变化混在同一批。
- **UI 修改**：保持现有主题、字体、图标和交互体系；检查布局、高 DPI、焦点/快捷键、空/忙碌/
  错误状态及重复点击。运行相关 Qt 测试；视觉项无法自动验证时给出人工检查步骤。
- **线程/后台任务**：验证成功、失败、取消、重复启动和窗口关闭路径；确认对象可释放、进程可停止、
  应用退出无新增残留，并为确定性竞态补测试。
- **测试修改**：测试可观察行为而非偶然实现细节；不删除有效测试或降低断言。GUI 测试沿用项目
  现有 pytest + QApplication/离屏模式；项目未配置 pytest-qt，不把它写成必需工具。
- **文档修改**：保持单一事实来源；命令、配置、公共行为、用户流程或架构边界变化时同步对应
  `docs/`，运行现有链接/frontmatter 检查。纯内部实现未改变文档事实时不为形式改文档。
- **依赖/打包/发布**：区分运行、构建、开发依赖，评估 PyInstaller 和跨平台影响。沿用
  `ADBLab.spec`/当前 CI 打包方式，不写入本机绝对路径；未经明确要求不执行正式发布。
- **安全修改**：不读取、输出、提交或上传密钥、Token、证书、密码、用户数据和真实设备唯一标识；
  不执行来源不明的远程脚本，不削弱输入校验、权限边界或目标校验。

## 必须先确认

以下操作先说明选项、影响和推荐方案并等待用户确认：删除文件或功能；破坏公共接口；改变用户
数据格式或执行迁移；新增/删除/升级生产依赖；大规模架构重构；修改 CI/CD 或发布流程；正式发布；
安装系统软件或修改全局配置；登录/操作外部账号；上传代码或数据；产生费用；不可逆操作；或存在
两个影响明显不同的合理方案。普通的需求内代码编辑、关联测试和只读静态检查无需重复确认。

## 最小充分验证

- 默认先运行直接测试，再按调用链扩大到受影响模块；代码、测试或方案未稳定时不跑全量。dev 推送
  main 本身不触发本地全量测试。
- 全量测试只在用户明确要求、发布验收、影响范围无法可靠界定或 CI 固定门禁时，在代码冻结后集中
  执行。局部后续改动先重跑关联测试；未触发全量条件而未跑全量不属于验证缺失。
- 使用项目已有工具，不默认运行 `compileall`，不要求未配置的 mypy、pytest-qt、Sphinx 或 MkDocs。
  无法运行的检查必须说明原因，不能表述为通过。

常用命令（把 `<...>` 替换为本次目标）：

```powershell
# 直接/关联测试
.\.venv\Scripts\python.exe -m pytest -q <test-file-or-node>

# 修改文件的 Lint；共享类型接口变化时对相关生产模块运行 Pyright
.\.venv\Scripts\python.exe -m ruff check <changed-python-files>
.\.venv\Scripts\python.exe -m pyright <affected-production-paths>

# 中文注释与文档
.\.venv\Scripts\python.exe scripts/check_comment_language.py <changed-production-paths>
.\.venv\Scripts\python.exe scripts/check_doc_links.py
git diff --check
```

场景补充：

- UI/线程修改：使用相关 pytest；需要离屏时先设置 `$env:QT_QPA_PLATFORM = "offscreen"`，并覆盖
  成功、失败、取消、关闭和清理路径。
- 启动入口、依赖、资源收集、运行时路径或打包边界修改：运行
  `.\.venv\Scripts\python.exe main.py --self-check packaging`。
- PyInstaller/spec/依赖/资源或发布验收：经确认后运行
  `.\.venv\Scripts\python.exe -m PyInstaller ADBLab.spec --noconfirm --clean`，再验证产物的
  `--self-check packaging`。
- 完整门禁（仅在上述触发条件成立时）：
  `.\.venv\Scripts\python.exe -m pytest -q`、`.\.venv\Scripts\python.exe -m ruff check .`、
  `.\.venv\Scripts\python.exe -m pyright` 和 `git diff --check`。

## 完成汇报

简洁说明修改内容和原因、涉及文件、实际运行的命令及结果、未运行/无法运行的检查、用户可感知或
兼容性变化，以及剩余风险和人工验证步骤。不要重复完整实施过程，也不要把“未验证”写成“通过”。
