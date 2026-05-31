# 2026-05-30 Architecture And Logic Optimization

## Scope

This optimization pass reviewed the full project execution flow, UI lifecycle behavior, and high-risk ADB feature paths. The work focused on making process execution predictable, reducing UI-thread stalls, and closing regressions with repeatable tests.

## Completed Changes

### Execution Layer

- Centralized synchronous command execution through `models/base/command_runner.py`.
- Centralized long-running and external process startup through `models/base/process_runner.py`.
- Added `ProcessRunner.spawn()` for untracked external launches such as terminal/file-folder opening.
- Kept ADB path resolution centralized so UI and worker modules no longer resolve executable paths ad hoc.

### UI And Dialog Lifecycle

- Reused active device dialogs instead of opening duplicate App Manager, File Explorer, or Live Logcat windows for the same device.
- Added safe signal disconnection helpers for dialogs that may receive queued signals while closing.
- Improved Live Logcat shutdown behavior to avoid touching deleted widgets after the dialog has closed.
- Moved screenshot folder opening through `ProcessRunner` instead of direct OS/process calls.
- Added VSCode launch configuration so debugging starts from `main.py` with project-root `PYTHONPATH`.

### Feature Logic

- Fixed batch install aggregation so every APK result contributes to the batch tracker.
- Fixed connect-device result handling to persist the actual returned device id.
- Fixed recorded-video pull and bugreport failure paths so command failures are reported instead of hidden.
- Made Monkey stop idempotent:
  - active local process stopped => success;
  - repeated stop with no active Monkey => success with "not running";
  - real ADB/device errors still fail with the device error text.
- Preserved scrcpy and logcat as long-running processes managed by `ProcessRunner`.

### Tests

- Expanded `tests/test_model_execution.py` from targeted smoke coverage to 42 regression cases.
- Covered execution runner behavior, dialog lifecycle safety, scrcpy argument building, file transfer streaming, ADBBridge command behavior, Monkey stop idempotency, bugreport failure handling, and LogService shutdown.

### Follow-up Optimization On 2026-05-31

- Moved File Explorer path parsing, shell command construction, size formatting, chmod mode calculation, and `ls -la` output parsing into `models/file_explorer_service.py`.
- Hardened File Explorer remote shell commands with centralized single-quote escaping so spaces, `$`, double quotes, and single quotes in remote paths do not break command parsing.
- Added configurable `ADBWorker` timeouts and used longer timeouts for root pull/copy/move operations that can legitimately take more than 30 seconds.
- Fixed LogService buffered flushing so logs emitted from worker threads schedule the Qt timer on the service owner thread instead of touching `QTimer` cross-thread.
- Added regression tests for File Explorer pure logic, shell quoting, symlink parsing, worker timeout propagation, and worker-thread LogService flushing.

### Click Response Optimization On 2026-05-31

Connected-emulator baseline (`emulator-5554`) showed that normal short ADB commands are not the only visible delay source:

- `adb devices`: avg 52.9 ms.
- `adb shell wm size`: avg 42.7 ms.
- `adb shell input keyevent HOME`: avg 173.1 ms, max 314.5 ms.
- Remote button submit after queueing: 0.022-0.331 ms.

Root causes found in the UI response path:

- Operation result logs waited for the default 200 ms buffered flush, so a completed command could look late even after the worker finished.
- `MainFrame` refreshed the device combobox after every `operation_completed`, including input, shell, app, and diagnostic operations that do not change the device list.
- Remote key/gesture buttons called ADBBridge from the Qt thread; the first gesture could synchronously run `wm size` before sending `input swipe`.
- Refresh could briefly show no device row when a newly connected serial was not yet persisted in `DeviceStore`.

Implemented fixes:

- `_emit_operation()` now flushes user-visible completion logs immediately.
- Device combobox/list refresh is tied to `devices_updated` only; normal ADB operation completion no longer rebuilds the device UI.
- `RemotePanel` submits key/gesture actions to a single remote input executor, preserving click order while returning control to the UI immediately.
- Device list refresh shows a placeholder row for new serials and replaces it after the background basic-info scan writes `DeviceStore`.
- Background device metadata refresh batches `DeviceStore` writes into one YAML save per scan.

Deferred optimization plan:

- P1: Completed. Added lightweight timing logs around async queue, model execution, signal delivery, and UI handler work for commands that exceed the configured threshold.
- P2: Completed. Added a debounce to continuous device scanning so repeated connect/disconnect changes cannot flood the device panel.
- P3: Completed. Added a Remote action queue status indicator for queued rapid clicks.
- P4: Completed. Added a persistent `adb shell` input session with fallback to per-command process spawning.

### P1 Slow Operation Trace On 2026-05-31

- Added `core/perf_trace.py` as a small helper for attaching and formatting slow-path timing metadata.
- `models.adb_model.async_command` now records queue wait time and model execution time for every asynchronous ADB task.
- `_ADBControllerBase._handle_async_response()` now strips internal timing metadata before business handlers run, then logs a compact `[PERF]` line only when a stage or total duration crosses `performance_log_threshold_ms`.
- Default threshold is `300 ms` via `AppSettings.DEFAULTS`; temporary lower thresholds can be used during local diagnosis without changing production behavior.
- Non-dict async results, such as `get_connected_devices_async()` returning a list, are wrapped only while crossing the signal boundary and restored before controller logic sees them.
- Connected-emulator smoke sample with a temporary `1 ms` threshold:

```text
[PERF] input_keyevent total=190.2ms queue=1.0ms model=182.7ms signal=6.4ms ui=0.0ms
```

### P2 Device Scan Debounce On 2026-05-31

- `_ScanThread` still polls `adb devices` every 3 seconds and emits only when the connected device count changes.
- `MainFrame` now routes scan-thread change notifications through a single-shot debounce timer before calling `ADBController.refresh_devices()`.
- The debounce window is `300 ms`, which preserves fast first refresh while collapsing bursts from emulator/device connect-disconnect jitter.
- Stopping continuous scan also stops any pending debounced refresh, preventing a late refresh after the user disables scanning or exits the app.
- Manual Refresh is unchanged and still calls `ADBController.refresh_devices()` immediately.
- Local debounce smoke sample:

```text
refresh_calls=1
```

### P3 Remote Input Queue Feedback On 2026-05-31

- Remote control now has its own lightweight `Input:` status label under the key/gesture controls, separate from the scrcpy Running/FPS status.
- Remote key and gesture actions still use the single-thread executor introduced in the click-response pass, so ordering is preserved.
- Queue counters are maintained when actions are submitted and completed; UI updates are delivered through a Qt signal back to the panel thread.
- Status text is intentionally compact:
  - `Input: Sending` when one action is in flight.
  - `Input: Queued N` when multiple rapid clicks are waiting.
  - `Input: Sent` after the queue drains successfully.
  - `Input: Failed` if the queued task raises or the executor rejects the submission.
- Local queue smoke sample:

```text
[(1, 0, 'queued'), (1, 1, 'sent')]
```

### P4 Persistent ADB Input Session On 2026-05-31

Connected-emulator measurements showed that process startup was the dominant cost for Remote input:

- Per-command `adb shell input keyevent 3`: avg 156.45 ms, min 136.91 ms, max 188.17 ms.
- Persistent `adb shell` stdin write: avg 0.03 ms, min 0.02 ms, max 0.05 ms.

Implemented fixes:

- Added `ADBInputSession` in `core/adb_bridge.py`.
- `ADBBridge.shell_input()` now keeps one persistent `adb shell` session per device and writes `input ...` commands to stdin.
- If session startup or write fails, `shell_input()` falls back to the previous `ProcessRunner.spawn(["adb", ..., "shell", "input ..."])` path.
- `ADBBridge.close_input_sessions()` closes one device session or all sessions.
- RemotePanel closes input sessions during `closeEvent()` so background `adb shell` processes do not linger after the panel/app exits.
- Real `ADBBridge.shell_input()` smoke sample after warm-up:

```text
bridge_shell_input_session: min=0.03ms avg=0.04ms max=0.05ms
```

## Current Architecture Rules

- Short-lived commands must use `CommandRunner.run()`.
- Long-running managed processes must use `ProcessRunner.start()`.
- Fire-and-forget external launches must use `ProcessRunner.spawn()`.
- UI code must not call `subprocess.run()`, `subprocess.Popen()`, or `os.startfile()` directly.
- ADB model async APIs should return normalized dict results and include context fields such as `device_ip`, `index`, and operation metadata.
- Repeated user actions such as Stop/Kill should be idempotent when the target is already stopped.

## Verification

Validated on Python 3.11:

```powershell
py -3.11 -m compileall -q gui controllers models core utils main.py
py -3.11 -m pytest tests
```

Latest result:

```text
84 passed
```

## Deferred Items

- Runtime-local settings changes in `resources/app_settings.json` were intentionally not included in this optimization commit.
- Account/config changes in `core/mail/mail.yaml` were intentionally not included because they may contain environment-specific credentials.
- Further UI polish can continue from the current architecture without changing the execution-layer contract.

## Global Feature Performance Review On 2026-05-31

### Review Scope

This review expands the previous Remote click-response work to the main feature paths:

- Device refresh and device info: `controllers/_device.py`, `models/adb_device.py`, `gui/panels/device_manager.py`.
- App operations and App Manager dialog: `controllers/_app.py`, `models/adb_app.py`, `models/app_manager_worker.py`, `gui/dialogs/app_manager.py`.
- Screenshot, recording, diagnostics, logcat, and process tools: `controllers/_media.py`, `models/adb_testing.py`, `models/adb_advanced.py`, `gui/dialogs/live_logcat.py`, `gui/dialogs/screenshot_viewer.py`.
- Shell, settings, file, port, and system tools: `controllers/_input.py`, `controllers/_file.py`, `models/adb_system.py`, `models/adb_network.py`.
- Shared UI/log execution layer: `models/adb_model.py`, `models/base/command_runner.py`, `models/base/process_runner.py`, `core/log_service.py`, `gui/panels/log_panel.py`.

### Connected-Emulator Baseline

Measured on `emulator-5554`:

```text
basic info / 3 separate getprop: avg=121.8ms
basic info / one shell batch: avg=39.1ms
basic info / getprop all: avg=41.7ms
full device info / current 14-command shape: avg=501.1ms
full device info / optimized 5-command estimate: avg=203.4ms
app manager / pm list packages -f: avg=41.2ms, packages=73
app manager / one dumpsys package: avg=46.3ms
screenshot current temp+pull flow: avg=394.9ms
screenshot exec-out direct flow: avg=230.3ms
```

### P1 Optimization Plan

1. Batch device info queries. Completed.

   Current `ADBDevice.get_devices_basic_info()` runs three separate `getprop` commands, and full device info runs fourteen commands. Replace the property part with one `adb shell getprop` parse or one shell batch, then keep only the probes that truly need separate commands (`df`, `meminfo`, `wm`, `ip addr`). Expected result: basic refresh from about 122 ms to about 40 ms per device; full info from about 501 ms to about 203 ms.

   Implemented:

   - `ADBDevice.get_devices_basic_info()` now uses one shell batch for the three properties used by device refresh.
   - `ADBDevice.get_device_info_async()` now uses one marker-delimited shell batch for properties, storage, memory, wm size/density, and wlan info.
   - Added parsing tests for getprop output, marker sections, fallback behavior, and full device info extraction.

   Validation:

   - Add unit tests for getprop parsing and missing-property fallback.
   - Re-run connected-emulator benchmark.
   - Check manual Refresh and Device Info UI.

   Latest connected-emulator result:

```text
ADBDevice.get_devices_basic_info: avg=71.8ms, min=65.4ms, max=74.4ms
ADBDevice.get_device_info_async.__wrapped__: avg=82.9ms, min=69.1ms, max=119.4ms
```

2. Make App Manager details lazy and indexed. Completed.

   `AppManagerWorker._load_detail_batch()` currently runs `dumpsys package <pkg>` for every installed package. On the test emulator one package costs about 46 ms, so 73 packages can create seconds of background work. `AppManagerDialog._on_detail()` then scans icon rows and table rows for every detail update, making UI updates O(n^2).

   Implemented:

   - Load package list first and keep the UI interactive.
   - Fetch details only for visible rows or the first small page.
   - Cache details by package and invalidate after install/uninstall/enable/disable.
   - Maintain `package -> row/item` maps so detail updates are O(1).
   - Debounce detail loading after search/filter and view-mode changes.

   Validation:

   - App Manager open time on emulator.
   - Search/filter while details are still loading.
   - Modify app operation still refreshes stale entries correctly.

   Latest connected-emulator result:

```text
pm list packages -f: avg=56.2ms, packages=73
lazy visible detail batch (30 pkgs): avg=1317.3ms
old all-detail estimate (73 pkgs): avg~3205.5ms
```

