# Windows 双产物安装器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans 或 superpowers:subagent-driven-development 按任务执行；使用下方复选框记录真实结果。

**Goal:** 为现有 Windows onedir 增加 Inno Setup 安装版，同时保留原免安装 ZIP 和用户数据兼容。

**Architecture:** 安装器作为已验证 PyInstaller 产物的后处理；安装版通过独立身份文件和维护锁
协调升级/卸载。业务只增加安装入口保护与性能输出路径修复，原配置格式和跨平台打包保持。

**Tech Stack:** Python 3.11、PyInstaller、Inno Setup 6.7.3 / Pascal Script、pytest、Windows API、GitHub Actions。

**Spec:** [Windows 安装版设计](../specs/2026-10-24-windows-installer-design.md)。

状态：用户已批准并已实施；原实施阶段的本地构建、直接/关联测试和独立审阅已完成。
随后用户授权提交、推送和运行真实安装/升级/卸载 CI，并允许直接修复发现的问题。首次 CI
在 fixture 首装失败；修复推送后的第二次 CI 已通过四个平台构建，以及 Windows 独立升级
fixture 和正式产品自动安装验收。后续标准用户、官方旧载荷升级及阶段故障验收也已完成，
详见[补充验收记录](2026-10-24-windows-installer-extended-acceptance.md)。下方按实际证据更新；
人工设备、物理断电与交互取消等未执行项仍保持未勾选。

应用内下载、校验、关闭及启动安装器交接属于[独立后续计划](2026-10-24-windows-installer-update.md)，
本期不改变“检查更新 → 浏览器 → 用户手动运行安装器”的交互。后续计划目前仅规划，未实现。

## Global Constraints

- 固定 AppId `{1C0CD5FE-33F4-4BB0-964D-F2EC6A79F062}`，当前用户安装，稳定 `ADBLab.exe`。
- 安装器 `ADBLab-win-x64-vX.Y.Z-setup.exe`；原 ZIP 文件名和内容结构不变。
- 用户目录、配置 schema、更新交互、原多实例能力及 macOS/Linux 打包模式保持。
- 新代码归现有 `core/`、`services/`、`scripts/`、`tests/`、`docs/`，不新增顶层目录。
- 禁止全局结束 ADB、递归清空安装目录、清除用户数据、自动迁移便携目录。
- 不添加生产依赖；版本仅来自 `utils/app_metadata.py`，本期保持 `3.3.2`，不正式发布。
- 原实施阶段不提交、不推送、不触发远程 CI；后续用户已明确授权提交、推送当前
  `ui-redesign` 并以 `publish=false` 运行安装验收，详见下方远程 CI 记录。
- 使用 `.venv`；编译器采用固定官方版本便携部署，不修改系统软件配置。
- 未得到实际结果不能勾选“通过”；安装测试只在一次性环境运行，失败传播不得放宽。

## Review Focus

1. 安装预检后另一个进程启动：保护业务准入，但 bootloader/独立工具仍可竞争；失败不能冒充成功。
2. 恶意或损坏旧清单、重解析点、用户放入的额外文件：不得越界或递归删除（任务 3）。
3. worker 实际结果目录与 GUI/归档预测不同：使用同一规范化快照，保留调用方对象（任务 1）。
4. 更高版本升级被同版本重装测试代替：分别验证升级、修复、降级与过期文件清理（任务 5）。
5. 只改环境变量伪装为隔离安装：真实 HKCU/快捷方式只能在一次性环境验证（任务 5）。

## 文件职责与并行边界

