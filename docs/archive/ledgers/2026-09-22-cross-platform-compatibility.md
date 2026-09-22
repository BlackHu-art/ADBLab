# 多系统兼容性修复实施方案

> **For agentic workers:** 执行时使用 superpowers:subagent-driven-development 或 superpowers:executing-plans，按任务记录复现、改动和验证结果。本文保留实施约定，执行状态和剩余验收见末尾记录。

**Goal:** 修复已确认的 macOS 工具发现、Linux 原生工具环境、Windows 性能日志与设备路径问题，并使发布架构和 GUI 验收覆盖真实平台差异。

**Architecture:** 扩展现有工具候选和进程边界，继续使用 ADB 客户端探测、QtAdbRuntime、CommandRunner/ProcessRunner 和 MobilePerfRunner。平台发现只负责候选路径；版本检查、能力探测和生命周期继续由现有组件负责。

**Tech Stack:** Python 3.11、PySide6、PyInstaller、pytest；实现使用现有依赖及 Python 标准库。

**Spec:** 本会话“继续检查代码对多系统的兼容性”的审查结果，以及“结合代码出一下处理方案”的要求；以下处理约定构成本方案的设计依据。

## 全局约束

- 本轮设计覆盖 Windows、Ubuntu/Linux 与 macOS；Windows/Linux x86_64 继续使用现有 scrcpy 4.1 工具包。macOS 继续使用系统安装工具。
- 保留已有 ADB 手动选择语义：指定客户端缺失时报告不可用，不静默换用另一个客户端。
- 保留“Windows / Ubuntu / macOS 下自动选择”的显示逻辑；显示名称不参与执行后端选择。
- 保留 adb_client 配置键和格式，不新增持久化 scrcpy 设置，不改变设置 schema。
- 不增加生产依赖、不更改应用版本、不运行时下载工具、不重新引入 scrcpy-win64。
- 候选发现不启动 ADB；版本探测在现有后台任务中执行。设备连接测试仅对授权设备进行。
- 按 [测试指南](../../guides/TESTING_GUIDE.md) 增量验证；既有 155 passed / 16 skipped 是审查基线，不代表本方案实施后通过。
- 本机安装系统软件、完整打包及 CI 改动按 [项目规则](../../../AGENTS.md) 的授权边界执行。不得将当前 workflow_dispatch 当作普通验收：其成功后会进入自动 Release。
- 不提交、推送或发布；若后续另有明确授权，按授权范围处理。

## 方案取舍

采用六个可以单独验收的局部任务。macOS 首轮解决标准安装目录发现，并用 SCRCPY_PATH 支持特殊部署；新增图形化 scrcpy 设置卡另作需求。Windows 继续复用同一程序的 MobilePerf worker，在入口恢复输出管道；无需维护第二个采集程序。macOS 建议提供 Intel 与 Apple Silicon 两种原生产物，避免将单一架构误标为 x64。

## 评审重点

1. Finder 的受限 PATH、工具安装/移除后重检：保持既有选择优先级，清缓存后能够发现新工具。
2. 用户显式选择无效路径：显示真实失败，不误用其他 ADB/scrcpy。
3. Linux 随包库与原生工具库不兼容：只清理目标子进程环境，MobilePerf worker 保持冻结运行环境。
4. Windows 无控制台、中文/emoji、管道 EOF：输出完整，句柄所有权明确，不因新增副本遗留 reader。
5. Intel/ARM64 和 X11 插件：产物架构与名称一致，GUI 初始化确实执行，不以 import 或资源检查代替。

## 任务 1：补充 macOS 工具发现并衔接现有 ADB 自检

