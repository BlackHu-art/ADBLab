# ADBLab 性能测试监控面板实现方案

日期：2026-06-01
目标：在 ADBLab 左上角工具栏新增 Performance 入口，按当前选中设备分别打开原生性能监控弹窗，结合 Perfetto / Systrace / dumpsys / am start / LeakCanary 等能力，自动化检测帧率、启动时间、内存趋势与可疑泄漏，并输出可保存、可复测、可对比的报告。

## 结论

推荐采用“ADBLab 原生面板 + 分层采集服务 + 多级降级”的实现，不把第三方 UI 嵌入 ADBLab。

核心链路：

1. 帧率 / 卡顿：优先 `dumpsys gfxinfo <package> framestats` 做快速统计，Perfetto Frame Timeline 做深度追踪，Systrace/atrace 作为 API 28 设备的兼容方案。
2. 启动时间：优先 `adb shell am start -S -W` 和 Logcat `Displayed` / `Fully drawn` 解析，后续支持 Macrobenchmark 导入作为专业基准数据。
3. 内存泄漏：先做 `dumpsys meminfo` 趋势 + Activity/View/Object 计数增长检测；可选接入 LeakCanary instrumentation 自动断言；Android 10+ 且应用 debuggable/profileable 时再启用 Perfetto heapprofd。
4. 报告：每次采集生成 `summary.json`、`metrics.csv`、原始 trace/log/meminfo 文件和一份 HTML/Markdown 报告。

## 当前项目与设备证据

### ADBLab 当前结构

已检查当前代码：

- 主窗口：`gui/main_frame.py`
- 功能标签容器：`gui/panels/side_panel.py`
- 现有 App 性能快捷入口：`gui/panels/app_panel.py`
- 系统命令入口：`gui/panels/system_panel.py`
- 控制器分发：`controllers/_base.py`、`controllers/_app.py`
- 统一短命令执行：`models/base/command_runner.py`
- 统一长生命周期进程：`models/base/process_runner.py`
- 现有测试诊断能力：`models/adb_testing.py`

设计约束：

- 新功能应该通过左上角第 4 个工具栏按钮打开按设备绑定的独立弹窗，不继续堆到 `AppPanel` 的 `Performance Diagnostics` 小区块里，也不新增右侧 `Performance` Tab。
- 短命令统一走 `CommandRunner`，例如 `dumpsys gfxinfo`、`dumpsys meminfo`、`am start -W`。
- 长任务统一走 `ProcessRunner`，例如 Perfetto trace、logcat 持续采集、monkey + 性能采样联动。
- UI 只展示状态和触发本设备采集，采集、解析、报告生成放到 `models/performance/`；P0 不新增全局 controller，后续批处理/CI 再接 controller mixin。

### 当前模拟器能力

已在当前连接设备上验证：

- `adb devices`：存在 `emulator-5554 device`
- `adb shell getprop ro.build.version.sdk`：返回 `28`
- `adb shell command -v perfetto`：返回 `/system/bin/perfetto`
- `adb shell command -v atrace`：返回 `/system/bin/atrace`
- `adb shell dumpsys gfxinfo com.android.launcher3 framestats`：可输出 `Total frames rendered`、`Janky frames`、百分位、`---PROFILEDATA---`
- `adb shell dumpsys meminfo com.android.launcher3`：可输出 PSS、Java Heap、Native Heap、Views、Activities 等字段
- `adb shell am start -W -n com.android.launcher3/.Launcher`：可输出 `ThisTime`、`TotalTime`、`WaitTime`
- 本机未找到 `trace_processor_shell` / `perfetto` 主机侧分析工具，需要后续作为可选依赖检测

注意：当前模拟器是 API 28。Perfetto 命令存在，但 heapprofd 官方要求 Android 10+，因此当前模拟器不适合作为 heapprofd 泄漏检测验证设备；应优先验证 gfxinfo、meminfo、am start 和 Systrace/atrace 降级链路。

## 外部方案依据

