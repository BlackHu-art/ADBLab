# Model Execution A1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize and speed up ADB model command execution while preserving all existing controller/dialog method names and Qt signal payloads.

**Architecture:** Keep `ADBDevice`, `ADBApp`, `ADBTesting`, `ADBAdvanced`, `AppManagerWorker`, and `file_explorer_worker` public APIs intact. Move repeated command execution and current-package detection into focused model/base helpers so Windows adb path resolution, process lifecycle, timeout behavior, and parsing are consistent.

**Tech Stack:** Python 3.10+, PySide6, pytest, ruff, existing `CommandRunner`, `ProcessRunner`, and `@async_command` infrastructure.

---

## File Structure

- Modify: `models/base/process_runner.py` — owns all long-lived `subprocess.Popen` process lifecycle; must not deadlock and must resolve `adb` path.
- Create: `models/base/focus_detector.py` — pure helper for current foreground package detection; no Qt dependency.
- Modify: `models/adb_app.py` — keep async methods, delegate current package lookup and remaining app commands to unified helpers.
- Modify: `models/adb_testing.py` — reuse focus detector in Monkey monitor and remove unstable `shell=True` path.
- Modify: `models/file_explorer_worker.py` — route short commands through `CommandRunner` and transfer process path resolution through `adb_path` without changing worker signals.
- Modify: `tests/test_model_execution.py` — regression tests for process lifecycle, current package detection, and app model command routing.

---

### Task 1: Lock down ProcessRunner behavior

**Files:**
- Modify: `models/base/process_runner.py`
- Test: `tests/test_model_execution.py`

- [ ] **Step 1: Write failing tests for process start and stop_all deadlocks**

Add these tests to `tests/test_model_execution.py`:

```python
import threading
from unittest.mock import Mock, patch

from models.base.process_runner import ProcessRunner


def test_process_runner_start_replaces_existing_process_without_deadlock():
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    new_proc = Mock()
    runner._procs["device_logcat"] = old_proc

    started = []

    def start_process():
        with patch("models.base.process_runner.subprocess.Popen", return_value=new_proc):
            started.append(runner.start("device_logcat", ["adb", "logcat"]))

    thread = threading.Thread(target=start_process, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert started == [new_proc]
    old_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc


def test_process_runner_stop_all_without_deadlock():
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    runner._procs["device_logcat"] = old_proc

    thread = threading.Thread(target=runner.stop_all, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    old_proc.terminate.assert_called_once()
    assert runner._procs == {}
```

- [ ] **Step 2: Run tests to verify they fail on the old implementation**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_process_runner_start_replaces_existing_process_without_deadlock tests/test_model_execution.py::test_process_runner_stop_all_without_deadlock -v
```

Expected: FAIL because the worker thread remains alive due to lock re-entry.

- [ ] **Step 3: Implement minimal ProcessRunner fix**

Change `models/base/process_runner.py` so `start()` and `stop_all()` do not call `stop()` while holding `_lock`, and resolve `adb` before `Popen`:

```python
import subprocess
import threading

from utils.adb_resolver import adb_path

from .command_runner import CF