**修改位置：**
- utils/adb_resolver.py：CLIENT_SOURCE_TOKENS、SDK_SOURCE_TOKENS、_candidates()。
- utils/tool_manifest.py：增加纯路径函数 macos_tool_candidates(tool: str, machine: str | None = None) -> list[tuple[str, str]]，仅生成有序 Homebrew 路径，不检查版本或启动进程。
- services/remote/scrcpy_service.py：ScrcpyService.resolve_executable()。
- gui/widgets/adb_client_card.py：来源显示标签和自动选择说明。
- gui/panels/remote_panel_scrcpy.py：无效 SCRCPY_PATH 的可操作提示。
- 三语言 TS/QM 与生成翻译资源：沿用现有生成流程。

**ADB 自动选择顺序：**

当前平台内置 → ADB_PATH → ANDROID_HOME → ANDROID_SDK_ROOT → Windows LOCALAPPDATA SDK → 当前 PATH → macOS 默认 SDK → macOS Homebrew。

新增项放在原 PATH 后，避免改变已经正常工作的环境。macOS 默认 SDK 为 ~/Library/Android/sdk/platform-tools/adb；Homebrew 为 /opt/homebrew/bin/adb 与 /usr/local/bin/adb，当前架构的标准前缀优先。

- 新来源使用 sdk_macos、homebrew_arm64、homebrew_x64；UI 按 source 索引，两个 Homebrew 路径不能共用一个 source。
- sdk_macos 加入 SDK_SOURCE_TOKENS，沿用 SDK 只供自动解析的策略；存在的 Homebrew 工具进入原候选版本探测，未安装位置不新增空行。
- CLIENT_SOURCE_TOKENS 已被 core/settings_manager.py 复用，新来源可正常往返保存，未知来源仍按原规则处理。
- POSIX 可执行权限检查、版本失败分类、失败不缓存继续沿用。

**scrcpy 路径顺序：**

非空 SCRCPY_PATH 是显式覆盖：按文件路径展开 ~ 并转为绝对路径，不作为命令字符串拆分；无效时报告失败，不 fallback。未配置时保持原内置/PATH策略，最后追加 macOS Homebrew 兜底。Windows 内置资源缺失的既有失败策略保留。resolve_executable() 保持返回路径的接口，避免向 UI 当前未捕获的位置新增异常；版本与执行能力仍由后台预检处理。

**与既有自检的连接：**

- SettingsPage._apply_adb_client() 继续负责选择注入、配置保存、探测缓存和两层路径缓存清理、执行环境重检。
- _rescan_adb_clients() 继续只刷新客户端候选；QtAdbRuntime.recheck() 继续清除 resolver/program 两层缓存后重新选择后端。
- 不增加全局工具缓存、新探测线程或额外 5037 查询；现有 host_system_name() 只负责界面文案。
- packaging 自检仍只要求随包交付的工具，macOS 外部 ADB/scrcpy 不成为构建机器的必装项。

- [x] 在 test_adb_resolver.py/test_remote_services.py 先补失败用例：Darwin + 受限 PATH、默认 SDK、双 Homebrew 前缀、已有 PATH 优先、缺执行权限、显式无效选择、非 macOS 不增加这些路径。
- [x] 运行这些新增节点，确认失败来自尚未实现的发现逻辑。
- [x] 实现候选与 SCRCPY_PATH；补来源标签和翻译，保留现有工作线程和错误契约。
- [x] 在 test_adb_client_refresh.py/test_qt_adb_runtime.py 验证来源出现/消失、选定来源消失、重新检测后发现新工具、选择事务只触发一次。
- [x] 在 test_settings_persistence.py 验证新来源可保存；在 test_scrcpy_backend.py 验证 scrcpy 仍绑定当前选定的 ADB。

直接/关联命令：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_adb_resolver.py tests/test_adb_clients.py tests/test_adb_client_refresh.py tests/test_qt_adb_runtime.py tests/test_settings_persistence.py tests/test_remote_services.py tests/test_scrcpy_backend.py tests/test_i18n.py
```

## 任务 2：隔离 Linux 原生工具的动态库环境

**修改：** core/native_process.py 的 popen_native()；扩展 tests/test_native_process.py、tests/test_native_execution_boundary.py。

增加独立函数 native_tool_environment(environment: dict[str, str]) -> dict[str, str]，只复制并调整 Linux 库搜索变量。恢复规则：

```python
cleaned = dict(environment)
original = cleaned.get("LD_LIBRARY_PATH_ORIG")
if original is None:
    cleaned.pop("LD_LIBRARY_PATH", None)