| 文件 | 职责 |
| --- | --- |
| 新 `core/windows_installation.py` | 安装身份读取、Windows 共享运行锁与释放、可操作失败分类 |
| 修改 `main.py` | 在入口分派前取得安装运行锁，统一 GUI/CLI 失败返回和 finally 释放 |
| 修改 `services/mobileperf_runner.py` | 单次运行保存路径规范化快照；保持结果预测与 worker 一致 |
| 新 `scripts/windows_installer/manifest.py` | 安装身份常量、载荷清单/路径校验、staging 规则，不依赖 Qt |
| 新 `scripts/windows_installer/ADBLab.iss` | 权限、文件映射、快捷方式、版本与安装/卸载事件入口 |
| 新 `scripts/windows_installer/maintenance.iss` | 锁、路径和文件占用预检、旧文件精确清理、元数据生命周期 |
| 新 `scripts/prepare_inno_setup.py` | 固定官方资产下载、摘要/签名验证、受限目录便携准备与版本验证 |
| 新 `scripts/build_windows_installer.py` | 校验输入、隔离 staging、生成清单、调用 ISCC、验证非空输出 |
| 新 `scripts/check_windows_installer.py` | 一次性 Windows 环境的真实安装/修复/卸载验收，非本机默认命令 |
| 修改 `scripts/check_build_artifacts.py` | 精确五产物集合及安装 EXE 静态校验，保留原归档校验强度 |
| 修改 `.github/workflows/Build-exe.yaml` | 仅 Windows 插入安装构建/验收，上传双产物并阻断失败发布 |
| 新/修改关联 `tests/` | 对应各项测试、安装器 fixture 和 CI 契约，不弱化既有断言 |
| 修改构建指南与知识文档 | 把已验证命令和兼容边界归入唯一事实来源 |

任务 1 和任务 2 可并行；任务 3 消费任务 2 的锁协议；任务 4/5 顺序集成。主 agent 负责
设计、共享协议、CI 集成和验证；实现结束由未参与实现的 agent 独立审阅。默认复用当前干净
`ui-redesign` 工作区；每次开工复核状态，新增外部修改必须保留，不因任务结束自动 commit。

## Task 1：固定性能输出目录的运行边界

**Files:** `services/mobileperf_runner.py`；新 `tests/test_mobileperf_output_paths.py`；
关联 `tests/test_model_mobileperf.py`、`tests/test_mobileperf_runner_concurrency.py`、
`tests/test_performance_service_boundaries.py`、`tests/test_performance_start_lifecycle.py`。

**Interfaces:** 保留 `MobilePerfRunConfig` 对外接口与原始序列化；runner 内增加
`_resolved_run_config(config: MobilePerfRunConfig) -> MobilePerfRunConfig`，返回独立副本。
空值基准 `Path.home() / "ADBLab" / "mobileperf"`，相对路径基准 `Path.home() / "ADBLab"`。

- [x] 补失败测试：空路径得到指定绝对目录；相对路径不随 cwd 或冻结资源根改变；绝对/UNC
  保持；盘符相对路径失败；调用方 config 不变；临时配置、baseline、结果查找使用同一路径。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_mobileperf_output_paths.py`，确认失败原因对应现有边界。
- [x] 在 start 前置阶段生成快照，统一交给 `_last_config`、配置写入、baseline 和归档；
  确认目标合法可写之后才启动 worker。失败沿用现有启动错误/取消清理协议。
- [x] 覆盖安装资源目录、拒绝写入、取消和重复启动；不修改配置字段默认值或历史 schema。
- [x] 运行上述直接测试，再运行列出的四份关联测试；UI 测试设置 `QT_QPA_PLATFORM=offscreen`。

## Task 2：安装版共享运行锁及入口接线

**Files:** 新 `core/windows_installation.py`、`tests/test_windows_installation.py`；
修改 `main.py`；关联 `tests/test_gui_startup.py`、`tests/test_startup_process.py`、已有 CLI 入口测试。

**Interfaces:** `acquire_installation_guard(executable: Path | None = None) -> InstallationGuard | None`；
`InstallationGuard.close() -> None` 幂等；`InstallationUnavailable` 分类但不暴露实际路径。
源码/非 Windows/无安装标识返回 None；有效安装共享读 lock，取锁后复核 ready 状态；
任一控制文件存在却标识损坏或 pending 维护状态均失败关闭，维护准入失败退出码 73。

- [x] 补失败测试：免安装和其他平台不触及 Win32；标识损坏/缺锁/拒绝访问阻止初始化；
  两个进程可以同时持有读锁；独占维护锁阻止读锁；最后一个读者退出才允许维护。
- [x] 先运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_windows_installation.py` 确认新契约未实现。
- [x] 用 ctypes 明确 Win32 参数和指针宽度，创建不继承的文件句柄；只打开既有稳定 lock 文件。
- [x] 在 main 最外层入口接线，先取锁再分派所有模式；正常/异常返回均释放；GUI 使用可操作
  提示，CLI/worker 标准错误和非零返回；不能依赖 Qt 已启动或在无控制台模式静默失败。
- [x] 测真实子进程并发/崩溃句柄回收/维护期间启动；Mock 测试不替代 Windows 文件锁测试。
- [x] 运行直接与入口关联测试、受影响模块 Ruff/Pyright；确认现有 worker UTF-8 和参数退出码不变。

