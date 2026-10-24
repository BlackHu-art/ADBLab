# Windows 应用内安装包升级后续实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans 或
> superpowers:subagent-driven-development 按批准后的任务执行；每项先写失败测试，再实现和验证。

**Goal:** 在现有手动检查更新基础上，为 Windows 安装版提供显式下载、校验和退出后交接安装器的流程。

**Architecture:** 继续由 `services/` 处理发布资产契约和状态，Qt adapter 负责异步网络及生命周期，
About 只呈现状态并发出用户意图；独立交接进程等待应用关闭后启动已验证的 setup。
安装器仍负责版本、目录、维护锁和载荷归属；应用不自行覆盖安装目录。

**Tech Stack:** Python 3.11、PySide6 QtNetwork、现有关闭屏障、Windows 进程与文件 API、Inno Setup。

**Spec:** [应用内升级设计](../specs/2026-10-24-windows-installer-update-design.md)，沿用
[双产物安装设计](../specs/2026-10-24-windows-installer-design.md)的维护协议。

状态：**实现与本地验收已完成，正式发行版端到端升级仍待真实 setup 资产**。以下记录区分已执行验证和外部条件限制。

## 本轮接口与执行分工

- U1：`InstallerAsset(release_id, asset_id, tag, version, name, download_url, size, sha256)`；
  `UpdateSnapshot.installer_asset` 默认 None；`parse_installer_asset(payload, release)` 严格绑定同一响应。
  `VerifiedInstaller(path, asset)`、`DownloadWriter(asset, cache_root=None)` 的 write/finish/cancel 负责缓存。
  `verify_download(path, asset)` 和 `validate_installer_asset(asset)` 供下载与交接共同使用。
- U2：`QtInstallerUpdate` 的 changed/snapshot、set_release(snapshot)、start(asset)、cancel()、
  prepare_shutdown()、wait(timeout)、is_running()；worker 自己拥有网络与文件，主线程只转发意图。
- U3：`InstallerHandoff` 的 prepare(verified) 在后台完成复制与 READY；abort() 撤销；
  mark_shutdown_success(bool) 只记录关闭报告；commit() 只由根入口在清理与安装锁释放后调用。
  主窗口可选注入 handoff，缺省保持旧行为；独立 helper 为 stdlib onefile，不纳入全局进程停止表。
- 根任务负责交接、构建与集成；子任务分别负责服务、网络、界面/关闭，文件归属互不交叉。
- 验证先各自直接测试，再合并更新、关闭、入口、收集契约测试；原生与冻结探针独立记录。
- 当前正式资产无 setup，U4 的真实正式包升级不伪造通过；可执行范围完成后独立审阅。

## Global Constraints

- 首期限定 Windows x64 安装版；源码、ZIP、macOS/Linux 保留现有浏览器下载入口，不自动转换分发方式。
- 用户显式开始下载、显式确认退出安装；不开机自动更新，不后台静默覆盖，不增加生产 AppId 切换。
- 保持固定 AppId、稳定 `ADBLab.exe` 和现有用户数据 schema；下载缓存位于用户数据区的独立子目录。
- 不新增强杀操作，沿用本实例关闭流程；如发生强制停止也不授权安装，其他实例仍由维护锁拒绝。
- 下载完成不等于可信，PE 校验不等于安装成功；不得执行只通过 MZ、文件名或用户可改字段检查的文件。
- 当前 setup 尚未配置发布者签名；不能把编译器 Authenticode 校验当作应用安装器认证。
- 不新增生产依赖，不正式发布，不增加签名服务或修改系统配置；必要构建收集沿用既有双产物流程。
- 实施时重新检查当前代码、局部规则和工作树，不沿用本文件中的历史测试数量或版本。

## Review Focus

1. 资产替换或同名错误版本：资产必须绑定同一正式 Release、平台、版本和可信摘要，失败不能执行。
2. 下载完成后到执行之间文件被替换、链接或重解析点变化：交接端重新验证身份、摘要和实际普通文件。
3. 用户取消关闭、任务停止超时、设置落盘失败或仍有其他实例：保持可恢复状态，不假装已退出或升级完成。
4. 安装器未启动、用户取消、部分覆盖或卸载后期失败：区分交接结果和 ready 安装结果，不承诺回滚。
5. ZIP 与安装版共用用户数据：仅安装身份有效的实例拥有安装交接入口，缓存清理不得触碰导出与用户文件。

