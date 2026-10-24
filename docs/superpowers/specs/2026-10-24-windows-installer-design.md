# Windows 安装版与免安装版并行交付设计

日期：2026-10-24。状态：设计已批准，当前工作树已有实现；真实安装生命周期与远程 CI 尚待验收。
实际执行证据统一见[实施计划的验收记录](../plans/2026-10-24-windows-installer.md#验收记录)。

## 目标与授权边界

用户已选定 PyInstaller onedir + Inno Setup，并要求同时保留安装 EXE 和现有免安装 ZIP，
先明确安装、升级、卸载及数据兼容设计和实施计划，再推进改造。

本方案沿用 Python 3.11、PySide6、现有资源清单和 Windows x64 产物，不改变设备功能、
配置 schema、历史记录、结果库格式、应用多实例行为或手动检查更新的交互。
不新增顶层目录；安装器相关源码放在 `scripts/windows_installer/`。

本期实施范围包括关联运行时修复、安装器、构建与发布校验、
测试和文档；不包含正式发布、推送代码、购买签名证书、配置外部账号或修改全局软件环境。
构建用 Inno 编译器采用官方便携部署，放入被忽略的任务构建目录，不安装到系统目录。

## 实施前基线

以下是方案形成时的原始行为，供说明改造原因；当前入口与操作规则以
[构建指南](../../guides/BUILD_AND_RUN.md#windows-安装版与免安装版)为准。

- 本地 `ADBLab.spec` 生成固定 `ADBLab.exe` 的 onedir；CI 使用 `scripts/build_app.py`，
  主 EXE 名为 `ADBLab-win-x64-vX.Y.Z.exe`，不能只修改根 spec。
- `scripts/packaging_manifest.py` 是 spec/CLI 共享资源来源；安装版完整保留 `_internal`。
- `utils/user_data.py` 把 Windows 数据放到 `%LOCALAPPDATA%\ADBLab`；默认导出目录为
  `~/ADBLab`。资源由 `utils/resource_path.py` 基于 `_MEIPASS` 解析。
- `utils/adb_resolver.py::client_executable` 会在 ADB 同目录生成 `adblab-adb.exe`。
  onedir 直接使用安装目录里的工具；退出主窗口不保证独立 ADB server 已退出。
- `services/mobileperf_runner.py` 对空结果路径回退到资源目录 `results`；相对路径随 worker
  的资源目录 cwd 解析。GUI 默认绝对路径安全，但清空或手工输入相对路径仍可触发该边界。
- 当前更新只打开正式 Release 页面，不解析下载 assets，不自动下载或替换文件。
- Release 校验精确要求四份版本归档；新增 EXE 必须同步修改上传路径、校验和测试。

## 方案取舍

| 方案 | 影响与裁定 |
| --- | --- |
| 保留 onedir，加 Inno 安装 EXE，同时保留原 ZIP | 用户选定。复用已验证载荷，新增安装/卸载管理，保留原下载契约 |
| 用安装 EXE 替换 Windows ZIP | 不采用。丢失免安装选项，超出已确定的兼容边界 |
| 改成 onefile 再套安装器 | 不采用。引入解包和工具缓存差异，没有安装需求上的必要性 |
| 每版独立目录 + 固定原生启动器 | 不纳入首期。适合更强的切换/回滚要求，但增加启动器、旧版本资源管理和恢复协议 |

首期采用固定目录、维护锁和文件预检；不承诺事务式升级或断电自动回滚。
安装器是一种分发和管理方式，不意味着减少 Qt/Python 依赖的安装体积。

## 安装行为

| 项目 | 设计值 |
| --- | --- |
| 产品身份 | 固定 AppId `{1C0CD5FE-33F4-4BB0-964D-F2EC6A79F062}`，不含版本 |
| 安装权限 | 当前用户，`PrivilegesRequired=lowest`；不提供全用户安装切换 |
| 默认程序目录 | `{localappdata}\Programs\ADBLab` |
| 主入口 | `{app}\ADBLab.exe`，保持 PyInstaller onedir 内部布局 |
| 安装器文件名 | `ADBLab-win-x64-vX.Y.Z-setup.exe` |
| 免安装文件名 | 原 `ADBLab-win-x64-vX.Y.Z.zip`，内部文件名和结构保持 |
| 快捷方式 | 当前用户开始菜单；桌面快捷方式可选，默认不勾选 |
| 安装结束 | 可选启动应用，仅交互模式显示；静默模式不自动启动 |
| 系统集成 | 当前用户卸载项，不修改 PATH、文件关联、开机启动或系统服务 |
| 版本来源 | 只读取 `utils.app_metadata.APP_VERSION` / `APP_RELEASE_TAG`，不新增手填版本 |

允许选择新的可写目录，但拒绝系统/盘符根、用户数据根、导出默认根、其危险祖先，以及
包含重解析点的目标路径。新目录必须为空；非空目录只接受本产品有效安装身份，不能直接
覆盖现有 ZIP 解压目录或任意同名文件夹。复用已安装目录时核对注册项与磁盘身份一致。
首次安装不扫描、不移动、不删除旧便携目录。

安装器构建在隔离 staging 中复制 onedir，不修改 ZIP 输入。将主 EXE 映射为 `ADBLab.exe`，
并在随包 ADB 同目录预置逐字节一致的 `adblab-adb.exe`，纳入安装文件清单。
由此避免安装版首次运行生成未受卸载管理的副本；外部自定义 ADB 的现有回退策略不变。

## 安装身份、维护锁与运行准入

安装目录使用以下明确归属的控制文件；前四项为常规协议，第五项仅用于提交中断恢复：

- `.adblab-install.ini`：格式版本 1、AppId、主入口名、`State`、`CompletedVersion` 与
  `PendingVersion`、`ManifestSha256` 与 `PendingManifestSha256`；版本均为三段数字，
  状态只允许 `installing`、`ready`、`removing`。
  首次安装的 CompletedVersion 为空；这是安装状态，不是用户配置。
- `.adblab-files.txt`：本版受管理载荷的相对路径及 SHA256；UTF-8 BOM，每行
  `64 位小写 SHA256<TAB>相对路径`，由构建脚本生成，路径统一使用 `/`。
- `.adblab-maintenance.lock`：稳定文件对象，只由安装器代码创建和最后清理，不进入普通
  覆盖或 `[UninstallDelete]` 清单。
- `.adblab-pending-files.txt`：格式同载荷清单，仅在进行中的安装/升级保留目标清单，供
  失败重试时核对已写入文件；不能用不完整的旧清单清理新载荷。
- `.adblab-files.txt.previous`：替换当前清单之前保存的旧完成清单，不是用户数据备份或
  任意历史版本清单。升级先原子写入 previous，再发布目标 current，最后发布 ready；
  因而在 current 已变为 pending 但 ready 身份尚未提交的窗口，旧完成归属仍可验证。
  installing/removing 状态下，只在 current 摘要等于 PendingManifestSha256 且 previous
  摘要等于旧 ManifestSha256 时，才从 previous 读取旧完成集合；冲突或缺失按损坏处理。
  首次安装没有旧完成清单，不生成 previous；ready 提交后可留下待清理的普通 previous，
  不据其内容改变当前完成归属，后续持独占锁维护时清理。不得放入 payload 或普通卸载日志。

Python 新增 `core/windows_installation.py`，在 Windows 冻结入口、业务初始化之前处理：

1. `sys.executable` 同目录五个安装控制文件全部不存在：沿用现有免安装行为，其他平台和
   源码同样不变；任一个存在即视为受管目录，残缺标识不能回退为免安装模式。
2. 标识存在：验证身份、格式和入口，再以 `OPEN_EXISTING + GENERIC_READ + FILE_SHARE_READ`
   打开 lock；取得锁后重新读取身份，只有 `ready`、PendingVersion 为空且当前清单摘要匹配
   才进入业务。ready 后可能尚未删去的 pending 文件仅在与当前清单完全一致时视为清理残留，
   不当作进行中的安装；其他冲突视为损坏。
   持有句柄直到入口返回；多个实例共享读，不变成单实例应用。
3. 标识损坏、lock 缺失、共享冲突或权限拒绝：阻止业务初始化并返回非零。
   GUI 区分“正在维护，请稍后重试”“安装尚未完成，请重新运行安装程序修复”和
   “安装信息损坏，请保留原目录后重新安装”；CLI/worker 写标准错误，不显示阻塞消息框。
   维护准入失败返回专用退出码 73；原有正常 CLI 退出码不变，不暴露实际安装路径。
4. GUI、启动画面、native launcher、MobilePerf worker、自检均经过同一入口保护，异常和
   正常退出均关闭自己的句柄，不由其他进程代为释放。

安装/升级在 `PrepareToInstall`、卸载在 `InitializeUninstall` 获取同文件的读写、零共享
独占句柄，持有到维护结束。已有安装缺 lock 时失败，不在原文件可能仍被持有时删除重建。
首次仅在确认空的新目录内创建。lock 不允许替换，以免新旧进程锁住不同文件对象。
首次创建 lock 并获得独占句柄后，必须先发布 `installing` 身份和 pending 清单，再复制任何
可执行载荷。完整预检通过后的升级同样先记录 installing；中断后该状态继续阻止业务启动。

独占句柄取得后，检查受管理的现有文件、待覆盖文件和精确待删除文件是否可写、是否占用；
检查失败在 payload 变更前退出。`CloseApplications=no`、`RestartApplications=no`，
不调用 `taskkill adb.exe`、`kill-server` 或自动关闭共享 ADB/scrcpy。

此锁阻止进入业务初始化，不能阻止 PyInstaller bootloader 更早装载 EXE/DLL；独立工具
也不持有该锁。文件预检具有检查与使用之间的竞争窗口，因此复制/删除期间的锁冲突仍须
真实报错，不能忽略错误、安排未确认的重启替换或报告成功。安装失败的修复受下述原版本、
原清单和状态约束，不能把所有维护失败都视为可直接重跑。

## 升级、修复与失败语义

1. 下载新安装器后，用户手动运行；更新服务不改为自动安装。
2. 使用稳定 AppId 读取既有安装位置，核对身份和数值版本。更高版本升级；相同版本允许
   修复；较低版本拒绝。`installing` 中断时只接受 PendingVersion 相同且目标清单 SHA256
   与 PendingManifestSha256、磁盘 pending 清单完全一致的原安装器，先修复为 ready 再升级。
   不能只比较版本号，不能用下一版替换 pending 而丢失前一次部分写入文件的归属。
   `removing` 中断不直接改为升级/修复；仅当旧卸载器与日志仍完整时可尝试继续卸载，
   卸载完成后再安装。Inno 已删除卸载日志时转人工保留目录恢复，不承诺旧卸载器可重跑。
3. 获取维护锁并完成权限、占用、清单与路径检查；应用仍运行、ADB 占用或权限不满足时，
   提示先关闭相关程序再重试，返回失败；预检失败不修改已有 payload 和用户数据。
4. 替换本版载荷。旧清单中本版不再包含的文件，仅在路径属于安装根、无重解析点且当前
   SHA256 与旧清单一致时删除；未知文件不删除，待删文件被改动则预检失败并明确提示。
5. 清单拒绝绝对路径、盘符/UNC、`..`、ADS、大小写冲突、保留控制文件和越界目标。
   禁止递归清空 `{app}` 或 `_internal`。清理目录只使用空目录删除。
6. 所有载荷步骤成功并按目标摘要复核后，先将旧完成清单发布为 previous 提交日志，再发布
   新的受管理清单，原子发布 `ready` 身份、
   新 CompletedVersion/ManifestSha256 并清空 pending 字段，最后删除与当前清单一致的
   pending 文件和 previous。提交前失败保持 installing，原 pending 清单不先删除；提交后清理中断
   允许下次持独占锁核实并清理同内容残留。状态文件用同目录临时文件写入后替换，不能原地
   截断写入；身份与 pending 清单矛盾或缺失时走损坏信息的人工恢复规则。
7. 进程取消、磁盘满、复制/删除失败均不得落成“升级成功”。首版不承诺操作开始后的完整
   回滚；残留 installing 只开放原安装器修复或卸载，removing 仅开放条件允许的卸载恢复，
   均不进入业务。卸载器及其日志已缺失时走人工保留目录恢复，不能通过修改状态恢复业务。
   重试使用旧清单与 pending 清单的受管集合核对占用和过期文件，不把未登记文件视为可删除对象。
8. 安装成功后的可选启动必须先释放维护锁；异常/取消由 DeinitializeSetup 兜底释放。
   不自动启动尚未 ready 的程序。

身份、旧清单或 lock 缺失/损坏无法证明归属时，禁止自动接管和重建。该情形不承诺“一键
修复”：先关闭程序，用户明确保留/改名旧安装目录，再在原位置的空目录重新安装；注册信息
只在新安装成功后更新。恢复只支持在原登记位置建立新的空目录，不自动接管不同目录的
同 AppId 安装。旧卸载器在 InitializeUninstall 核对自身原始安装目录、当前注册位置和磁盘
身份；路径不一致或元数据不完整就拒绝，防止被移走的旧卸载器删除新安装注册项。
应用数据位于外部，不随这一步删除。安装器不自行移动旧目录。

Inno 本身的卸载日志与本项目载荷清单职责不同：载荷 `[Files]` 统一使用
`uninsneveruninstall`，由本项目清单管理精确卸载；Inno 管理快捷方式、卸载注册项和自身文件。
原因是其默认追加日志会记住已退役文件的旧路径，若用户后来在该路径放入新文件，普通卸载
仍会按历史路径删除。不能只依靠 AppId 就假定旧文件已清理或未知文件必然保留。

## 卸载与数据兼容

- 卸载同样先取得维护锁并检查占用；失败就保持安装，不强杀程序或 ADB。通过全部预检后、
  正式删除前写入 removing；删除中断后不能把剩余程序当作完整安装启动。
- 在 `usUninstall` 依据当前完成清单与合法 pending 清单精确删除载荷，只有摘要匹配的文件
  可删，已缺失文件视为该项完成；文件被改动、越界、无法判定或删除失败立即 Abort。
  不允许忽略文件错误继续清理身份。Inno 再清理快捷方式和卸载注册项；不提供清个人数据选项。
- `%LOCALAPPDATA%\ADBLab`、`~/ADBLab`、自定义导出目录、设备数据及旧 ZIP 目录一律保留。
- lock/身份/清单不交给普通删除清单。`usPostUninstall` 仅是检查时机，必须实际核对清单
  内所有载荷、登记的快捷方式和本产品卸载项均已消失，才关锁并精确删除存在的控制文件、
  尝试删除空目录；取消/异常/残留只释放锁，保留 removing 状态及清单，不报告完成。
  Inno 的该回调可能在删除不完整时触发，退出码 0 也不构成证据；自动验收必须检查后置状态。
  Inno 在后期脚本失败前可能已删除卸载 `.dat` 或通知第一阶段成功，原卸载器未必还能启动；
  即使脚本显式终止后续阶段也不能据此承诺可重试。此类失败保留现有目录供人工恢复，
  不自动删除残留、伪造卸载成功或接管未知文件。
  卸载器自删除是异步流程，由验收器有界等待确认，不能在其自身进程内要求自身文件已消失。
- 安装目录里额外放入的非管理文件保留，不能因为根目录未删空而清除它们。
  包括已由前一次升级删除的退役路径后来出现的用户文件；普通卸载日志不得重新删除它。
- 当前版本、同一 Windows 账号的 ZIP/安装版使用同一用户数据位置和 schema，无需复制或
  迁移。并存不代表两个不同版本可以安全同时写入所有设置；沿用当前兼容边界。
- 只存在于老便携目录里的 `resources/app_settings.json` / `connected_devices.yaml`
  不自动扫描导入；保留旧目录，先通过兼容版本正常启动落入用户数据目录，或另行明确导入。
- 指向旧 ZIP 的自定义 ADB 绝对路径原样保留，文件缺失仍按当前规则报错，不静默改为内置；
  用户可在现有设置中选择“自动/内置”或有效路径。

## 性能采集输出目录修复

保持 `MobilePerfRunConfig` 的字段、序列化和公开兼容入口不变，不修改历史配置值。
在 `MobilePerfRunner.start()` 创建本次运行快照时统一解析保存位置：

- 有效绝对路径原样规范化使用；UNC 绝对路径继续支持。
- 空值使用 `~/ADBLab/mobileperf`；相对路径以 `~/ADBLab` 为基准，解析成绝对路径。
- Windows 盘符相对路径（如 `C:results`）及不完整根路径拒绝，不依赖进程隐含盘符 cwd。
- 不修改调用方配置对象；规范化后的副本同时用于临时配置、结果预测、基线、归档和回调，
  不能让实际输出与界面寻找结果使用不同目录。
- 非法路径、位于安装资源内部的目标或创建/写入失败，在启动 worker 前明确失败。
  不静默回退到安装目录，也不移动既有结果文件。

这是对原先依赖工作目录的未明确行为的收敛。正常 GUI 默认目录、自定义绝对路径、数据格式
保持；文档必须说明空值/相对路径的新解析规则，测试覆盖源码、冻结和切换 cwd。

## 构建、双产物与验证边界

新 `scripts/build_windows_installer.py` 消费已自检的 onedir，执行校验、staging、清单生成和
ISCC；不重新打主应用，不直接修改 ZIP 来源。`--dry-run` 只输出计划，不下载、不写入。
编译器路径可显式传入；默认查已准备的固定版本，不隐式使用任意系统版本。

固定 Inno Setup 6.7.3 官方资产，便携部署至 `build/tools/inno-6.7.3` 或 runner 临时目录：

- URL：`https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe`
- SHA256：`9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732`
- 下载后验证固定摘要及 Windows Authenticode，再使用官方 `/PORTABLE=1 /CURRENTUSER`
  `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...`；失败不执行下载文件。
- 实施时再次核对资产与固定标签源码。无网络/验签失败则报环境阻断，不降低校验或安装 latest。

Windows CI 顺序：现有测试/onedir 构建 → 现有冻结三项探针 → 安装器构建 → 安装验收 →
原 ZIP 压缩 → 精确上传 ZIP 与 setup。生成安装器必须早于现有删除 onedir 目录的步骤。
macOS/Linux 构建与归档不变。Release 校验改为恰好五份预期版本产物，保留四份归档的
完整校验；setup 增加非空普通 PE 文件检查及构建阶段真实安装验收，不能把 `MZ` 当作安装成功。

真实安装/卸载测试只在一次性 Windows runner/干净 VM 中执行，检查本产品 AppId 尚不存在。
本机默认只编译和运行纯逻辑/隔离进程测试，不覆盖真实安装、注册表和开始菜单。
仅改 `LOCALAPPDATA` 环境变量不能隔离 Inno 使用的 HKCU 和 Windows known folders。
生产 AppId 的安装验收与 ADBLab 自检数据隔离分别处理；不加入能改变发布产品身份的隐藏参数。

真实验收至少覆盖首次安装、相同版本修复、较高版本升级、拒绝降级、多实例/子进程占用、
独立工具文件占用、安装中启动竞争、卸载保留数据、未知文件保留、重装、路径含中文/空格、
非管理员账号、损坏标识、不可写路径和安装后冻结三项探针。
同版本重装不等于跨版本升级；跨版本测试使用独立测试 fixture 版本序列并另做真实应用前后版
验收，不能修改或发布虚假的生产版本来充数。

本轮不新增 Python 运行依赖，不修改应用版本。Windows 代码签名可后续单独接入；未配置签名
时如实说明，不能声称安装器已有发布者认证或保证没有系统信誉提示。

## 官方参考

- [Inno Setup 功能](https://jrsoftware.org/isinfo.php)
- [当前用户安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
- [AppId 与卸载身份](https://jrsoftware.org/ishelp/topic_setup_appid.htm)
- [CloseApplications 的自动关闭语义](https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm)
- [安装事件](https://jrsoftware.org/ishelp/topic_scriptevents.htm)
- [卸载事件示例](https://github.com/jrsoftware/issrc/blob/is-6_7_3/Examples/UninstallCodeExample1.iss)
- [卸载日志追加规则](https://jrsoftware.org/ishelp/topic_setup_uninstalllogmode.htm)
- [固定版本卸载实现](https://github.com/jrsoftware/issrc/blob/is-6_7_3/Projects/Src/Setup.Uninstall.pas)
- [Windows 文件共享与句柄规则](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [编译器官方便携部署实现](https://github.com/jrsoftware/issrc/blob/is-6_7_3/isportable.iss)
- [固定版本编译器安装脚本](https://github.com/jrsoftware/issrc/blob/is-6_7_3/setup.iss)

实施顺序与验收记录见[实施计划](../plans/2026-10-24-windows-installer.md)。