## Task 3：编译器准备、安装器载荷与升级/卸载协议

**Files:** 新 `scripts/windows_installer/{manifest.py,ADBLab.iss,maintenance.iss}`、
`scripts/prepare_inno_setup.py`、`scripts/build_windows_installer.py`；
新 `tests/test_windows_installer_build.py`、`tests/test_prepare_inno_setup.py`、
`tests/test_windows_installer_manifest.py`。额外提交日志 `.adblab-files.txt.previous` 保存旧清单，
用于新清单已发布但 ready 身份尚未提交时恢复归属；它不进入原 ZIP。

**Interfaces:** 构建 CLI
`python scripts/build_windows_installer.py --source-dir <onedir> --entry-name <原EXE名> --output-dir <dist> --iscc <ISCC.exe>`；
增加 `--dry-run` 只读预览。版本自动来自 app_metadata，不提供生产版本任意覆盖开关。
准备 CLI `python scripts/prepare_inno_setup.py --destination <任务构建目录>`。

- [x] 先测缺失/空主入口、缺 `_internal`、重解析点、大小写冲突、非法相对路径、摘要不符、
  编译器失败/超时、输出缺失都非零；dry-run 不下载、不复制、不写文件。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_windows_installer_build.py tests/test_prepare_inno_setup.py`，确认失败后实现。
- [x] 固定官方 6.7.3 URL/SHA256 和有效 Authenticode；只向经校验的构建子目录便携部署。
  已有目录只接受可核实的目标版本，不执行不明同名编译器，不递归删除任意传入路径。
- [x] 复制 staging，稳定入口名，预置 ADB 同内容副本，生成载荷清单；确认源目录摘要未变。
- [x] 写 ISS 当前用户安装、稳定身份、快捷方式/卸载项；禁止自动关闭/重启其他进程。
- [x] 实现新目录安全检查、既有身份/数值版本校验、维护锁和全目标文件预检；同版本修复、
  升级允许，降级拒绝。预检失败不修改既有 payload。
- [x] 实现载荷复制前发布 installing/pending 清单，首次也先建立标识；成功后发布 ready 并
  清理同内容 pending。installing 仅原版本且相同清单可修复，removing 仅继续卸载；损坏身份
  不自动接管，恢复指引保留在指南。实现、helper 回归与已执行安装事件分别提供对应证据。
- [x] 在 fixture 构造“A 已完成、B 部分写入”的指定中断状态，再用真实 Inno 事件验证
  C 被拒绝、原 B 修复、随后 C 升级；这不是终止正在运行的安装进程或任意阶段断电测试。
- [x] 对 3 个首装、9 个升级、2 个共享冲突、4 个卸载事件阶段实际注入故障，核验状态与恢复；
  installing 恢复时拒绝同版本不同载荷，并验证真实安装过程中启动应用的竞争，详见补充记录。
- [ ] 物理断电、磁盘故障与未列出的任意故障点；已执行的进程退出不证明所有残留状态或原子回滚。
- [x] 实现精确旧文件清理和元数据成功发布；路径越界/重解析点/待删文件改动阻断，未知文件保留。
- [x] 载荷统一 `uninsneveruninstall`，由 usUninstall 按当前/pending 清单、路径和摘要精确删除，
  失败 Abort；Inno 只清理自身系统集成。升级中已退役路径新放入的用户文件必须保留。
- [x] 删除前写 removing；usPostUninstall 实际核对载荷、快捷方式、注册项后才清理控制文件。
  残留误报回归及真实成功卸载已通过；失败/取消释放锁、可选运行先放锁仍为实现与限定
  helper/静态证据，交互取消和安装完成后可选运行未作真实验收。
- [x] 旧卸载器验证自身登记目录与现注册位置/磁盘身份；模拟旧目录改名后原位置重新安装，
  旧卸载器不得影响新安装。损坏信息不自动接管，人工保留目录恢复流程写入指南。
- [x] 编译最小 fixture，用真实 Inno 引擎验证代码可编译和已列出的安装事件行为。

## Task 4：双产物发布校验与 CI 集成

**Files:** `.github/workflows/Build-exe.yaml`、`scripts/check_build_artifacts.py`、
`tests/test_ci_contracts.py`、`tests/test_check_build_artifacts.py`。

**Interfaces:** 原四产物路径不变；新增
`ADBLab-win-x64/ADBLab-win-x64-vX.Y.Z-setup.exe`。
Release 仍调用 `check_build_artifacts.py release --directory ... --version vX.Y.Z`，不添加放行模式。

- [x] 测精确五文件集合、安装 EXE 缺失/额外/错版本/空/链接/非 PE 均失败；四归档 CRC、入口、
  完整 TAR/GZIP 校验继续有效；更新 fixture 而非删除原坏包用例。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_check_build_artifacts.py tests/test_ci_contracts.py`，确认新产物未受支持。
