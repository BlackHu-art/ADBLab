# Remote Windowing Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本阶段由同一个 Remote owner 顺序执行，主任务安排独立审阅；不要并行编辑共享旧 tracker。

**Goal:** 将窗口契约和原生平台适配实际迁入功能目录，同时保留旧入口和全部已知替换语义。

**Architecture:** `windowing` 仅承载 contracts、Win32、X11 与 WinEvent 实现。
旧 `window_tracking` 保留实际策略/工厂，其余两个旧模块为显式同对象导出。

**Tech Stack:** Python 3.11、ctypes、pytest、项目 `.venv`、PySide6 离屏消费者测试；无新增依赖。

**Spec:** [设计](../specs/2026-10-24-remote-windowing-package-design.md)。日期 2026-10-24；实施、独立任务审阅及最终集成审阅均已通过。

## Global Constraints

- 不更改窗口匹配、PID 归属、焦点、几何、DPI、便携工具栏、事件或关闭行为。
- 不新增依赖、修改 CI/版本/数据格式；不提交、推送或回退已有未提交成果。
- 禁止通用动态代理、修改 `sys.modules` 实现兼容、重复实现类、复制全局资源集合。
- 新包 `__init__.py` 不聚合任何对象；原 `services.remote.__init__.py` 不改。
- 不修改共享 conftest/marker，不运行真实 native 测试、ADB 或设备操作。
- 所有本阶段 pytest 命令使用 `-m "not integration"`；offscreen 不能代替该筛选。
- 仅主任务把通过审阅的草案发布到正式 docs；Remote owner 不编辑正式 docs、GUI 或其他阶段文件。

## Review Focus

1. 整个旧模块 `sys` 被替换而非只改属性：原平台测试必须原样通过，不能把 patch 改到新实现掩盖失败（Task 1）。
2. 反向导入时旧新对象身份、协议 runtime check 与事件集合共享：参数化干净子进程与 fake 关闭/重试测试固定（Task 1、2）。
3. 新 leaf 导入触发兄弟后端或原生资源：干净子进程的限定模块集合断言和 ctypes 加载哨兵固定（Task 1）。
4. X11 handler 的进程级作用域、构造失败连接清理及 ABI 被拆散：原 fixture 改真实 owner，原错误恢复和释放测试保持（Task 1、2）。
5. 迁移后 Dock 的关闭/替换遇到晚到事件：只在 fake/offscreen 消费者中验证 queued 通知与工具窗退休（Task 2）。

---

## Task 1: 原子迁移平台所有权与兼容路径

**Files:**

- Create: `services/remote/windowing/__init__.py`、`contracts.py`、`win32.py`、`x11.py`、`events.py`。
- Modify: `services/remote/window_tracking.py`、`x11_window_tracking.py`、`window_events.py`。
- Create: `tests/test_remote_windowing_imports.py`。
- Modify: `tests/test_x11_window_tracking.py`（仅 `_module()` 定位）；不提前改它导致旧基线无法运行。
- Read/run unchanged: `tests/test_window_tracking_platform.py`、`tests/test_remote_window_tracking.py`、`tests/test_remote_window_events.py`。

**Interfaces:**

Consumes 当前 `WindowsWindowTracker`、`create_window_tracker` 和设计中的原平台签名。
Produces 设计“文件结构与精确符号所有权”列出的新模块和 alias；五个 contracts 对象及 Win32 类保持旧新同一身份。
保留 `WindowsWindowTracker.__module__ == 'services.remote.window_tracking'` 和 factory 同模块真实定义。

- [x] **Step 1: 检查所有权并建立最小行为基线。**