class ProcessRunner:
    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(self, key: str, cmd: list[str], stdout=None, stderr=None) -> subprocess.Popen:
        self.stop(key)
        stdout = stdout or subprocess.DEVNULL
        stderr = stderr or subprocess.DEVNULL
        proc = subprocess.Popen(self._resolve_cmd(cmd), stdout=stdout, stderr=stderr, creationflags=CF)
        with self._lock:
            self._procs[key] = proc
        return proc

    def stop(self, key: str, timeout: float = 5.0) -> int | None:
        with self._lock:
            proc = self._procs.pop(key, None)
        if proc is None:
            return None
        if proc.poll() is not None:
            return proc.returncode
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return proc.returncode

    def poll(self, key: str) -> int | None:
        with self._lock:
            proc = self._procs.get(key)
        if proc is None:
            return None
        return proc.poll()

    @staticmethod
    def _resolve_cmd(cmd: list[str]) -> list[str]:
        resolved = list(cmd)
        if resolved and resolved[0] == "adb":
            resolved[0] = adb_path()
        return resolved

    @property
    def active_keys(self) -> list[str]:
        with self._lock:
            return [key for key, proc in self._procs.items() if proc.poll() is None]

    def stop_all(self):
        with self._lock:
            keys = list(self._procs.keys())
        for key in keys:
            self.stop(key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_process_runner_start_replaces_existing_process_without_deadlock tests/test_model_execution.py::test_process_runner_stop_all_without_deadlock -v
```

Expected: PASS.

---

### Task 2: Extract foreground package detection helper

**Files:**
- Create: `models/base/focus_detector.py`
- Modify: `tests/test_model_execution.py`

- [ ] **Step 1: Write failing tests for parsing and command fallback**

Add to `tests/test_model_execution.py`:

```python
from unittest.mock import Mock

from models.base.command_runner import CommandResult
from models.base.focus_detector import detect_current_package, extract_package_name


def test_extract_package_name_ignores_log_prefix_and_returns_real_package():
    output = "ACTIVITY Sys2038: com.example.app/.MainActivity pid=123"

    assert extract_package_name(output) == "com.example.app"


def test_detect_current_package_uses_fast_activity_top_first():
    runner = Mock()
    runner.run.return_value = CommandResult(
        success=True,
        output="ACTIVITY com.example.app/.MainActivity pid=123",
    )

    result = detect_current_package("device-1", runner=runner)

    assert result == {
        "success": True,
        "device_ip": "device-1",
        "package_name": "com.example.app",
    }
    runner.run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "dumpsys", "activity", "top"],
        timeout=5,
    )


def test_detect_current_package_falls_back_to_window_focus():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output=""),
        CommandResult(success=True, output="mCurrentFocus=Window{u0 com.example.app/.MainActivity}"),
    ]

    result = detect_current_package("device-1", runner=runner)

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    assert runner.run.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail before helper exists**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_extract_package_name_ignores_log_prefix_and_returns_real_package tests/test_model_execution.py::test_detect_current_package_uses_fast_activity_top_first tests/test_model_execution.py::test_detect_current_package_falls_back_to_window_focus -v
```

Expected: FAIL with import error for `models.base.focus_detector`.

- [ ] **Step 3: Create `models/base/focus_detector.py`**

Create this file:

```python
import re

from .command_runner import CommandRunner

_PACKAGE_RE = re.compile(r"([\w.]+(?:\.[\w.]+)+)/")


def extract_package_name(output: str) -> str:
    for line in output.splitlines():
        if "/" not in line:
            continue
        match = _PACKAGE_RE.search(line)
        if match:
            return match.group(1)
    return ""


def detect_current_package(device_ip: str, runner=CommandRunner) -> dict:
    commands = [
        ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "top"],
        ["adb", "-s", device_ip, "shell", "sh", "-c", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"],
        ["adb", "-s", device_ip, "shell", "dumpsys", "window"],
    ]
    for command in commands:
        result = runner.run(command, timeout=5)
        if not result.success:
            continue
        package_name = extract_package_name(result.output)
        if package_name:
            return {"success": True, "device_ip": device_ip, "package_name": package_name}
    return {"success": False, "device_ip": device_ip, "error": "No focus info found"}
```

- [ ] **Step 4: Run tests to verify helper passes**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_extract_package_name_ignores_log_prefix_and_returns_real_package tests/test_model_execution.py::test_detect_current_package_uses_fast_activity_top_first tests/test_model_execution.py::test_detect_current_package_falls_back_to_window_focus -v
```

Expected: PASS.

---

### Task 3: Route ADBApp through helper and unified execution

**Files:**
- Modify: `models/adb_app.py`
- Modify: `tests/test_model_execution.py`

- [ ] **Step 1: Write failing tests for ADBApp public behavior**

Add to `tests/test_model_execution.py`:

```python
from unittest.mock import patch

from models.adb_app import ADBApp
from models.base.command_runner import CommandResult


def test_get_current_package_uses_shared_detector():
    model = ADBApp()

    with patch("models.adb_app.detect_current_package") as detect:
        detect.return_value = {"success": True, "device_ip": "device-1", "package_name": "com.example.app"}

        result = model.get_current_package("device-1")

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    detect.assert_called_once_with("device-1")


def test_install_apk_uses_run_helper_and_preserves_result_fields():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "Success",
            "device_ip": "device-1",
            "apk_path": "demo.apk",
            "index": 1,
            "apk_name": "demo.apk",
        }

        result = model.install_apk("device-1", "demo.apk", "demo.apk", 1)

    assert result["success"] is True
    assert result["apk_name"] == "demo.apk"
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "install", "-r", "demo.apk"],
        timeout=120,
        device_ip="device-1",
        apk_path="demo.apk",
        index=1,
        apk_name="demo.apk",
    )


def test_list_installed_packages_parses_command_output():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "package:com.example.one\npackage:com.example.two\n",
            "device_ip": "device-1",
        }

        result = model.list_installed_packages("device-1", 3)

    assert result == {
        "device_ip": "device-1",
        "success": True,
        "packages": ["com.example.one", "com.example.two"],
        "index": 3,
    }
```