- [x] 扩展 validator 对 setup 静态结构的最低检查；明确静态验证不能取代真实安装验收。
- [x] 在 Windows 冻结探针后、压缩删除 onedir 前插入准备/编译/真实验收；任何失败禁止压缩
  上传。保留 macOS/Linux 的 frozen 检查及精确归档路径。
- [x] Windows 精确上传两条文件路径，其余平台继续一条；不能上传 `dist/*` 或 staging。
- [x] 保留 publish=false、正式发布校验、权限和 tag 不变；原实施阶段未触发远程 workflow
  或发布。后续授权验收使用 publish=false，不创建 Release 或修改 tag。
- [x] 跑两份直接测试并核对最终 YAML 顺序与路径；安装器工具不进入生产 requirements。

## Task 5：隔离验收、文档与独立终审

**Files:** 新 `scripts/check_windows_installer.py`、`tests/test_windows_installer_validation.py`、
`tests/fixtures/windows_installer/`；更新 `docs/guides/BUILD_AND_RUN.md`、
`docs/project-knowledge/BUSINESS_FLOW.md`、`docs/README.md`；需要时在风险账本记录未验证边界。

**Interfaces:** 验收 CLI 接收 installer、预计版本与专属临时根；仅在显式的一次性 Windows
验证环境运行。先确认真实 AppId 未安装；若已有真实安装则拒绝，不备份/替换用户注册项。
使用实际安装器固定生产身份，不提供测试后门改变发布包身份。

- [x] 为验收器补环境拒绝、已安装拒绝、子进程超时/非零、清理失败传播测试；创建路径先验证
  绝对目标严格位于本次临时根，清理只针对本次创建资源，不使用通配递归删除。
- [x] 编译/运行 fixture，验证 A→B 升级、旧 A 降级拒绝、B 同版本修复、B→C 升级、退役文件
  清理、未知文件和退役路径新用户文件保留、坏清单、独立工具占用及指定中断状态恢复。
  fixture 的拒绝场景逐次核对安装树全文件摘要和卸载登记；外部数据哨兵由正式产品验收末尾检查。
- [x] 真实完整事件验证修改过的受管文件阻止卸载、四个卸载阶段故障，以及安装中启动应用
  竞争；实际阶段与保留边界见补充记录，不把它们视为交互取消或原子回滚证明。
- [x] 构建实际应用：`.\.venv\Scripts\python.exe scripts/build_app.py --name ADBLab --onedir --windowed --icon icon.ico`。
- [x] 跑源码 `main.py --self-check packaging` 和实际 `check_build_artifacts.py frozen` 三项；
  用已确认编译器构建 setup，保留具体产物路径、摘要、版本及编译退出码。
- [x] 在一次性 Windows runner 真实安装，验证稳定入口、开始菜单快捷方式文件存在、卸载
  登记位置/版本、安装后 frozen 三探针、共享运行锁/独立工具占用拒绝、同版本修复、
  卸载/重装及数据/额外文件哨兵；未发送 ADB 设备命令。自动断言不单独证明登记所在 hive。
- [x] 在含中文与空格的路径执行 fixture 和正式产品自动安装事件；这不替代向导中的人工交互检查。
- [x] 一次性 runner 上使用真实非管理员账户，执行官方 3.3.1 应用载荷到 3.3.2 的升级和卸载。
  历史没有正式 setup，使用固定官方 ZIP 的测试封装；不把它称为历史安装器之间升级。
- [ ] 人工检查安装向导、取消、中文/空格路径、开始菜单、卸载入口，以及实机 ADB/scrcpy；
  无设备时记录未验证，不为通过改变业务行为。
- [x] 根据实际代码和验证结果更新指南及设计/计划状态，避免把未运行命令写成已验证操作。
- [x] 运行改动文件 Ruff、生产路径中文注释检查、受影响共享类型 Pyright、
  `scripts/check_source_text.py`、`scripts/check_doc_links.py` 和 `git diff --check`。
  关联验证稳定后按测试指南判断是否触发全量；不因新增安装器自动跑全量 GUI 套件。
