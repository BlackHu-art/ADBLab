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

Result:

```text
42 passed
```

## Deferred Items

- Runtime-local settings changes in `resources/app_settings.json` were intentionally not included in this optimization commit.
- Account/config changes in `core/mail/mail.yaml` were intentionally not included because they may contain environment-specific credentials.
- Further UI polish can continue from the current architecture without changing the execution-layer contract.