- [ ] **Step 2: Run tests to verify they fail before sync wrappers/helper routing exist**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_get_current_package_uses_shared_detector tests/test_model_execution.py::test_install_apk_uses_run_helper_and_preserves_result_fields tests/test_model_execution.py::test_list_installed_packages_parses_command_output -v
```

Expected: FAIL because `detect_current_package` is not imported or sync wrappers do not exist.

- [ ] **Step 3: Modify `models/adb_app.py`**

Use this structure for app commands:

```python
from .adb_model import ADBModelCore, async_command
from .base.focus_detector import detect_current_package


class ADBApp(ADBModelCore):
    def get_current_package(self, device_ip: str) -> dict:
        return detect_current_package(device_ip)

    @async_command
    def get_current_package_async(self, device_ip: str) -> dict:
        return self.get_current_package(device_ip)

    def install_apk(self, device_ip: str, apk_path: str, apk_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "install", "-r", apk_path],
            timeout=120,
            device_ip=device_ip,
            apk_path=apk_path,
            index=idx,
            apk_name=apk_name,
        )

    @async_command
    def install_apk_async(self, device_ip: str, apk_path: str, apk_name: str, idx: int):
        return self.install_apk(device_ip, apk_path, apk_name, idx)

    def uninstall_app(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "uninstall", package_name],
            timeout=30,
            device_ip=device_ip,
            package_name=package_name,
            index=idx,
        )

    @async_command
    def uninstall_app_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self.uninstall_app(device_ip, package_name, idx)

    def list_installed_packages(self, device_ip: str, index: int) -> dict:
        result = self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "packages"],
            device_ip=device_ip,
        )
        if not result["success"]:
            return {"device_ip": device_ip, "success": False, "message": result["error"], "index": index}
        packages = [
            line.replace("package:", "").strip()
            for line in result["output"].splitlines()
            if line.startswith("package:")
        ]
        return {"device_ip": device_ip, "success": True, "packages": packages, "index": index}

    @async_command
    def list_installed_packages_async(self, device_ip: str, index: int) -> dict:
        return self.list_installed_packages(device_ip, index)
```

Keep existing methods not shown here (`clear_app_data_async`, `restart_app_async`, `get_current_activity_async`, `parse_apk_info_async`, `input_text_async`) unless they are already using `_run()`.

- [ ] **Step 4: Run ADBApp tests**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_get_current_package_uses_shared_detector tests/test_model_execution.py::test_install_apk_uses_run_helper_and_preserves_result_fields tests/test_model_execution.py::test_list_installed_packages_parses_command_output -v
```

Expected: PASS.

---

### Task 4: Reuse focus detector inside Monkey monitoring

**Files:**
- Modify: `models/adb_testing.py`
- Modify: `tests/test_model_execution.py`

- [ ] **Step 1: Write failing test for Monkey monitor package helper**

Add to `tests/test_model_execution.py`:

```python
from unittest.mock import patch

from models.adb_testing import ADBTesting


def test_testing_model_current_package_uses_shared_detector():
    model = ADBTesting()

    with patch("models.adb_testing.detect_current_package") as detect:
        detect.return_value = {"success": True, "device_ip": "device-1", "package_name": "com.example.app"}

        package_name = model._get_current_package("device-1")

    assert package_name == "com.example.app"
    detect.assert_called_once_with("device-1")
```

- [ ] **Step 2: Run test to verify it fails before helper exists**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_testing_model_current_package_uses_shared_detector -v
```

Expected: FAIL because `_get_current_package` does not exist or does not call shared detector.

- [ ] **Step 3: Modify `models/adb_testing.py` imports and helper**

Add import:

```python
from .base.focus_detector import detect_current_package
```

Add method inside `ADBTesting`:

```python
    def _get_current_package(self, device_ip: str) -> str:
        result = detect_current_package(device_ip)
        if result.get("success"):
            return result.get("package_name", "")
        return ""