- Android 启动指标：Android 官方使用 TTID 和 TTFD 衡量启动，`am start -S -W` 可得到 `ThisTime`、`TotalTime`、`WaitTime`，Logcat 中 `Displayed` 对应 TTID，`Fully drawn` 依赖应用调用 `reportFullyDrawn()`。参考：https://developer.android.com/topic/performance/vitals/launch-time
- Android 渲染指标：慢帧通常按 16ms 以上观察，冻结帧为 700ms 以上；官方建议用 `dumpsys gfxinfo package_name` 判断设备是否记录渲染时间，也可以用 Systrace 定位单帧问题。参考：https://developer.android.com/topic/performance/vitals/render
- 命令行 Systrace：Android 官方仍保留命令行生成 HTML trace 的方案，API 28+ 也可以用系统 tracing 能力。参考：https://developer.android.com/topic/performance/tracing/command-line
- JankStats：适合应用内埋点上报每帧 jank、帧耗时和 UI 状态，适合作为被测 App 可改造时的增强插件。参考：https://developer.android.com/topic/performance/jankstats
- Macrobenchmark：官方基准测试方案，支持 `StartupTimingMetric`、`FrameTimingMetric`、`TraceSectionMetric`，适合作为 CI/基准测试数据源。参考：https://developer.android.com/topic/performance/benchmarking/macrobenchmark-overview
- Perfetto Trace Processor：可用 SQL 查询 trace 中的 slice/counter/frame 数据，是深度分析和报告自动化的核心。参考：https://perfetto.dev/docs/analysis/trace-processor
- Perfetto heapprofd：Android 10+ 支持按调用栈采样 native/java allocation，但 user build 通常要求 app debuggable 或 profileable。参考：https://perfetto.dev/docs/data-sources/native-heap-profiler
- LeakCanary：适合开发/测试包做 UI 测试内存泄漏断言，`LeakAssertions.assertNoLeaks()` 可在 instrumentation 测试中让泄漏直接失败。参考：https://square.github.io/leakcanary/ui-tests/

## 功能边界

### P0 必须做

- 左上角第 4 个工具栏按钮新增 `Performance` 入口，按设备打开独立 `Performance Monitor - <device>` 弹窗。
- 弹窗绑定单个设备，支持包名、启动 Activity、实时在线状态、当前包名、采样时长和基础阈值判定。
- 一键运行“快速体检”：启动时间 + gfxinfo 帧统计 + meminfo 快照。
- 一键运行“场景监控”：开始采样、执行用户操作或 monkey、结束采样、生成报告。
- 输出清晰结论：通过 / 警告 / 失败，并给出指标和阈值原因。
- 不阻塞主 UI，所有采集任务异步执行，退出应用时停止后台进程。

### P1 建议做

- Perfetto trace 录制和本地拉取，支持打开 `ui.perfetto.dev` 或复制 trace 路径。
- 自动检测本机 `trace_processor`，存在时自动解析 Frame Timeline、CPU、memory counter。
- 支持多轮启动测试，输出 min / p50 / p90 / p95 / max。
- 支持测试前后 `dumpsys gfxinfo reset` / logcat clear / meminfo baseline。

### P2 可扩展

- LeakCanary instrumentation 模板和结果解析。
- Macrobenchmark JSON / Gradle connectedCheck 结果导入。
- 基线对比：本次指标与历史报告、指定 baseline 对比。
- CI 导出：JUnit XML / JSON gate / Markdown summary。

### P3 深度能力

- heapprofd Java/native allocation 采集和 SQL 自动分析。
- 自定义 Perfetto SQL 模板。
- 与 Remote / Monkey / Shell 动作编排联动，形成可复现性能脚本。

## 弹窗设计

建议把现有 `AppPanel` 内的轻量 `Performance Diagnostics` 保留为快捷按钮，同时在左上角工具栏第 4 个位置新增性能入口：

```text
Toolbar
├─ App Manager
├─ File Explorer
├─ Live Logcat
├─ Performance
├─ Settings
└─ CMD
```

点击 Performance 后按当前选中的每个设备打开一个独立 `Performance Monitor - <device>` 弹窗；同一设备重复点击只激活已有窗口，不重复创建。

Performance 弹窗分区：

1. Target
   - Web Dashboard 可用时，Target 使用真实 HTML 输入控件承载，PySide Target 仅作为 fallback；Target 只占一行，不再展示 Device，设备号由窗口标题和运行状态区表达。
   - Package：默认使用当前前台包名，也允许手动输入。
   - Current Package：一键把实时检测到的前台包名写入 Package。
   - Activity：支持 `package/.Activity`，可空；空时走 launcher intent。
   - Scenario：P0 暂不新增全局场景切换；Quick Check 和 Start Monitor 先覆盖日常排查，Perfetto / Full 作为 P1/P2 增强。