执行 `git status --short`、目标路径 `git diff`，检查更近 AGENTS；若目标已有其他作者的新改动，先核对，
不得覆盖。阅读当前 spec 和相关原代码，检查新增引用（包括 `__module__`、pickle、私有 loader 和 ABI）。
本轮边界是原生契约/平台归属，直接验证身份、平台准入、事件释放、X11 loader：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" tests/test_remote_window_tracking.py tests/test_window_tracking_platform.py tests/test_remote_window_events.py tests/test_x11_window_tracking.py
```

预期全部通过；若失败，记录节点、当前文件差异和失败原因，不修改无关阶段，不以历史数字代替基线。
`test_remote_window_tracking.py` 尾部 native hidden-window 节点带 integration，不得漏掉筛选。

- [x] **Step 2: 新增结构/兼容测试并观察红灯。**

在 `test_remote_windowing_imports.py` 写以下用例，全部使用标准库和子进程，无 Qt fixture；
不用新模块顶层 import 使整文件收集失败，测试体内导入以精确显示失败。
子进程统一 `[sys.executable, '-c', script]`、`cwd=Path(__file__).resolve().parents[1]`、
`capture_output=True, text=True, timeout=20`，断言 `returncode == 0` 并附 stdout/stderr。

| 测试名 | 参数与必要断言 |
| --- | --- |
| `test_legacy_exports_share_identity_in_either_import_order` | `new_first=[False,True]`；四组 old/new/names 为 tracking/contracts 的五个名称、tracking/win32 的 `_Win32WindowApi`、旧 X11/new x11 的 `X11WindowApi`、旧 events/new events 的类与集合；逐名 `getattr(old, name) is getattr(new, name)` |
| `test_windowing_leaf_imports_keep_unrelated_backends_unloaded` | 对 package、contracts、win32、x11、events 各起干净子进程；本阶段模块集合必须符合下表，不断言 core/Qt 不存在 |
| `test_windowing_imports_do_not_open_native_resources` | 参数为五个新路径和三个旧路径，各起子进程；导入前给 `ctypes.WinDLL`、`ctypes.WINFUNCTYPE`、`ctypes.CDLL`、`ctypes.util.find_library` 安装抛 `AssertionError` 的哨兵（Windows 属性不存在时也显式赋值）；import 成功，无 API 构造。不得拦截 `CFUNCTYPE`，X11 定义 ABI 合法使用它 |
| `test_contract_defaults_and_optional_event_protocol_are_preserved` | 新 DTO 前八个字段用既定值构造，断言 `dpi == 96`、`foreground_hwnd == 0`；赋值触发 `FrozenInstanceError`；复用 `FakeWindowApi/EventWindowApi` 验证 `isinstance(fake, contracts._EventWindowApi)` 分别 False/True，旧与新协议 `is` 相同 |

限定模块集合表（只比较旧三个模块和新 package/四个 leaf，不比较祖先已有聚合）：

| 首次导入 | 允许出现的本阶段模块 |
| --- | --- |
| `services.remote.windowing` | 仅 package |
| `...windowing.contracts` | package、contracts |
| `...windowing.win32` | package、contracts、win32 |
| `...windowing.x11` | package、contracts、x11 |
| `...windowing.events` | package、events |

不要在父测试进程删除 sys.modules 模拟冷启动；每组用新子进程。
若原祖先聚合触发哨兵，先定位实际调用；不能为了迁移测试擅改聚合包，必要时只对本阶段导入增量设置哨兵并记录限制。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" tests/test_remote_windowing_imports.py
```

预期因 `services.remote.windowing` 尚不存在而失败；确认失败为目标缺失，不能因拼错或环境错误假记红灯。

- [x] **Step 3: 按设计原样迁移唯一实现。**

1. 新建仅中文包说明的 `windowing/__init__.py`；把 tracker 原第 17–62 行类型/DTO/协议搬到 contracts，
   引入其标准库依赖；DTO字段、默认值、装饰器保持。旧文件导出五个同名 alias。
2. 把原 tracker 第 260 行起三份 Win32 类整体搬到 win32，带上 ctypes/wintypes/os/Callable/Iterator/contextmanager；
   从 contracts 取得 DTO、矩形、订阅协议。`subscribe_changes` 的局部 import 改为新 events 字面路径。
3. 把旧 X11 文件整体搬到 x11，仅把 DTO import 改为 contracts；旧文件缩为中文兼容说明和
   `from services.remote.windowing.x11 import X11WindowApi as X11WindowApi`。
4. 把旧 events 文件整体搬到 events；旧文件缩为中文说明及两项显式 alias，不新建集合。
5. tracker 清理已迁出的 import 和定义，保留真实类/工厂、原 sys/Win32 alias 读取与分支内旧 X11 import。
   旧 `_Win32WindowApi` 用同名显式 alias；不改 Dock、Remote 聚合包、后台聚焦服务。
6. `tests/test_x11_window_tracking.py::_module()` 的字符串改为 `services.remote.windowing.x11`；
   FakeX11 的 `_XErrorHandler/_XErrorEvent`、fixture 的 `_load_x11/_load_xrandr` 自动跟随真实 owner，其他断言不动。