else:
    cleaned["LD_LIBRARY_PATH"] = original
```

仅在 Linux + frozen + isolate=True + 非 shell 命令调用此函数，输入为显式 env 或 os.environ 的副本。保留 ADB、ADB_PATH、PyInstaller 元数据和其他环境；不修改传入字典或父进程 os.environ。不要把 _should_isolate() 的 Windows 条件改成 Linux，否则会进入 Win32 launcher。

本任务限定现有 ADB/scrcpy 原生边界；MobilePerf worker 的 isolate=False 继续继承原环境。后续系统终端/文件管理器若需要清理环境，应单独明确它们的启动契约。

- [x] 新增参数化测试，覆盖 ORIG 缺失、空串、非空、显式 env、父环境未改变及 ADB 变量保留。
- [x] 增加反例：源码、非 Linux、isolate=False、shell 模式均保持原环境；确认新增测试在旧实现失败。
- [x] 实现环境副本清理，沿用现有取消、超时与管道排空流程。
- [x] 用临时 libgcc_s.so.1 冲突和同一条 adb version 验证清理后恢复成功；不访问设备。该用例证明隔离边界，不声称当前官方工具包本身损坏。
- [x] 运行两个直接测试文件，并关联 test_adb_clients.py/test_scrcpy_backend.py。

```bash
.venv/bin/python -m pytest -q tests/test_native_process.py tests/test_native_execution_boundary.py tests/test_adb_clients.py tests/test_scrcpy_backend.py
```

## 任务 3：恢复 Windows MobilePerf 管道并统一 UTF-8

**新增：** core/worker_stdio.py、tests/test_worker_stdio.py。
**修改：** main.py::_run_mobileperf_worker()、services/mobileperf_runner.py::start()。
**关联：** mobileperf/common/log.py 的现有日志分流契约，保持 DEBUG、业务日志和脱敏行为。

提供 prepare_worker_stdio() -> None，只在专用 worker 入口调用；必须早于 argparse 和导入 StartUp。源码 -m 路径由父进程强制设置 PYTHONIOENCODING=utf-8；冻结路径通过入口显式恢复标准流，不能只依赖环境变量。

Windows 标准流为 None 时，使用下列所有权链：

GetStdHandle → DuplicateHandle（不可继承副本）→ msvcrt.open_osfhandle（O_BINARY）→ os.fdopen（UTF-8、逐行刷新）。

- 原始标准句柄属于进程，不交给文本流关闭；每个副本仅转移一次所有权。
- open_osfhandle 成功前失败：CloseHandle 副本；成功后包装失败：os.close(fd)；文本流成功后不再直接关闭底层句柄。
- 已存在的文本流支持 reconfigure() 时设置 UTF-8；保留注入的 StringIO，不随意替换已有输出对象。
- 无效管道明确失败，不转写空设备后继续采集。成功安装的流由 worker 进程持有至解释器退出，保证异常和 logging 收尾仍能输出。
- 重复调用幂等；不恢复不需要的 stdin；非 Windows 不调用 Win32 API。
- 可借鉴 core/native_launcher.py 的句柄操作，但不直接复用 _startup_info()：它服务于下一子进程的启动，并采用不同的继承与空设备策略。

- [x] 新增无设备回归：父端强制 UTF-8，即使继承 PYTHONIOENCODING=gbk，中文/emoji 的 on_log 仍完整。
- [x] 新增 Windows pythonw.exe 测试：两个 PIPE、初始化前标准流 None、初始化后中文分别到 stdout/stderr、退出码与 EOF 正常。
- [x] 以替身检查不可继承副本、分阶段失败清理、重复调用和原始句柄不被关闭；先运行并确认旧实现失败。
- [x] 实现 worker 初始化及父进程环境设置，保留现有 logger 的“没有标准流也不崩溃”独立导入契约。
- [ ] Windows 原生补验待完成；Linux 直接/关联测试已执行，Windows 专用节点 skip 不算通过。

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_worker_stdio.py tests/test_model_mobileperf.py tests/test_logging_routing_mobileperf.py tests/test_mobileperf_runner_concurrency.py
```