2. Run Controls
   - Web Dashboard 可用时，Run Controls 使用真实 HTML 按钮，并通过 `QtWebChannel` 回调弹窗已有业务方法；PySide 按钮只在 fallback 模式显示。
   - Quick Check：一次性采集启动、帧和内存。
   - Start Monitor：启动持续采样。
   - Stop & Analyze：停止采样并生成报告。
   - Open Report：打开最近报告目录。
   - Export：导出 JSON/CSV/Markdown。

3. Live Metrics
   - 改成 PerfDog 风格的共享时间轴，不再使用 2x2 小图分散展示。
   - Web Dashboard 内部左侧 Metrics 使用真实 HTML chip 负责指标开关：FPS、Jank、PSS、Java、Native、Activity、Views、Online；PySide Metrics 只作为 Web 不可用时的 fallback。
   - Web Dashboard 中间 Realtime Timeline 使用 Canvas 统一横轴展示所有指标，每条指标独占一条横向泳道，显示当前值、最大值、最小值和趋势线。
   - Web Dashboard 右侧 Summary 使用 HTML 卡片展示每个指标的 now / avg / max，便于快速判断当前抖动和长期趋势；PySide Summary 只作为 fallback。
   - 默认 1s 刷新 online/current package/meminfo；Start Monitor 后 5s 刷新一次 gfxinfo，避免 ADB 压力过大。
   - 时间轴保留最近 3600 个点，按默认 1s 采样约保留 60 分钟；事件文本流也保留 3600 条，避免长时间监控时太快丢上下文。
   - Mark 按钮可在当前时间轴插入手动标记，用于记录“进入页面、开始播放、点击按钮”等人为操作点。
   - Web Dashboard 支持鼠标悬浮查看同一时间点多指标读数，拖拽横轴局部缩放，Reset 恢复全量范围。

4. Timeline / Report
   - Web Dashboard 底部使用 HTML Events 和 Report 区域，展示最近事件、当前状态、当前包名和报告摘要；PySide Timeline / Report 文本框只作为 Web 不可用时的 fallback。
   - Report 区域不再只是纯文本：Quick Check / Monitor 结果会转换为结构化 `reportSummary`，包含状态、Startup / Displayed / FPS / Jank / P95 / PSS 等关键指标、Findings 和报告目录。
   - 事件流：start app、reset gfxinfo、sample meminfo、trace started、trace pulled、analysis done。
   - 不直接塞满原始 dumpsys；原始内容放报告文件，UI 只显示摘要和路径。
   - 移除弹窗底部 `QStatusBar`，错误和进度进入 Timeline / Web Events，当前状态放在 Run Controls 右侧并同步到 Web Dashboard 顶部。

### PerfDog 化重构路线

当前 P0 已具备两层时间轴渲染：桌面环境优先使用 `QtWebEngineView + HTML Canvas`，QtWebEngine 不可用或处于 offscreen 测试环境时回退到 PySide6 自绘 QWidget。两层渲染共用 `models/performance/session.py` 数据源，因此后续增强交互不需要重写采集服务。

建议演进顺序：

1. 保持 PySide 控件版本作为 fallback，完成 FPS/Jank/PSS/Java/Native/Views/Online 的可靠采样和导出。
2. `gui/performance_web/` 已新增本地 HTML + Canvas 多泳道 dashboard：HTML 承载 Target、Controls、Metrics、Summary、Events、Report，Canvas 专注实时折线、hover tooltip 和拖拽缩放；普通浏览器打开 `assets/index.html` 时会进入 preview 数据模式，便于脱离 Qt 做视觉验证。
3. 弹窗已根据环境优先加载 WebView；QtWebEngine 不可用时回退到 QWidget 时间轴，Web 可用时不重复渲染 PySide Target、Run Controls、左右侧栏、Timeline 文本框和 Report 文本框。
4. Web Dashboard 通过 `QtWebChannel` 触发 Current Package、Quick Check、Start Monitor、Stop & Analyze、Mark、Open Report 和 Export，数据刷新仍复用弹窗 worker 与 `PerformanceService`，不把采集逻辑写进 HTML。
5. 接入 Perfetto trace 后，把 trace section、帧耗时尖峰、ANR/GC/Activity 切换作为事件 marker 覆盖到同一时间轴。
6. 下一步把结构化 Report 卡片扩展为完整 HTML dashboard 页面，支持历史 baseline 对比和截图/HTML 导出。