## 开工前设计门槛

以下三项已在本轮设计确定，沿用用户直接实施授权，不重复请求确认：

- **可信性**：确认固定项目发布源的元数据能提供资产大小和 SHA256，并确定允许的下载跳转域、
  协议与次数。摘要从同一受信发布源取得仅提供该信任模型下的完整性，不等于发布者代码签名；
  若要求发布者认证，先落实签名或带可验证签名的清单及密钥分发，不能在应用里留关闭校验的开关。
- **交互**：下载期间允许继续工作；验证完成后明确列出需要关闭的本实例任务，用户确认才请求关闭。
  安装器继续显示交互向导并承担是否安装；“已启动安装器”和“安装成功”使用不同状态。
- **交接**：独立 helper 使用明确自有进程身份和有界等待；保留重试所需的已验证文件。
  它只启动安装器，不替应用结束其他进程，不以进程名或可复用 PID 判断关闭完成。

## 文件职责与候选接口

以下为本轮实际落实的职责，未新增顶层目录：

| 路径 | 后续职责 |
| --- | --- |
| `services/app_update.py` | 保留现有 ReleaseInfo 和浏览器契约，增加独立安装资产描述及解析函数 |
| `services/installer_update.py` | 无 Qt 的下载校验结果、交接准入与恢复状态，不执行 UI 或覆盖载荷 |
| `gui/adapters/installer_update.py` | Qt 异步下载、取消、超时、进度和关闭时释放网络资源 |
| `gui/features/about.py` | 安装版专属显式动作及状态呈现，继续使用现有按钮/焦点与无障碍体系 |
| `gui/main_frame.py` 及现有关闭 owner | 复用关闭屏障；仅成功释放全部自有资源后完成交接 |
| `scripts/installer_update_handoff.py` | 独立交接协议及有界等待；冻结 helper 的收集方式在设计阶段确定 |
| `tests/test_app_update.py`、`tests/test_qt_app_update.py` 与新增直接测试 | 保留当前手动检查契约，覆盖资产、下载、取消、关闭和交接失败 |

已实现纯逻辑接口：`parse_installer_asset(payload: object, release: ReleaseInfo) -> InstallerAsset`；
`verify_download(path: Path, asset: InstallerAsset) -> VerifiedInstaller`。后者必须在全部验证成功后
才创建不可变结果；路径字符串本身不能充当“已验证”标志。交接消息按本轮设计绑定私有管道与父进程身份，
不使用不受约束的命令行拼接或用户可写的裸标记文件授予执行权。

## Task U1：正式发布安装资产契约

- [x] 用错平台、错版本、草稿/预发布、重复同名资产、错误大小/摘要、非法链接和过期结果写失败测试。
- [x] 运行 `python -m pytest -q tests/test_app_update.py`，确认新增断言因契约未实现失败。
- [x] 增加独立资产类型和严格解析，保留 `ReleaseInfo` 已有使用方及手动浏览器行为。
- [x] 实施批准的可信元数据来源；若需改变发布工作流，先取得该项授权并增加相应 CI 契约测试。
- [x] 运行直接测试与现有 Qt 更新测试；验收错误/历史结果不能授予下载或执行能力。

## Task U2：有界异步下载与缓存校验

- [x] 先测断网、TLS、重定向越界、响应大小超限、超时、磁盘不足、取消、重复点击、窗口关闭和晚到回调。
- [x] 为新增 adapter 和纯校验器建立直接测试，先观察失败，再实现分块写入专属临时文件、摘要/大小
  校验和原子发布；禁止把未验证文件显示为可安装，不自动执行缓存内同名文件。
- [x] 执行前重新核对路径、非重解析普通文件、版本、摘要及批准的签名规则；测试校验后文件替换。
- [x] 仅清理自己创建并验证归属的下载临时资源；取消保留旧的有效缓存，不清用户导出目录。
- [x] 运行 adapter 的离屏 Qt 测试，检查进度、忙碌、失败、重试、焦点和无障碍状态。

## Task U3：关闭屏障与独立交接

- [x] 用取消退出、采集未停止、设置未落盘、helper 启动失败、父进程未退出及 PID 重用写失败测试。
- [x] 接入现有应用关闭 owner；全部资源确认释放前不授予运行安装器的权限；关闭前失败可重试，
  不可逆关闭之后失败保留缓存，下次启动重新检查和验证。