Windows 产物补验使用 subprocess.run(capture_output=True, timeout=15)：--mobileperf-worker --help 应返回 0 且 stdout 包含 --config；--mobileperf-worker --编码验证 应返回 2 且 stderr 的 UTF-8 解码包含原参数。两项都在解析参数阶段结束，不启动设备采集。

## 任务 4：统一 Android 设备路径语义

**修改：** services/file_explorer.py::device_path()。
**测试：** tests/test_file_explorer_service.py，另在现有预览/操作测试中增加一个假 worker 消费者断言。

设备路径实现改为：

```python
import posixpath

def device_path(*parts: str) -> str:
    """按 Android 的 POSIX 语义拼接设备路径，不解释宿主盘符。"""
    return posixpath.join(*parts)
```

主机本地路径继续使用 os.path，现有 safe_name() 和 shell_quote() 边界保留。

- [x] 先补 ntpath 主机条件下的回归，断言 device_path('/data/local/tmp', 'C:notes.txt') == '/data/local/tmp/C:notes.txt'，并覆盖 D:资料、普通文件名及嵌套目录。
- [x] 确认旧实现会丢失父目录后修改该函数。
- [x] 消费者假 worker 断言预览或重命名收到完整设备路径；本机保存路径构造不变。
- [x] 运行直接测试与新增消费者节点。

```bash
.venv/bin/python -m pytest -q tests/test_file_explorer_service.py
```

## 任务 5：独立验证 Qt GUI 启动及 Linux 系统依赖

**修改：** main.py::_run_self_check()；新增 _self_check_gui()；扩展 tests/test_gui_bootstrap.py。

增加 --self-check gui，保留 packaging 原有含义。GUI 模式只创建 QApplication、小型 QWidget，显示窗口后通过 QTimer 在一次短事件循环后退出；不调用 _run_gui()、不创建 MainFrame、不加载用户设置、不扫描设备。GUI 探针作为独立进程运行，避免与已有 QCoreApplication 混用。

核心形式：

```python
app = QApplication([])
window = QWidget()
window.resize(320, 160)
window.show()
QTimer.singleShot(100, app.quit)
return app.exec()
```

不在代码里强制 offscreen。离屏只用于本地逻辑测试；Linux 的 X11 验收显式设置 QT_QPA_PLATFORM=xcb，在 xvfb-run 中运行，并设置外部 15 秒超时。