## 后端模块设计

新增目录：

```text
models/performance/
├─ __init__.py
├─ types.py
├─ parsers.py
├─ session.py
├─ report_service.py
└─ service.py
```

新增 UI：

```text
gui/dialogs/performance_monitor.py
gui/performance_web/dashboard.py
gui/performance_web/assets/index.html
gui/performance_web/assets/style.css
gui/performance_web/assets/app.js
```

接入点：

- `gui/main_frame.py` 在 `Live Logcat` 后、`Settings` 前新增 `tb_performance`。
- `gui/main_frame.py` 新增 `_show_performance_monitor()`，复用 `_show_device_dialogs(PerformanceMonitorDialog)` 实现按设备开窗和同设备复用。
- `gui/dialogs/performance_monitor.py` 持有每设备独立 worker 和 `PerformanceService`，关闭时只停止本窗口采集。
- `gui/performance_web/dashboard.py` 只负责 QtWebEngine 容器、资源加载和 `QtWebChannel` bridge；页面结构、样式和交互拆到 `gui/performance_web/assets/`，业务执行仍在 `gui/dialogs/performance_monitor.py` 和 `models/performance/`。
- P0 不要求 controller 信号分发；弹窗直接调用性能服务。后续若需要接入全局批处理/CI，再补 `controllers/_performance.py`。
- 当前实现已经切到共享时间轴 + session 模型，旧四宫格折线图已移除。

### 数据类型

`types.py` 建议包含：

```python
@dataclass
class StartupMetrics:
    device_id: str
    package_name: str
    activity: str
    mode: str
    this_time_ms: int | None
    total_time_ms: int | None
    wait_time_ms: int | None
    displayed_ms: int | None
    fully_drawn_ms: int | None
    success: bool
    raw_output_path: str

@dataclass
class FrameMetrics:
    total_frames: int
    janky_frames: int
    jank_rate: float
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    slow_frames: int
    frozen_frames: int
    estimated_fps: float | None

@dataclass
class MemorySample:
    timestamp_ms: int
    total_pss_kb: int | None
    java_heap_kb: int | None
    native_heap_kb: int | None
    graphics_kb: int | None
    activities: int | None
    views: int | None

@dataclass
class PerformanceReport:
    status: Literal["pass", "warn", "fail"]
    summary: dict
    artifacts: dict[str, str]
    findings: list[str]
```

## 采集链路

### 启动时间

冷启动：

```bash
adb -s <device> shell am force-stop <package>
adb -s <device> logcat -c
adb -s <device> shell am start -S -W -n <package>/<activity>
adb -s <device> logcat -d -v time
```

解析：

- `ThisTime`：最后一个 Activity 启动耗时。
- `TotalTime`：整体 Activity 启动耗时，Quick Check 默认看这个。
- `WaitTime`：AMS 等待完成耗时，不直接作为性能 gate，只作为排障字段。
- `Displayed <component>: +XsYms`：TTID，优先级高。
- `Fully drawn <component>: +XsYms`：TTFD，只有应用调用 `reportFullyDrawn()` 才存在。

建议策略：

- 有 `Displayed` 时以 `Displayed` 作为 TTID。
- 无 `Displayed` 时用 `TotalTime` 作为可比近似值。
- 有 `Fully drawn` 时展示 TTFD；没有则显示“未上报 reportFullyDrawn”。
- 每个模式至少跑 5 次，首轮可作为 warm-up，不纳入统计。

### 帧率与卡顿

快速模式：

```bash
adb -s <device> shell dumpsys gfxinfo <package> reset
# 执行测试动作，例如 monkey、Remote 操作、用户手动操作
adb -s <device> shell dumpsys gfxinfo <package> framestats
```

解析：

- 汇总区：`Total frames rendered`、`Janky frames`、`50th/90th/95th/99th percentile`。
- `---PROFILEDATA---`：按 `FrameCompleted - IntendedVsync` 计算单帧耗时。
- slow frame：大于 16.67ms。
- frozen frame：大于 700ms。
- estimated FPS：有效帧数 / 时间跨度，作为近似值；真实刷新率以 Perfetto Frame Timeline 更准。

深度模式：