- [x] **Step 4: 观察绿灯并复核语义差异。**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" tests/test_remote_windowing_imports.py tests/test_remote_window_tracking.py tests/test_window_tracking_platform.py tests/test_remote_window_events.py tests/test_x11_window_tracking.py
```

预期全部通过，原平台测试完全不改。逐块比较移动前后字段/argtypes/restype、ABI整数类型、异常、
hook 的注册/撤销顺序、X11 error lock 和 handler finally；只允许归位所需 import/说明变化。
作为任务可审阅检查点，不 commit、不暂存其他作者文件。

## Task 2: 共享清理资源与实际消费者验收

**Files:**

- Modify: `tests/test_remote_window_events.py`（新增 fake 兼容回归，保留原断言）。
- Run unchanged: Task 1 五文件、`tests/test_remote_dock.py`、`tests/test_remote_dock_updates.py`。
- Main-task-only documentation: 正式设计/计划、`docs/README.md`、roadmap；`MODULE_MAP.md` 仅补窗口后端新所有权和直接测试入口。

**Interfaces:**

Consumes Task 1 旧新同身份 `WinEventSubscription/_RETAINED_SUBSCRIPTIONS` 和旧 `_Win32WindowApi.subscribe_changes`。
Produces fake 失败/重试可观察证据、Dock 关联结果及明确的未验证边界；不新增生产接口。

- [x] **Step 1: 增补集合共享回归。**

测试名 `test_legacy_and_new_event_exports_observe_same_failed_release`，参数 `failure=['unhook','wrong_thread']`。
复用当前 `FakeUser32`、`_subscribe()`（它已把 WINFUNCTYPE 换为 CFUNCTYPE，且用 object.__new__ 绕开 WinDLL）。
记录旧集合的 `before = set(old._RETAINED_SUBSCRIPTIONS)`，断言旧新集合/类 `is`，订阅实例类型就是新类。
unhook 分支让 FakeUser32.UnhookWinEvent 返回 False；wrong_thread 分支用短期 Python thread 调用 close 并 join，
断言线程已结束、fake hooks 尚未删除。两分支均断言通知已禁用且 subscription 同时在旧新集合中。
恢复 fake unhook 后在原线程 close，断言三 hook 释放、集合恢复 `before`、晚到 fake emit 无 callback。
使用 try/finally 原线程重试清理，测试失败不能污染全局 retained set。

这是迁移契约的补充测试，Task 1 之后可以直接绿；不伪造行为缺陷来满足红灯。Task 1 新目录导入已提供真实红绿。

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" tests/test_remote_window_events.py
```

- [x] **Step 2: 跑直接集合与 fake Dock 消费者。**

若 Task 1 通过后仅新增事件测试，可只重跑该直接文件和关联消费者；不要无变化重复五文件。
扩大到 Dock 的原因：它是工厂唯一已检出的生产消费者，持有 tracker、队列通知与工具窗关闭协议。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" tests/test_remote_dock.py tests/test_remote_dock_updates.py
```

重点已有节点：`test_retiring_session_releases_native_connection_once`、
`test_independent_xcb_toolbar_retires_popup_and_rejects_late_input`、
`test_destroyed_view_revokes_session_and_destroys_timer_and_tools`、
`test_window_event_burst_updates_latest_geometry_without_polling_other_sessions`、
`test_pending_and_late_window_events_cannot_reopen_a_closed_dock`。
环境变量只在当前验证 shell 设置；不修改全局配置。所有预期为通过，记录真实 passed/deselected 数量。

- [x] **Step 3: 最小静态门禁与源码 packaging 自检。**

```powershell
.\.venv\Scripts\python.exe -m ruff check services/remote/windowing services/remote/window_tracking.py services/remote/x11_window_tracking.py services/remote/window_events.py tests/test_remote_windowing_imports.py tests/test_x11_window_tracking.py tests/test_remote_window_events.py
.\.venv\Scripts\python.exe -m pyright services/remote/windowing services/remote/window_tracking.py services/remote/x11_window_tracking.py services/remote/window_events.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py services/remote/windowing services/remote/window_tracking.py services/remote/x11_window_tracking.py services/remote/window_events.py
git diff --check -- services/remote/windowing services/remote/window_tracking.py services/remote/x11_window_tracking.py services/remote/window_events.py tests/test_remote_windowing_imports.py tests/test_x11_window_tracking.py tests/test_remote_window_events.py
.\.venv\Scripts\python.exe main.py --self-check packaging
```

未跟踪新文件不在 git diff 默认范围内；主任务对每份新文件补 `git diff --no-index --check -- NUL <path>`，
无空白错误为通过，普通差异的 exit 1 不能误判为空白失败。Pyright 若存在迁移前 ctypes 既有诊断，
先核实原位置基线并分别报告，不加 ignore/降低标准使其消失。

主任务完成正式 docs 后运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py` 与对应 docs diff check。
仅目录迁移无全量触发，不重跑全项目 pytest。源码自检失败如为其他既有工具/资源问题，明确列为未通过/阻塞项，
不能直接加入本阶段打包配置修复。