3. Batch UI log rendering. Completed.

   `LogService` buffers internally, but `LogPanel` still receives and renders one line at a time. High-volume actions such as Monkey, logcat export, shell output, and device info can flood `QTextEdit`.

   Target shape:

   - Add a batch signal or `LogPanel.append_batch()` path.
   - Flush UI logs every small time window or line batch.
   - Keep immediate flush for user-facing completion events.
   - Apply the same strategy to `LiveLogcatDialog._on_line()` by buffering incoming lines for 50-100 ms before `appendPlainText()`.

   Validation:

   - Spam 1,000 synthetic log lines and compare UI responsiveness.
   - Run live logcat for 30 seconds and verify Stop remains responsive.

   Implemented:

   - `LogService` now emits `logs_received` batches after each buffered flush while preserving the old `log_received` single-line compatibility signal.
   - `LogPanel` subscribes to the batch signal and appends a batch as one HTML edit block instead of repainting once per line.
   - `LogPanel` trims by stored entries after large batches and re-renders only when the visible log cap is exceeded.
   - `LiveLogcatDialog` buffers visible lines for 75 ms before one `appendPlainText()` call, so high-volume logcat streams leave more room for Stop/filter UI events.

   Local synthetic result:

```text
LogPanel._append_logs(1000 lines): one render pass, 1000 entries retained
LiveLogcatDialog._on_line(2 lines): zero immediate appends, one flush append
```

4. Remove double dispatch in app controller operations. Completed.

   Several `controllers/_app.py` actions call `self.executor.submit(self.app_model.*_async, ...)`. The model async method already schedules work on `QThreadPool`, so this adds a Python executor hop before the real Qt worker starts. It also makes some controller log emissions originate from a non-Qt worker thread.

   Target shape:

   - Emit immediate "queued/started" status in the controller.
   - Call model async methods directly from the Qt signal handler.
   - Keep `ThreadPoolExecutor` only for non-Qt background work such as device-store enrichment.

   Validation:

   - Install, batch install, uninstall, clear data, restart app, activity info, parse APK.
   - Confirm `[PERF] queue_ms` no longer includes the extra Python executor hop.

   Implemented:

   - `install_apk()`, `batch_install_apk()`, `uninstall_apk()`, `clear_app_data()`, `restart_app()`, `get_current_activity()`, and `parse_apk_info()` now call the model async APIs directly from the Qt signal handler.
   - The immediate "Start ..." operation log is still emitted before each model task is queued, preserving visible feedback.
   - The shared `ThreadPoolExecutor` remains available for non-model background work, but is no longer used as an extra hop before model `QThreadPool` tasks.

5. Use direct screenshot streaming. Completed.

   Current screenshot capture writes to `/sdcard`, checks the file, pulls it, then removes it. A direct `adb exec-out screencap -p` path can stream to the local PNG file in one subprocess. On the connected emulator this reduced capture from about 395 ms to about 230 ms.

   Implemented:

   - Added `CommandRunner.run_to_file()` for binary stdout streaming through the shared execution layer.
   - `ADBTesting.take_screenshot_async()` now prefers `adb exec-out screencap -p` and validates the PNG header.
   - If direct streaming fails or writes invalid PNG data, screenshot capture falls back to the previous temp-file + pull flow.

   Validation:

   - Screenshot button opens the viewer with a valid PNG.
   - Multi-device screenshots still collect all paths before opening the viewer.
   - Fallback path works when `exec-out` fails.

   Latest connected-emulator result:

```text
ADBTesting.take_screenshot_async direct/fallback: avg=273.1ms, min=262.6ms, max=289.2ms
```

### P2 Optimization Plan

1. Reuse the persistent input path outside Remote. Completed.

   The Remote panel already benefits from `ADBBridge.shell_input()`. Sidebar input buttons (`input_tap`, `input_swipe`, `input_keyevent`, `input_text`) still use per-command ADB process startup. Move these input-only operations behind a shared input service while keeping a fallback to `CommandRunner.run()`.

   Implemented:

   - `ADBAdvanced` now sends tap, swipe, keyevent, longpress, and drag input through `ADBBridge.shell_input()`.
   - `ADBBridge.shell_input()` keeps the existing persistent `adb shell` session and fallback process path, so the model layer does not call raw subprocess APIs.
   - The bridge is lazy-created to avoid import cycles and startup-time ADB path work.
   - `MainFrame.closeEvent()` closes the shared input sessions before shutting down the controller executor.

   Latest connected-emulator result:

```text
per-command input keyevent: avg=181.6ms, min=164.6ms, max=208.5ms
persistent shell input write: avg=0.01ms, min=0.00ms, max=0.03ms
```

2. Bulk-fill file explorer tables. Completed.

   `FileExplorerDialog._on_ls_result()` inserts one row at a time. For large directories, switch to `setRowCount(len(rows))`, set updates disabled while filling, and debounce search filtering. Keep sorting disabled until the batch is complete.

   Implemented:

   - `_on_ls_result()` now disables table updates and sorting during population.
   - Rows are preallocated with one `setRowCount()` call, including the optional parent `..` row.
   - Per-row cell assignment is isolated in `_set_file_row()`, and `insertRow()` is no longer used in the listing path.

3. Cap and externalize large shell output.

   `_process_run_shell_command_result()` currently logs full command output. Other diagnostics already cap to 1,000-2,000 chars. Apply a consistent output policy: show the first N lines/chars in the UI and save full output to a file when it exceeds the threshold.

4. Batch multi-command quick settings. Completed.

   `ADBSystemMixin.quick_setting_async()` runs three separate settings commands for animation toggles. Combine them into one shell command for lower latency and a single result.

   Implemented:

   - Animation quick settings now run as one `adb shell "<cmd> && <cmd> && <cmd>"`.
   - Single-command actions such as Stay Awake still use the same `_run()` execution boundary.

5. Debounce small UI refresh helpers.

   Device combobox rebuild and package-history updates are small today, but they are repeated after scans and package fetches. Keep the current correctness, but prefer diff updates when the device/package set is unchanged.

### P3 Optimization Plan

1. Add a reusable performance smoke script.

   Keep connected-device benchmarks repeatable without manual snippets: basic info, full device info, screenshot, package list, one dumpsys package, log append stress, and Remote/sidebar input.

2. Improve cancellation for long-running helpers.

   App Manager detail loading, file transfers, live logcat, Monkey, and email polling all run off the UI thread, but should expose consistent cancellation and final-state logging.

3. Normalize large-data dialogs.

   Use the same rendering rules for screenshot viewer, text viewer, shell output, and live logcat: lazy loading where possible, bounded visible buffers, and export for full data.

4. Keep architecture boundaries stable.

   The existing rule remains: UI owns widgets and user intent, models/services own ADB/process behavior, and shared process access stays in `CommandRunner`, `ProcessRunner`, or a narrow service such as the Remote input session.

### Foreground Package And Shutdown Fixes On 2026-05-31

Observed issue:

```text
[PERF] get_current_package total=1575.5ms queue=0.1ms model=1574.7ms signal=0.2ms ui=0.6ms
```

Root cause:

- `detect_current_package()` tried `dumpsys window | grep ...` first. On the connected emulator this command alone was about 1.6 seconds, so the delay was in model execution, not Qt signal delivery or UI rendering.
- Long-running processes were split across several owners (`ADBTesting`, `ADBAdvanced`, Remote scrcpy, File Explorer workers). Most paths had local cleanup, but the main-window exit path did not have one final process-level fallback.

Implemented:

- `detect_current_package()` now tries `cmd activity stack list` first and parses `visible=true topActivity=ComponentInfo{...}` before falling back to heavier `dumpsys` paths.
- `ADBTesting.shutdown()` stops managed Monkey/logcat processes.
- `ADBAdvanced.shutdown()` stops recording processes and closes persistent input shell sessions.
- `_ADBControllerBase.shutdown()` calls model shutdown hooks, stops all globally tracked `ProcessRunner.start()` processes, then shuts down the controller executor.
- `MainFrame.closeEvent()` now uses controller shutdown instead of manually stopping only the executor/input session.
- `RemotePanel.closeEvent()` now stops a running scrcpy process before shutting down its input executor.
- `ProcessRunner` now keeps a global registry for processes created through `start()` and exposes `stop_all_tracked()` as an application-exit fallback. `spawn()` remains untracked for external tools such as CMD or file explorer windows.
- App Manager detail/restore workers now respect abort requests inside longer loops.

Latest connected-emulator result:

```text
get_current_package: avg=86.1ms, min=79.4ms, max=99.0ms
```