- API 31+ 优先 Perfetto Frame Timeline。
- API 28 当前模拟器优先 Systrace/atrace + gfxinfo。
- 本机存在 `trace_processor` 时自动跑 SQL，否则仅保存 `.perfetto-trace` 并提示打开 Perfetto UI。

### 内存趋势与泄漏嫌疑

快速模式：

```bash
adb -s <device> shell dumpsys meminfo <package>
```

采样字段：

- `TOTAL`
- `Java Heap`
- `Native Heap`
- `Graphics`
- `Objects` 下的 `Views`、`Activities`、`AppContexts`
- `SQL` 和 `DATABASES` 作为附加诊断

泄漏嫌疑规则：

- 连续 N 次 GC 后 PSS 仍单调上升，且增幅超过阈值。
- Activity 数量在场景结束后不回落。
- Views / ViewRootImpl 数量在页面进出后明显增长。
- Java Heap 增长伴随 GC 频率升高，可标记为 warn。

增强模式：

- Debug / test build 接入 LeakCanary instrumentation，运行 UI 测试后解析 `NoLeakAssertionFailedError` 或 heap analysis 文件。
- Android 10+ 且目标 app debuggable/profileable 时启用 heapprofd，生成 trace 后用 Trace Processor SQL 分析 allocation top callsites。

## 自动化场景

### Quick Check

面向日常手工排查，耗时 5-20 秒：

1. 检查设备和工具能力。
2. 解析当前包名或使用用户输入包名。
3. 执行一次启动测量。
4. reset gfxinfo。
5. 等待 3 秒或执行轻量 monkey。
6. 采集 gfxinfo。
7. 采集 meminfo。
8. 生成摘要和报告。

### Scenario Monitor

面向复测：

1. 用户设定采样时长、包名、阈值、是否启用 Perfetto。
2. `Start Monitor` 后开始 trace/logcat/meminfo 周期采样。
3. 用户手动操作，或选择内置 monkey/启动/页面切换动作。
4. `Stop & Analyze` 停止所有进程。
5. 拉取 trace 和日志。
6. 解析并生成报告。

### CI / 自动化模式

后续可以提供 CLI 或隐藏入口：

```bash
python -m tools.performance_run --device emulator-5554 --package com.example \
  --scenario startup,frame,memory --duration 30 --output reports/performance
```

输出：

- `summary.json`
- `metrics.csv`
- `report.md`
- `raw/gfxinfo.txt`
- `raw/meminfo_*.txt`
- `raw/logcat.txt`
- `raw/trace.perfetto-trace`

## 报告结构

目录：

```text
<save_dir>/performance/<device>_<package>_<HHMMSS>/
├─ summary.json
├─ metrics.csv
├─ report.md
├─ raw/
│  ├─ startup_am_start.txt
│  ├─ startup_logcat.txt
│  ├─ gfxinfo_framestats.txt
│  ├─ meminfo_000.csv
│  ├─ meminfo_raw_000.txt
│  └─ trace.perfetto-trace
└─ charts/
   ├─ memory_pss.csv
   └─ frame_durations.csv
```

`summary.json` 示例：

```json
{
  "status": "warn",
  "device": "emulator-5554",
  "sdk": 28,
  "package": "com.example",
  "startup": {
    "total_time_ms_p50": 840,
    "displayed_ms_p50": 790,
    "fully_drawn_ms_p50": null
  },
  "frames": {
    "total": 1200,
    "janky": 42,
    "jank_rate": 0.035,
    "p95_ms": 24,
    "frozen_frames": 0
  },
  "memory": {
    "pss_start_kb": 61000,
    "pss_end_kb": 73500,
    "activity_delta": 0,
    "views_delta": 8
  },
  "findings": [
    "Frame p95 exceeded 16.67ms but jank rate is under fail threshold.",
    "TTFD unavailable because reportFullyDrawn was not observed."
  ]
}
```

## 阈值建议

默认阈值应可配置并保存在 `resources/app_settings.json`，但不要在测试中反复写入用户本地配置；测试用例用临时 settings。

```json
{
  "performance_thresholds": {
    "startup_cold_warn_ms": 3000,
    "startup_cold_fail_ms": 5000,
    "startup_warm_fail_ms": 2000,
    "startup_hot_fail_ms": 1500,
    "jank_rate_warn": 0.05,
    "jank_rate_fail": 0.10,
    "slow_frame_ms": 16.67,
    "frozen_frame_ms": 700,
    "memory_pss_growth_warn_kb": 10240,
    "activity_growth_fail": 1
  }
}
```