- [x] 实现批准的独立 helper 部署、握手和有界等待；helper 再验下载文件，成功启动交互 setup 后
  只记录“已交接”，不记录“升级完成”，不持有应用安装运行锁阻塞安装器。
- [x] 其他实例与独立工具仍运行时让安装器按现有预检失败；不通过 taskkill 或忽略共享错误绕过。
- [x] 运行关闭、ProcessRunner、冻结 helper 和更新关联测试；触及收集入口时跑源码与实际产物
  packaging/frozen 检查，跨进程测试不能仅用替身替代原生行为。

## Task U4：一次性环境升级验收与文档

- [ ] 在一次性 Windows 环境使用真实前后版本安装包验证下载→校验→关闭→交接→升级→再启动；
  另测取消安装、占用拒绝、降级拒绝、中断后原包修复和损坏身份恢复，不修改生产版本造假。
- [ ] 检查安装后版本、ready 身份、冻结三探针、系统集成和用户数据/额外文件哨兵；安装进程退出
  0 或启动新进程均不单独作为成功证据。
- [ ] 单独验证普通用户、中文/空格路径、多实例、设备任务与真实冻结 helper；环境不足明确记未完成。
- [x] 在实现和验证结束后更新 BUSINESS_FLOW、BUILD_AND_RUN 与风险账本，独立审阅下载来源、
  TOCTOU、关闭授权和精确清理；按测试指南决定集成范围，不把本计划当作已完成记录。

## 保留的替代流程

所有分发方式继续支持[浏览器下载与手动安装器覆盖](../../guides/BUILD_AND_RUN.md#windows-安装升级与恢复边界)。
本期双产物的实现和验证记录仍由[原实施计划](2026-10-24-windows-installer.md)维护。

## 本轮验收记录

- 服务、Qt 下载、界面及关闭、独立 helper、构建收集按职责并行实现；没有修改版本、AppId、
  生产依赖或用户数据 schema。新增 17 条界面文案已补简中、繁中、英文及内嵌资源。
- 独立审阅确认并复现两处 P2：取消清理检查后按路径删除的竞态，以及校验后按路径发布/覆盖
  目标的竞态。修复为 `utils/installer_cache_file.py` 的 Windows 对象句柄协议：在同一句柄内
  校验、禁止覆盖重命名或删除，关闭后才发布 ready；复审及独立原生直接集 29 项通过。
  非 Windows 仅保留纯校验，拒绝原生发布且不按路径删除 part；界面仍采用浏览器流程。
- 本地 PyInstaller onedir 实际构建通过，产物位于
  `build/installer-update-acceptance/dist/ADBLab`；源码 packaging、冻结 packaging 和离屏 GUI
  探针均退出 0，冻结 packaging 包含新增 helper 资源与运行检查。
- 最新 `scripts/check_installer_update_handoff.py` 在修复后重新构建真实冻结父进程和无安装行为的
  哨兵载荷：正常授权、未授权、父进程异常退出、载荷损坏四场景全部通过。父进程存活期间
  不启动载荷；helper 存活时模拟安装目录可重命名；中文和空格路径通过。
  这不是正式安装器升级证据，fixture 的 99.0.0 不改变或冒充产品版本。
- Windows CI 已接入相同冻结交接探针，工作流契约测试通过；本轮未提交、推送或触发远端 CI。
- 首次冻结探针因脚本传入相对路径失败，改为绝对路径并保留诊断后重跑通过；原失败不计成功。
- U4 保持未完成：当前官方 v3.3.2 只有 ZIP，没有真实前后正式 setup 版本对；也未重复本机真实
  安装、系统账户、注册表或设备操作。待正式资产发布后在一次性标准账户完成真实在线升级验收。

最终集成选择更新、缓存、交接、窗口关闭、设置落盘、启动、构建、翻译、字号和 CI 契约共
20 个测试文件，**705 passed，1477 个第三方弃用警告，146.57 秒，退出 0**。这是本轮关联集，
不是全仓全量。此前直接失败回归及独立复审测试另行执行，不重复叠加计数。

修改 Python 文件 Ruff、生产注释检查、源码文本完整性、文档链接/frontmatter 与
`git diff --check` 通过。默认 Pyright 不能解析当前 `.venv` 继承的系统 site-packages；使用
临时配置补充真实解释器路径，所有修改生产路径 **0 errors / 0 warnings**，未改仓库类型规则。
详细本地日志位于忽略目录 `.superpowers/sdd/2026-10-24-windows-installer-update/`。