- [x] 先补 CLI 分派隔离测试，以及独立子进程 offscreen 成功、无效 QPA 平台非零退出的用例。
- [x] 实现独立 GUI 自检，不改变 packaging、worker、普通 GUI 的启动顺序。
- [x] 在 BUILD_AND_RUN.md 记录 libxcb-cursor0 等 Qt 系统依赖及安装/排障方法。
- [x] 用户已在终端安装 libxcb-cursor0；源码与产物均通过系统库环境下的 xcb 探针，结果见执行记录。Xvfb 是验收工具，不能当作应用运行依赖。

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_gui_bootstrap.py
timeout 15s xvfb-run -a env QT_QPA_PLATFORM=xcb .venv/bin/python main.py --self-check gui
```

Xvfb 不覆盖 Wayland、真实显示器、高 DPI 或完整窗口交互；这些进入平台人工验收。

## 任务 6：使 macOS 发布架构、产物名称及验收对应

**修改：** .github/workflows/Build-exe.yaml、tests/test_ci_contracts.py；同步构建文档。

推荐矩阵：

| Runner | setup-python architecture | Python/产物架构 | 资产名称 |
| --- | --- | --- | --- |
| macos-15-intel | x64 | x86_64 | ADBLab-macos-x64 |
| macos-15 | arm64 | arm64 | ADBLab-macos-arm64 |

Windows/Linux 沿用当前打包模式。两个 macOS job 都用原生 Python 构建主程序与 helper，无需增加跨架构转换或修改现有 ADBLab.spec。

- [x] 先补 CI 契约测试：架构映射、缓存键含 runner.arch、检查在归档前、macOS 产物自检、Linux xcb 冒烟。
- [x] 修改矩阵、Python architecture，pip cache 的 key 与 restore-keys 都包含架构。
- [x] Python 安装后核对 platform.machine()；helper 构建后及主程序压缩前分别用 file 与 lipo -archs 断言与矩阵一致。
- [x] 压缩前执行 macOS .app/Contents/MacOS/<产物名> --self-check packaging；文件名来自现有 matrix.artifact 和版本变量。
- [x] Linux CI 系统依赖增加 libxcb-cursor0，验收工具增加 xvfb/xauth；在源码和最终产物上执行任务 5 的 xcb GUI 探针。
- [x] 运行契约测试及本地 dry-run；修改 CI 后不得为验收触发当前自动 Release。

```bash
.venv/bin/python -m pytest -q tests/test_ci_contracts.py tests/test_build_app.py
.venv/bin/python scripts/build_app.py --dry-run
```

## 执行顺序与集成验收

1. 任务 1、2 可以并行实现；二者完成后联合验证 ADB 客户端探测与 scrcpy 启动计划。
2. 任务 3 与任务 4 独立推进；任务 3 涉及 main.py，完成后再做同文件的任务 5，避免并发编辑冲突。
3. 任务 5 完成后执行任务 6，使工作流只引用已经存在的 CLI 自检目标。
4. 每项先失败回归、再最小实现、再直接/关联测试；主任务统一决定集成范围，不自动跑全量。
5. 同步 BUILD_AND_RUN.md、ADB_FAST.md、DEPENDENCY_MAP.md；纠正“非 Windows 不内置 scrcpy”和“packaging 不执行 adb version”等旧描述，验证后再更新 RISKS_AND_DEBT.md。

静态验收使用修改文件的 Ruff、受影响生产模块的 Pyright、中文注释检查、文档检查和 git diff --check。完整构建经授权后沿用现有 build_app.py/ADBLab.spec，并对新产物执行 packaging 和对应 GUI 探针。

人工验收：Windows 检查打包版性能日志、中文路径、投屏与停止；Ubuntu 分别检查 X11/Wayland 启动、内置工具、自检与投屏；macOS Intel/Apple Silicon 分别从 Finder 打开，验证受限 PATH 下的发现、镜像和关闭。没有相应实机时保留未验收状态。

## 依据

- [GitHub 托管 runner 与架构](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [PyInstaller macOS 架构](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support)
- [PyInstaller 外部进程环境与 Windows 标准流](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
- [Windows CRT 句柄所有权](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)

## 执行记录（2026-09-22）

六项代码修复已实施，未提交、推送或触发发布。Windows/macOS 原生功能仍待对应平台验收。

| 本轮验证范围 | 实际结果 |
| --- | --- |
| macOS 候选、自检衔接、设置、Remote 与翻译关联集 | 394 passed |
| 原生进程、执行边界与文件路径 | 54 passed，15 个 Windows 专用节点 skipped |
| GUI 启动与文件预览 | 42 passed |
| MobilePerf 标准流、日志与并发 | 92 passed，1 个 Windows pythonw 节点 skipped |
| CI 契约与构建入口 | 34 passed |
| 评审追加：改名 scrcpy 原生隔离及进程/快速通道关联集 | 237 passed（包含部分上述已测文件，不能与上表直接累加） |
| 真实 Linux ADB 动态库冲突注入 | 未隔离返回 127；隔离后 ORIG 缺失、空串和非空均返回 0；未访问设备 |
| 源码 packaging 与 offscreen GUI 自检 | 退出码 0 |
| Ruff、中文注释、文档/frontmatter、差异检查 | 已通过 |
| Pyright | 受影响模块通过；原有 core/native_process.py 的 Win32 ctypes 成员需 Windows target 检查，默认 Linux target 存在 5 条既有错误 |

新增回归先确认失败再修复。相关测试还纠正了三处已确认的过时替身/Windows 路径预期，保留业务断言。
本轮影响范围可沿调用链界定，按测试指南未运行全量 pytest。Linux 构建、独立评审与环境探针结果见下表。


独立评审发现并补修了一个 P2：`SCRCPY_PATH` 的任意文件名可能绕过基于 basename 的原生工具
识别。`CommandRunner.run()` 和 `ProcessRunner.start()/spawn()` 增加兼容默认的 `native_tool`
参数，由 scrcpy 短/长进程入口明确声明；该标记仅用于隔离，不禁用 ADB 快速通道。新增回归先
4 failed 后通过，worker 默认保留冻结环境的反例也通过。

### 最终产物验收

已执行 `.venv/bin/python scripts/build_app.py --name ADBLab-linux-x64 --onefile`，最终产物为
`dist/ADBLab-linux-x64`。评审追加修复后重新构建，以下均针对最终产物：

| 检查 | 实际结果 |
| --- | --- |
| `PATH="" ./dist/ADBLab-linux-x64 --self-check packaging` | 退出 0；内置 ADB、scrcpy、server 与桥接工具通过 |
| `QT_QPA_PLATFORM=offscreen ./dist/ADBLab-linux-x64 --self-check gui` | 退出 0 |
| xcb/Xvfb 源码及产物 GUI 探针 | 均退出 0；15 秒限时；安装系统库后再次验证通过，无临时库路径 |
| 产物 `--mobileperf-worker --help` | 退出 0，stdout 包含 `--config` |
| 产物 `--mobileperf-worker --编码验证` | 退出 2，stderr 为 UTF-8 且保留中文参数；父环境指定 GBK |
| 独立评审复查 | 改名 scrcpy 查询/启动均恢复原生库路径，worker 保留冻结库路径；原 P2 已关闭 |

首次验收时本会话的 `sudo` 被 no-new-privileges 限制，未能安装系统包。当时从 Ubuntu 官方 apt 源下载
`libxcb-cursor0 0.1.4-1build1 amd64`，核对 SHA256 与 apt 元数据一致后仅解包到忽略的临时工作区；
xcb 探针通过子进程 `LD_LIBRARY_PATH` 临时加载它。该临时库未加入版本控制或产物。
用户随后完成系统安装，`dpkg-query` 确认 `install ok installed`、版本 `0.1.4-1build1`。
清除子进程的 `LD_LIBRARY_PATH` 与 `LD_LIBRARY_PATH_ORIG` 后，以下两条命令均退出 0、无错误输出，
确认当前系统库支持源码与现有产物启动，无需重新打包：

```bash
env -u LD_LIBRARY_PATH -u LD_LIBRARY_PATH_ORIG QT_QPA_PLATFORM=xcb timeout 15s xvfb-run -a .venv/bin/python main.py --self-check gui
env -u LD_LIBRARY_PATH -u LD_LIBRARY_PATH_ORIG QT_QPA_PLATFORM=xcb timeout 15s xvfb-run -a ./dist/ADBLab-linux-x64 --self-check gui
```

构建时有第三方可选库提示（包括 SciPy `_cdflib`、其他系统的 ctypes 库及当时尚未安装的 xcb 库），
packaging/GUI 检查通过不代表所有第三方功能已经实机覆盖。

Windows/macOS 原生产物、Finder 启动、真实设备投屏及断线、Wayland/高 DPI 尚未验证。
本轮未连接设备、未触发 GitHub Actions、未发布。详细命令及日志保存在本地忽略目录
`.superpowers/sdd/2026-09-22-cross-platform-compatibility/`。