## 降级策略

| 能力 | 优先级 | 当前模拟器 | 降级方案 |
| --- | --- | --- | --- |
| `dumpsys gfxinfo framestats` | P0 | 可用 | 无输出时退到普通 `dumpsys gfxinfo` 汇总区 |
| `am start -W` | P0 | 可用 | 解析 logcat `Displayed` |
| `dumpsys meminfo` | P0 | 可用 | 退到 `top` / `proc/<pid>/status` |
| `perfetto` device binary | P1 | 可用 | API 28 上优先 Systrace/atrace |
| `trace_processor` host binary | P1 | 当前未安装 | 保存 trace，提示用户安装或打开 Perfetto UI |
| `heapprofd` | P3 | 当前 API 28 不满足 | LeakCanary 或 meminfo 趋势 |
| LeakCanary | P2 | 需要被测 app 接入 | 仅做外部检测项，不强依赖 ADBLab |
| Macrobenchmark | P2 | 需要 Android 工程测试模块 | 支持结果导入，不作为 ADBLab P0 前置 |

## 实施步骤

### Step 1：方案与骨架

- 新增本方案文档。
- 新增 `models/performance/types.py` 和 `parsers.py`。
- 为 `gfxinfo`、`meminfo`、`am start -W` 解析器写单元测试。

验收：

- `py -3.11 -m pytest -q tests/test_performance_parsers.py`
- 解析器可以处理当前模拟器采集到的 launcher 样本。

### Step 2：P0 快速体检服务

- 新增 `service.py` 聚合 P0 启动、帧统计、内存采样和实时快照能力。
- 统一通过 `CommandRunner` 执行短命令。
- 新增 `report_service.py` 生成 JSON/CSV/Markdown。

验收：

- 对 `emulator-5554` 跑 `com.android.launcher3` Quick Check 能生成报告。
- UI 线程无阻塞，日志能即时看到状态变化。

### Step 3：Performance 弹窗与工具栏入口

- 新增 `gui/dialogs/performance_monitor.py`。
- `MainFrame` 工具栏第 4 个功能按钮增加 `Performance Monitor`。
- `MainFrame._show_performance_monitor()` 按选中设备打开窗口，复用已有 `_register_dialog` / `_find_active_dialog`。
- 每个窗口实时刷新 online/current package/meminfo，Start Monitor 后保存采样序列并周期刷新帧统计，Stop & Analyze 后生成报告。

验收：

- 弹窗可输入包名、Activity、时长和阈值。
- 点击 Quick Check 后卡片刷新：启动、帧、内存、报告路径。
- 选中多个设备时，每个设备各打开一个性能窗口；重复点击同设备只激活已有窗口。
- 主窗口关闭时无遗留 `adb logcat`、`perfetto`、`monkey` 等进程。

### Step 4：Perfetto / Systrace 深度追踪

- 在 `models/performance/` 下新增或拆分 `perfetto_service.py`、`systrace_service.py`。
- API 29+ 走 Perfetto config；API 28 走 Systrace/atrace 兼容路径。
- 检测本机 `trace_processor`，存在则自动 SQL 分析，不存在则保存 trace。

验收：

- 当前 API 28 模拟器能走兼容路径并保存 trace/html。
- Android 10+ 设备能保存 `.perfetto-trace`。
- 缺少 host 工具时 UI 不报错，只显示“未安装 trace_processor，已保存原始 trace”。

### Step 5：内存泄漏自动化

- P0：meminfo 趋势检测。
- P2：支持读取 LeakCanary instrumentation 输出。
- P3：Android 10+ heapprofd。

验收：

- 多轮页面进出后能输出 Activity/View/PSS 增长趋势。
- LeakCanary 失败日志能解析成 fail finding。
- heapprofd 不满足条件时能清晰说明原因。

## 代码质量与测试

需要新增测试：

- `tests/test_performance_parsers.py`
- `tests/test_performance_report_service.py`
- `tests/test_performance_services.py`
- `tests/test_model_execution.py` 中覆盖工具栏入口、同设备复用、worker 绑定窗口 service。

测试覆盖：

- `am start -W` 成功、Activity already running、失败输出。
- Logcat `Displayed` 和 `Fully drawn` 解析。
- `dumpsys gfxinfo` 汇总区解析。
- `---PROFILEDATA---` 单帧耗时解析。
- `dumpsys meminfo` PSS、Heap、Objects 解析。
- 阈值判定 pass/warn/fail。
- report 路径和文件命名不污染用户配置。