- [x] 独立 agent 审阅实现与设计：数据保留、失败传播、竞态、路径删除、产物集合和验证真实性。
  主 agent 修复确认的问题并重跑对应测试，再记录剩余人工/环境限制。

## 验收记录

- 设计/计划阶段：独立 builder check 已完成，最终结论 `nothing important left`。
  评审中补齐四项：中断状态与持锁后复核；卸载真实后置条件；历史卸载日志对退役路径的
  误删防护；未完成升级仅由原版本且相同载荷清单的安装器恢复。该结论仅证明设计可实施。
- 2026-10-24 文档检查：`scripts/check_doc_links.py` 通过（95 份文档）；
  `git diff --check` 通过，两份新增文档也通过 `git diff --no-index --check -- NUL <file>`。
- 2026-10-24 实施完成：性能输出路径快照、安装入口共享锁、安装器 staging/清单/维护状态、
  编译器准备、双产物 CI、静态产物门禁、一次性环境验收脚本及独立升级 fixture 均已落地。
- 原实施阶段版本保持 `3.3.2`；当时未新增生产依赖、提交、推送、触发远程 workflow 或
  正式发布。后续授权提交与 CI 结果单列于下方记录，版本与生产依赖保持不变。
- 运行时和安装主体分别独立审阅，确认的问题以原生/隔离子进程回归修复：stderr-only 维护
  错误提示、ready 残留 pending 进入 removing 后恢复、真实 Shell 数据哨兵，以及前置冻结
  自检创建数据目录与验收器过严拒绝之间的 CI 衔接。
- 本地已实际构建 Windows windowed onedir。更新入口修复后的第二次收集遇到已有 dist
  目录，未删除原目录；使用生成的同一 spec 收集到 `build/installer-final-dist/` 并成功。
  源码 packaging 自检、最终冻结 EXE 的 packaging/worker help/UTF-8 三项均通过。
- 固定 Inno 6.7.3 已便携准备，来源 SHA256、Windows 签名和真实引擎版本核实通过；
  生产 setup 及 A/B/C 三份独立升级 fixture 实际编译成功。原生协议探针只执行
  InitializeSetup 的隔离 helper 验证后返回 False，不进行产品安装。
- 安装器输入含 1978 个文件；staging/ZIP 创建前后核对源载荷摘要一致。实际 ZIP 完整 CRC
  和入口验证通过，实际 setup PE 结构验证通过。下表是首次 CI 发现问题前的历史本地编译
  产物，未签名、未发布；旧 setup 已由修复后的本地重建产物替代，新摘要见下方记录。
  ZIP 源载荷未变，下表 ZIP 摘要仍有效；远程 CI 产物独立构建，不混用本地文件摘要。

| 产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| `dist/ADBLab-win-x64-v3.3.2.zip` | 153907568 | `0360d70e1a4b47eb15506fb8c6ed9073316a86b7dc1fc0de5cbc521ac8dff07e` |
| `dist/ADBLab-win-x64-v3.3.2-setup.exe` | 107291552 | `6b72b0060dbd953e0c4fe0f48a6b58cc9d292276bc0424f524386e39d23877aa` |

本地实际命令的核心入口如下，已有产物不要不经检查重复覆盖：

```powershell
.\.venv\Scripts\python.exe scripts/build_app.py --name ADBLab-win-x64-v3.3.2 --onedir --windowed --icon icon.ico
.\.venv\Scripts\python.exe -m PyInstaller build/app-spec/ADBLab-win-x64-v3.3.2.spec --distpath build/installer-final-dist
.\.venv\Scripts\python.exe main.py --self-check packaging
.\.venv\Scripts\python.exe scripts/check_build_artifacts.py frozen --executable build/installer-final-dist/ADBLab-win-x64-v3.3.2/ADBLab-win-x64-v3.3.2.exe --timeout 60
.\.venv\Scripts\python.exe scripts/build_windows_installer.py --source-dir build/installer-final-dist/ADBLab-win-x64-v3.3.2 --entry-name ADBLab-win-x64-v3.3.2.exe --output-dir dist --iscc build/tools/inno-6.7.3/ISCC.exe
```