- [x] **Step 4: 独立审阅、知识库发布与完成记录。**

主任务统一安排独立审阅，审阅上述 globals/alias/ABI/线程清理边界与最终 diff。Remote owner 不再派 agent。
主任务把正式设计和计划记录为当前状态，按最小事实变化补 MODULE_MAP，保留 BUSINESS_FLOW 的行为描述；
不把本轮测试数量写入长期知识库。未获得明确提交要求不 commit/push。

最终记录实际命令和结果、保留的旧入口、`__module__` 与 events logger 名称变化，单列以下未验证项：

- `test_remote_window_tracking.py::test_native_hidden_windows_keep_physical_geometry_and_owned_stacking`。
- `tests/test_remote_dock_native.py`、`tests/test_remote_dock_motion_native.py`、`tests/test_remote_dock_x11.py`。
- PyInstaller 实际产物收集、自检和真实 Windows/X11 焦点/层级/混合 DPI/关闭 hook。

这些真实资源测试本阶段不执行；源码静态可达和 fake/offscreen 通过均不替代它们。

## 计划自审记录

设计文件/符号归位、alias、patch、导入安全由 Task 1 完整覆盖；唯一 retained set 与失败重试、
实际 Dock 消费者由 Task 2 覆盖。无需共享 conftest 修改，无新资源或隐藏导入配置。
仍待执行的所有步骤保持未勾选；本草案阶段没有运行测试结果，也没有跨平台通过声明。

## 主任务预审与执行裁定

主任务独立builder check PASS，三个/两个紧耦合步骤各由单owner顺序实施，完成后统一独立任务审阅；
两阶段按不相交生产/测试并行。root保管全部正式文档与集成，不重复每小步review或全量测试。
Pyright基线/最终由root按实际.venv搜索路径集中执行。packaging也由root稳定后集中执行，
子进程LOCALAPPDATA/XDG_CONFIG_HOME指向临时目录，保留原main自检入口和工具行为；
该命令会写删.self_check探针，不描述为只读或冻结构建验收。owner不重复自检。
精确裁定与before证据在本阶段忽略目录builder-check.md和progress.md。

## 实施验证记录（2026-10-24）

8生产、3测试文件已完成并冻结：五份windowing模块实际拥有契约/平台实现，旧tracker/factory保留真实定义，
旧X11/events为同对象兼容导出。完整ABI、X11错误锁/连接清理、唯一retained set和事件线程协议不变。
六项移动源段比对通过；X11 fixture只改实际owner，原platform/tracker/Dock测试未改。

去重123项通过：原直接70、新导入22、新失败重试2、Dock29；另1项真实native integration明确排除，
不是通过或平台skip。所有pytest显式-m "not integration"并保存数字exit；迁移后直接92pass，事件21pass，
Dock29pass，最终alias格式涉及的imports/events43pass，不重复累加交集。19项新路径缺失的真实红灯已记录。
限定Ruff、中文注释、diff及新文件空白通过；root按实际解释器路径运行8生产Pyright，0错误/0警告。
root集中源码packaging自检使用临时数据环境，exit0且无残留.self_check；不代表PyInstaller收集或真实平台通过。

独立任务审阅Spec/Quality PASS，无分级缺陷；最终集成审阅另记。类__module__及events logger名称随实现迁入，
不伪造反射元信息相同；保留原平台选择globals、工厂路径和公开对象身份。
未运行真实Windows/X11窗口/hook/display、native Dock测试、Android设备、全量或冻结构建。
完整命令/数字exit/补丁/hash与报告见`.superpowers/sdd/2026-10-24-remote-windowing-package/`。

## 最终审阅与交付

2026-10-24，独立最终审阅 PASS，无 P0–P3 findings。审阅固定30路径与20代码路径，
核对两个完整补丁、关键源段和实际验证记录；305项通过、13生产文件类型无诊断。
审阅未重跑测试；1项真实native排除，既有UI-09/UI-10未修复或重验，未验收实机或冻结产物。
原integration-hashes保留，状态收尾后的delivery-hashes另存；全项目持续目标仍在推进。