验证命令：

```bash
py -3.11 -m compileall -q controllers core gui models tests
py -3.11 -m pytest -q
git diff --check
```

当前已验证：

- 普通浏览器打开 `gui/performance_web/assets/index.html` 会进入 preview 模式，展示示例指标、Events、Report 和非空 Canvas 曲线；控制台无错误。
- QtWebEngine smoke 已验证 `WebPerformanceTimelineChart` 能通过 `QUrl.fromLocalFile` 加载外部 HTML/CSS/JS，注入 payload 后 DOM、Canvas 和 `QtWebChannel` action 均正常。
- 真实设备 `emulator-5554` 已验证 `PerformanceService.snapshot()` 能采集当前包 `com.android.flysilkworm` 的 online、meminfo 和 gfxinfo 数据。
- 真实 `PerformanceMonitorDialog(device_ip="emulator-5554")` 已验证 Web Dashboard 可显示 `com.android.flysilkworm`、8 个指标和非空 Canvas，隐藏 PySide fallback 控件由弹窗持有，不再被 Qt 回收。
- 性能 Dashboard 已重排为 Target/Action/Metric/Timeline/Summary/Report 布局；折线图改为共享横轴 + 右侧纵轴刻度，稀疏指标按最近采样值连续显示，避免不同采样频率导致断线。
- Web Dashboard 已接收 Qt 当前主题 palette，暗色/亮色主题切换后背景、边框、文本、按钮和图表颜色同步刷新。
- 2026-06-01 浏览器预览验证：Canvas 有效像素 `134624+`，8 个指标、7 个动作按钮均可识别；稀疏 FPS 样本 `{60, null, null, 58}` 显示为连续持有序列 `[60, 60, 60, 58]`，控制台无错误。
- 2026-06-01 紧凑 UI 二次重构：外层边距和面板间距收紧，底部 Events/Report 合并为 Inspector tabs，图表有效高度提升到约 `484px`；新增 `Abs / Norm / Focus / Delta` 四种显示模式，默认 `Norm` 用 0-100% 归一化突出波动，`Focus` 可双击指标放大单条曲线，`Delta` 显示相对首个可见样本的变化。
- 2026-06-01 浏览器预览验证：Canvas 有效像素 `244783+`，8 个指标、7 个动作按钮、4 个图表模式均可识别；模式按钮不越界，Inspector 的 Report tab 可切换，控制台无错误。

## 风险点

- API 差异：Frame Timeline、heapprofd 在不同 Android 版本差异大，必须先做 capability probing。
- 权限差异：user build 对 heapprofd 和 heap dump 限制更多，不应把它作为 P0。
- 指标误读：`WaitTime` 不是单纯应用启动耗时，报告中要解释字段含义。
- 多设备并发：性能采集会产生较大文件，默认先限制每设备单任务，后续再并发。
- UI 卡顿：原始 trace/log 不在 UI 中全量渲染，只展示摘要和路径。
- 本地工具安装：`trace_processor` 作为可选能力，不能阻断 Quick Check。

## 推荐开发顺序

1. 先实现解析器和报告结构，因为这是后面 UI、Perfetto、CI 都要复用的核心。
2. 再实现 Quick Check，利用当前模拟器即可验证端到端。
3. 再接 UI 面板，保持懒加载，避免拖慢主界面启动。
4. 再做 Perfetto/Systrace 深度追踪。
5. 最后做 LeakCanary/Macrobenchmark/heapprofd 这些需要被测应用或更高 Android 版本配合的增强能力。

## 第一版交付标准

第一版完成后，应满足：

- 用户打开 ADBLab，选择 `emulator-5554`，点击左上角第 4 个 `Performance` 按钮，打开 `Performance Monitor - emulator-5554` 弹窗。
- 点击 `Quick Check`，30 秒内得到启动、帧、内存三类摘要。
- 弹窗打开后每 1 秒刷新设备在线状态、当前包名和基础内存指标。
- 生成报告目录，包含 `summary.json`、`metrics.csv`、`report.md` 和原始采集文件。
- 无论 Perfetto 或 trace_processor 是否可用，Quick Check 都能完成。
- 关闭 ADBLab 后无残留采集进程。