```

- [ ] **Step 4: Replace repeated Monkey monitor detection block**

Inside `run_monkey_test_async`, replace the long block that runs `dumpsys activity top`, `dumpsys window | grep`, and full `dumpsys window` with:

```python
                    current_app = self._get_current_package(device_ip)
```

Keep the existing off-target recovery logic unchanged.

- [ ] **Step 5: Run Monkey helper test**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_testing_model_current_package_uses_shared_detector -v
```

Expected: PASS.

---

### Task 5: Move file explorer short commands onto CommandRunner

**Files:**
- Modify: `models/file_explorer_worker.py`
- Modify: `tests/test_model_execution.py`

- [ ] **Step 1: Write failing test for ADBWorker command routing**

Add to `tests/test_model_execution.py`:

```python
from unittest.mock import patch

from models.base.command_runner import CommandResult
from models.file_explorer_worker import ADBWorker


def test_file_explorer_worker_uses_command_runner_for_short_commands():
    worker = ADBWorker("device-1", ["shell", "ls", "/sdcard"])
    emitted = []
    worker.finished.connect(lambda output, failed: emitted.append((output, failed)))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="Download\nPictures")

        worker.run()

    assert emitted == [("Download\nPictures", False)]
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "ls", "/sdcard"],
        timeout=30,
    )
```

- [ ] **Step 2: Run test to verify it fails before worker uses CommandRunner**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_file_explorer_worker_uses_command_runner_for_short_commands -v
```

Expected: FAIL because `CommandRunner` is not imported or not called.

- [ ] **Step 3: Modify `models/file_explorer_worker.py`**

Add imports:

```python
from models.base.command_runner import CommandRunner
from utils.adb_resolver import adb_path
```

In `ADBWorker.run`, replace direct `subprocess.check_output` with:

```python
    def run(self):
        cmd = ["adb", "-s", self.device_ip] + self.args
        result = CommandRunner.run(cmd, timeout=30)
        if self._aborted:
            return
        if result.success:
            self.finished.emit(result.output, False)
        else:
            self.finished.emit(result.error, True)
```

In `TransferWorker.run`, resolve adb before `Popen`:

```python
            cmd = [adb_path(), "-s", self.device_ip] + self.args
```

Keep the existing progress and finished signal behavior unchanged.

- [ ] **Step 4: Run file explorer worker test**

Run:

```bash
python -m pytest tests/test_model_execution.py::test_file_explorer_worker_uses_command_runner_for_short_commands -v
```

Expected: PASS.

---

### Task 6: Final verification for A1 scope

**Files:**
- Verify only changed files from Tasks 1-5.

- [ ] **Step 1: Run full model execution test file**

Run:

```bash
python -m pytest tests/test_model_execution.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run ruff on changed files**

Run:

```bash
python -m ruff check models/base/process_runner.py models/base/focus_detector.py models/adb_app.py models/adb_testing.py models/file_explorer_worker.py tests/test_model_execution.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Compile changed files**

Run:

```bash
python -m py_compile models/base/process_runner.py models/base/focus_detector.py models/adb_app.py models/adb_testing.py models/file_explorer_worker.py tests/test_model_execution.py
```

Expected: command exits with code 0 and no output.

- [ ] **Step 4: Inspect remaining direct subprocess usage**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in Path('models').rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    hits = [needle for needle in ('subprocess.run', 'subprocess.check_output', 'shell=True') if needle in text]
    if hits:
        print(path, hits)
PY
```

Expected: no `subprocess.run` or `subprocess.check_output` outside `models/base/command_runner.py`; no `shell=True` in `models/adb_testing.py`.

---

## Self-Review

- Spec coverage: The plan covers A1 execution stability, `adb_app.py` routing, `adb_testing.py` current package reuse and shell removal, and `file_explorer_worker.py` direct subprocess cleanup.
- Placeholder scan: No TBD/TODO placeholders are present; each task includes exact file paths, code, commands, and expected results.
- Type consistency: New helper functions are `extract_package_name` and `detect_current_package`; tests and implementation tasks use those exact names. Sync wrappers in `ADBApp` preserve existing async public methods.