原实施阶段最终直接测试集合 **342 passed、1 skipped**（18.09 秒）；启动/worker、性能用例关联集合
**209 passed、1 skipped**（37.29 秒）。独立收口审阅的验收/fixture/CI 集合另为 94 passed，
与直接集合重叠，不重复计入总数。独立审阅未发现剩余代码阻断。

实际测试范围：

```powershell
# 当前环境临时加入现有 Git Bash；不修改系统 PATH。
$env:Path = 'C:\Program Files\Git\bin;' + $env:Path
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_windows_installation.py tests/test_windows_installer_manifest.py tests/test_windows_installer_build.py tests/test_windows_installer_validation.py tests/test_windows_installer_upgrade_fixture.py tests/test_windows_installer_pe.py tests/test_prepare_inno_setup.py tests/test_build_app.py tests/test_check_build_artifacts.py tests/test_ci_contracts.py tests/test_mobileperf_output_paths.py tests/test_worker_stdio.py
.\.venv\Scripts\python.exe -m pytest -q -rs tests/test_gui_bootstrap.py tests/test_gui_startup.py tests/test_startup_process.py tests/test_native_execution_boundary.py tests/test_native_launcher.py tests/test_model_mobileperf.py tests/test_mobileperf_runner_concurrency.py tests/test_performance_service_boundaries.py tests/test_performance_start_lifecycle.py
```

修改文件 Ruff、生产注释检查、受影响模块 Pyright 通过；源码文本检查通过 867 个文件，
文档链接/frontmatter 检查通过 96 份文档，`git diff --check` 及新增文件 whitespace 检查通过。
本轮仅按启动/worker、性能路径和打包边界扩大关联测试，未触发全量 GUI 套件。
已有两项平台跳过不变：Windows 不直接执行 shebang 的产物测试、只适用于 POSIX 的
SIGTERM 忽略探针；唯一类型的 warning 来自已安装 qfluentwidgets 的 scipy 弃用导入。
当前 PowerShell PATH 未暴露 bash，CI 契约测试临时加入已存在的 Git bin 后通过；未安装
系统工具。main 的定向 Pyright 使用原规则与当前解释器实际 sys.path 的临时配置，解决
本机 system-site-packages 的发现差异，未修改仓库类型标准或生产依赖。

### 2026-10-24 授权提交与远程 CI 验收

用户明确授权提交并推送当前 `ui-redesign` 分支、运行安装/升级/卸载 CI，并直接修复验收
发现的问题。该授权更新了原实施阶段“不提交、不推送、不触发 CI”的范围；本轮仍使用
`publish=false`，不正式发布、不更改版本，也不在本机执行真实产品安装。

