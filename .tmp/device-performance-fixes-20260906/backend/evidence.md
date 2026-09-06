# MobilePerf / Monkey 后端修复证据

日期：2026-09-06。范围仅三个内核文件及两个直接测试文件；其余脏工作树由主任务或其他代理所有。

## 已证实根因

1. `ADB.start_activity()` 将每一行按所有 `: ` 拆分后解包两个变量，Warning、Error、Intent 的值含第二个分隔符时复现 `ValueError: too many values to unpack`。改为只拆首个分隔符，保留完整值。
2. `Monkey.start()` 先设置 `running=True`，随后 `start_monkey()` 检查该状态直接返回；真实启动入口完全没有调用 ADB。改为成功取得进程并准备 reader 后再提交运行状态，重复调用仍只启动一次。
3. 原异步 ADB 分别创建 stdout/stderr PIPE，但 Monkey 只有 stdout reader。Monkey 现在显式请求合并 stderr；其他 ADB 消费者保持默认行为。
4. 原 reader 不识别 EOF，短日志不会落盘，后台错误只记录日志；StartUp 对 Monkey 启动失败也像可选指标一样继续。现在 EOF 回收 reader、刷新尾日志，并将启动/运行/停止失败作为 MonkeyError 交回采集主线程。主线程先停止其他采集器、生成可用的部分报告，再传播异常使子进程失败。可选指标的容错不变。

## 修改范围

- `mobileperf/android/tools/androiddevice.py`：首分隔符解析；异步命令可选合并 stderr。
- `mobileperf/android/monkey.py`：真实启动、重复启动保护、失败可重试、本地进程与 reader 有界回收、短日志刷新、失败交回主线程。
- `mobileperf/android/startup.py`：用户明确启用的 Monkey 必须成功启动/执行；停止后再次检查 reader 的晚到结果；其他采集器和报告清理继续执行。移除重复的 Monkey 全局停止调用，由启动实例负责。
- `tests/test_mobileperf_parsers.py`、`tests/test_mobileperf_monkey_lifecycle.py`：模拟外部命令的直接回归。

所有开始时原字节存于当前目录 `*.baseline`，没有替换或恢复工作树。

## 验证

旧代码直接红灯：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mobileperf_monkey_lifecycle.py tests/test_mobileperf_parsers.py -k 'monkey or async_adb or start_activity'
```

结果：**9 failed, 1 passed, 6 deselected**，详见 `red-tests.log`。失败包含用户同类 ValueError 和实际启动 ADB 调用次数为 0。

生产代码稳定后的后端关联组合：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mobileperf_monkey_lifecycle.py tests/test_mobileperf_parsers.py tests/test_model_mobileperf.py tests/test_mobileperf_runner_concurrency.py tests/test_mobileperf_androiddevice_log_safety.py tests/test_mobileperf_runtime_data.py
```

结果：**86 passed in 2.96s，exit 0**。此后仅添加三项直接测试，未再修改生产代码。

最终直接组合：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mobileperf_monkey_lifecycle.py tests/test_mobileperf_parsers.py
```

结果：**27 passed in 0.34s，exit 0**。覆盖成功、重复启动、启动失败重试、thread.start 失败、缺失 stdout、短日志 EOF、非零退出、terminate 超时升级 kill、用户停止、运行/停止阶段失败、停止错误仍保留报告/清理其他采集器、可选指标失败不影响 Monkey、冻结 worker 不吞 MonkeyError。所有设备/命令为 fake，未运行实际设备 Monkey。

Ruff：三个生产文件与两个测试文件 **All checks passed**。

中文注释检查：三个生产文件通过。`git diff --check`：本轮跟踪文件通过。

Pyright：三个 vendored 内核文件存在既有类型债，**不宣称全绿**。`compare_types.py` 在隔离目录运行原字节基线并比较诊断；基线 **53 errors**，当前 **46 errors**，无新增诊断。原始 JSON 分别为 `pyright-baseline.json` / `pyright-current.json`。不扩大修复历史类型问题。

## 验证边界

未连接或读取用户真实设备、未运行用户设备 Monkey、未读写用户配置、未改依赖或打包入口、未运行全量测试或打包。远端停止沿用现有 ADB `kill_process` API，模拟验证调用、异常传播和本地进程/reader 退出；未声称在物理设备上确认进程停止。UI 开关、进度与多设备上下文由主任务独立验证。
