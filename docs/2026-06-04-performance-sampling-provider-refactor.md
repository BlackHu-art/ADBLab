# 性能采样方案重构设计

日期：2026-06-04

## 结论

旧方案把实时采样建立在多条 `adb shell dumpsys/*proc*` 命令和 Python 解析上，主要问题是：

- `dumpsys meminfo/gfxinfo` 本身较重，1 秒级重复调用容易造成 UI 点位延迟和采样抖动。
- `gfxinfo framestats` 是累计窗口，实时展示时需要维护增量基线，否则容易把旧极值带入当前点。
- CPU、内存、帧率来自不同命令，采样时间戳不一致，曲线会出现“看起来同一时刻、实际不是同一批数据”的失真。
- 解析逻辑越来越多，继续修 parser 会让采样层和展示层耦合更重。

新的方向改成“采样 Provider + 统一样本模型”：

1. `psutil-host`：监控本机进程和 ADBLab 自身资源占用。它适合 Windows/Linux/macOS 的桌面进程，不适合直接采 Android App。
2. `perfetto-android`：Android App 的主采样后端。通过 Perfetto 录制系统 trace，使用 Trace Processor/PerfettoSQL 分析 CPU scheduling、frame timeline、memory 等数据。
3. `android-agent`：需要低延迟实时曲线时，在设备端运行轻量采集 agent，一次启动、持续输出 NDJSON，PC 端只负责接收和渲染。
4. `adb-compat`：仅作为兼容/报告兜底，保留启动时间、一次性 meminfo、一次性 gfxinfo，不再作为实时主采样方案。

`psutil` 不是 Python 标准库，是第三方库；它的价值是给本机进程提供跨平台采集 API。Android 设备侧真实性能采集仍应走 Perfetto 或设备端 agent。

## Provider 接口

Provider 统一输出现有面板能消费的 `PerformanceSnapshot`，后续再把图表数据升级为更通用的 sample/counter 结构。

```python
class PerformanceSampleProvider(Protocol):
    name: str

    def start(self, target: str) -> None: ...
    def sample(self, target: str = "") -> PerformanceSnapshot: ...
    def stop(self) -> None: ...
```

### psutil-host

用途：

- 监控 ADBLab 自身进程。
- 监控本机上由 ADBLab 拉起的工具，例如 `scrcpy.exe`、`adb.exe`、`python.exe`。
- 做桌面端性能面板 demo 或本机回归测试。

采样字段：

- CPU：`Process.cpu_percent()`。
- Memory：`Process.memory_info().rss` 映射为 `MemorySample.total_pss_kb`。
- Threads：`Process.num_threads()`。
- Process identity：PID、进程名、exe/cmdline。

限制：

- 不能读取 Android 设备内 App 的 CPU/PSS/frame timeline。
- 首次 `cpu_percent(None)` 只用于建立 baseline，第二次之后才有稳定百分比。

### perfetto-android

用途：

- Android App 的主性能后端。
- 场景采集、报告、深度分析。

采集方式：

- 使用 device `/system/bin/perfetto` 或 Perfetto 官方 `record_android_trace`。
- API 29+ 输出 `.perfetto-trace`；更老设备按能力降级。
- 本机存在 Trace Processor 时自动 SQL 分析；不存在时保存 trace 并提供 Perfetto UI 打开入口。

建议数据源：

- `sched` / CPU scheduling：定位线程和 CPU 占用。
- `freq`：CPU 频率。
- `gfx` / frame timeline：帧耗时、jank。
- `view` / `input` / `wm` / `am`：页面、输入、Activity/window 事件。
- memory counters：进程内存趋势，必要时扩展 heapprofd。

### android-agent

用途：

- 实时曲线需要 250-500ms 级刷新时使用。
- 解决反复启动 `adb shell` 的开销。

实现形态：

- PC 端通过 `adb shell` 启动一次脚本或小二进制。
- 设备端循环读取 `/proc/stat`、目标进程 `/proc/<pid>/stat`、`/proc/<pid>/status`、必要的 `/proc/<pid>/smaps_rollup`。
- stdout 输出 NDJSON：一行一个时间点。
- PC 端 worker 持续读取，直接写入 session。

限制：

- `smaps_rollup` 可用性随 Android 版本/权限变化。
- Java/native heap 细分仍需要 Perfetto/heapprofd 或兼容 meminfo。

## 迁移顺序

### Step 1：Provider 层

- 新增 `models/performance/providers.py`。
- 新增 `PsutilHostProvider`，用于验证 provider 接口和本机进程采样。
- 测试 provider 输出的 `PerformanceSnapshot` 能被现有 dashboard 消费。

### Step 2：实时面板切 provider

- `PerformanceMonitorDialog` 增加采样后端选择：
  - Android 默认 `perfetto-android` 或 `android-agent`。
  - Host/本机进程使用 `psutil-host`。
- UI 不直接调用 ADB parser，只调用 provider。
- `PerformanceSession` 只接收 provider 输出的 counter。

### Step 3：删除旧 ADB 实时解析

可删除或降级的代码：

- `PerformanceService.cpu_sample()` 的实时主路径。
- `PerformanceService.memory_sample()` 的 1 秒轮询路径。
- `PerformanceFrameWorker` 的 1 秒 `dumpsys gfxinfo` 轮询路径。
- `parse_gfxinfo_output()` / `parse_meminfo_output()` 只保留报告兼容，移出实时链路。

保留的兼容能力：

- `am start -W` 启动时间。
- Quick Check 的一次性 `meminfo/gfxinfo`。
- 无 Perfetto/agent 时的降级报告。

### Step 4：Perfetto 报告

- 新增 `perfetto_provider.py` 或在 `providers.py` 中拆分。
- 录制 trace 到报告目录。
- 优先使用本机 Trace Processor SQL 输出：
  - frame p50/p90/p95/p99
  - jank/frozen frame
  - process/thread CPU slice
  - memory counter
- 无 Trace Processor 时只保存 trace，并提示用 Perfetto UI 打开。

### Step 5：设备端 agent

- 新增 agent 启动/停止服务，使用 `ProcessRunner` 管理长生命周期进程。
- 输出 NDJSON，PC 端解析成本地 sample。
- 替换实时曲线主数据源。

## 验收标准

- 实时面板不再每秒跑多条 `dumpsys`。
- 点击 Start 不在 UI 线程同步跑 ADB 采样命令。
- Android 场景监控以 Perfetto trace 或设备端 agent 为主。
- psutil 只用于 Host provider，不误标为 Android 采样方案。
- 旧 ADB parser 从实时链路移除，只保留兼容 Quick Check/报告路径。