| 提交 | 内容与状态 |
| --- | --- |
| [`b955795`](https://github.com/BlackHu-art/ADBLab/commit/b955795638a626a831c9bf7c0b3ffda6fd31c8f9) | Windows 安装版、免安装双产物及升级保护；已推送 `ui-redesign` |
| [`5c79f96`](https://github.com/BlackHu-art/ADBLab/commit/5c79f96f22c1d1d611a084f615347f4616e44615) | Windows 失败时输出限定安装日志的有界尾部；不新增 artifact，不改变成功构建与发布集合；已推送 |
| [`2b1a2f9`](https://github.com/BlackHu-art/ADBLab/commit/2b1a2f930228ee1564d41c44181ec9e83f9ace72) | 修复安装目录准入与卸载验收等待竞态；已推送 |

首次真实运行 [40074841221](https://github.com/BlackHu-art/ADBLab/actions/runs/40074841221)
以 `publish=false` 执行。Windows job `120815904245` 在独立 fixture A 首次安装时失败，
日志报告 `Unknown constant "userprofile"`：Inno Setup 6.7.3 不支持该常量；编译不能验证
运行期常量，原 InitializeSetup 协议探针又仅检查危险目录并把任意异常当作拒绝，掩盖了
目录预检始终报错的问题。新增普通目录正向准入后原生复现同一错误，再修复通过。此次
失败不能视为升级/卸载或正式产品安装验收通过。

本轮修复了两项已确认问题：

1. 安装目录预检改用 Windows Shell profile API 获取实际用户目录，并同时保护进程环境
   指向的用户目录；补充对应原生目录边界探针，避免只靠编译验证运行期常量。
2. 两个验收器的卸载等待原先只观察 marker 与卸载器消失，会在维护锁等后续清理尚未完成时
   提前退出并误报失败。等待与最终断言现共用完整后置条件，覆盖载荷、控制文件、卸载器、
   登记及正式产品快捷方式；保留 20 秒期限、残留失败和状态读取异常传播。回归先出现
   **9 failed、2 passed**，修复后两个直接文件 **37 passed**，独立审阅重跑亦为 **37 passed**。

主任务集成命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_windows_installer_manifest.py tests/test_windows_installer_validation.py tests/test_windows_installer_upgrade_fixture.py
```

结果为 **83 passed**（12.30 秒）。随后 `scripts/check_source_text.py`（867 文件）、
`ruff check .`、`scripts/check_comment_language.py`、`scripts/check_doc_links.py`（96 份文档）
及 `git diff --check` 均通过；定向 `pyright scripts/check_windows_installer.py` 为
**0 errors、0 warnings**。修复经独立审阅，未发现剩余可行动问题；这些结果仅证明本地修复
与回归通过，不能代替完整安装生命周期的远程结果。

第二次真实运行 [40075896897](https://github.com/BlackHu-art/ADBLab/actions/runs/40075896897)
使用修复提交 `2b1a2f930228ee1564d41c44181ec9e83f9ace72`，目标分支 `ui-redesign`，
`publish=false`；于 **2026-10-24 07:53:16Z 至 08:07:23Z** 执行并最终 **SUCCESS**。
version、Windows x64、macOS Intel、macOS ARM64、Linux x64 均成功，release job 为
**skipped**，没有正式发布。四个平台的 Actions artifacts 均可从该运行页面下载。

Windows job [120819075499](https://github.com/BlackHu-art/ADBLab/actions/runs/40075896897/job/120819075499)
的 `not ui` 集合为 **3897 passed、55 skipped、4487 deselected、36 warnings**（269.18 秒），
这不是全量 GUI 套件。原 onedir 冻结三探针通过；08:06:57Z 的两段验收日志分别报告：

- 独立 fixture 完整事件通过：A→B 升级、降级拒绝、同版本修复、退役路径及未知文件保留、
  工具占用拒绝、损坏清单拒绝、指定 pending B 状态恢复，以及移动旧卸载器拒绝。
- 正式产品自动验收通过：安装清单、安装后冻结三探针、维护互斥、同版本修复、卸载与
  数据保留；实际调用还完成重装再卸载，并检查开始菜单快捷方式文件和卸载登记位置/版本。

Windows artifact `12553557405` 精确上传 `ADBLab-win-x64-v3.3.2.zip` 和
`ADBLab-win-x64-v3.3.2-setup.exe` 两个文件，上传成功。该 **Actions artifact 归档**为
264916448 字节，SHA256
`db655f4db6c9a60062a3e696115c2d5e038ed9e5807538923a1ae85df3df68da`；它不是内部 setup
单文件的摘要。另外三个平台 artifact 也均来自本次同一提交；本轮没有执行 release job 的
下载后五产物集合校验，也没有创建 GitHub Release。

修复后的本地生产安装器已重新编译并通过构建器的 PE 结构检查（编译退出 0），替换了
`dist/ADBLab-win-x64-v3.3.2-setup.exe`：107292239 字节，SHA256
`0c76117cfadb95cbb82d6b59f00c2b86e674074f18060eada37d4fdedca6a5ba`。
ZIP 源载荷未改动，上方 ZIP 摘要仍有效；这些本地产物未执行真实安装，远程产物独立构建。

**首轮结束时未完成的验收**（后续进展见[补充记录](2026-10-24-windows-installer-extended-acceptance.md)）：
本机明确拒绝运行正式安装验收；未伪造 hosted runner 环境。
远程已配置的自动验收通过，但旧真实应用版本的跨版本升级、标准用户、向导/取消、桌面
快捷方式创建、开始菜单实际启动与卸载入口人工验收、真实 ADB/scrcpy 设备验证仍未执行。
各阶段失败/断电注入、installing 中断恢复时同版本不同载荷的完整事件拒绝、修改过受管
文件的完整卸载拒绝与真实安装中启动应用竞争也未执行。fixture 只构造一个中断状态，不代表任意断电点的
原子回滚；晚期卸载失败仍可能需要保留旧目录后在原位置空目录重装。

附：早期编译器版本探针生成的空 `Output/` 清理被自动审批返回 `blocked by policy`；
已保留该空目录，后续探针改在自身临时目录内运行，不影响受控源文件。
