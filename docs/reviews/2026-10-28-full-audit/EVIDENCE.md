# 隔离探针证据

本文件仅保存审查用临时脚本的文本副本，没有把它们加入项目测试套件。断言描述预期契约，当前版本故意失败用于揭示缺陷；不得把这些结果称为修复验收。每次运行及退出码见 VALIDATION.md。所有命令在临时目录运行，路径和设备标记均为合成值。

## 验证脚本

### pytest_guard.py

```python
import sys, os, platform, subprocess
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root))
# Windows platform version discovery may invoke cmd /c ver; read before external-process guard.
platform.uname()
python_prefix=subprocess.list2cmdline([sys.executable])+" "
def audit(event,args):
    if event in {"socket.connect","os.system","os.startfile","os.startfile/2"}:
        raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:"+event)
    if event == "subprocess.Popen":
        executable=args[0]
        allowed=(executable is not None and Path(str(executable)).resolve() == Path(sys.executable).resolve())
        if executable is None and isinstance(args[1],str):
            allowed=args[1].startswith(python_prefix)
        if not allowed:
            raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
sys.addaudithook(audit)
import pytest
raise SystemExit(pytest.main(sys.argv[2:]))

```

### run_validation.py

```python
import sys, os, json, subprocess
from pathlib import Path
root=Path(r"S:\CodeSpaces\PyCharm\ADBLab")
tmp=Path(__file__).parent
name=sys.argv[1]
env=os.environ.copy()
env.update(PYTHONDONTWRITEBYTECODE="1",PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",QT_QPA_PLATFORM="offscreen",PYTHONPATH=str(root),LOCALAPPDATA=str(tmp/name/"local"),APPDATA=str(tmp/name/"roaming"),USERPROFILE=str(tmp/name/"home"),XDG_CONFIG_HOME=str(tmp/name/"config"),XDG_CACHE_HOME=str(tmp/name/"cache"),TMP=str(tmp/name/"tmp"),TEMP=str(tmp/name/"tmp"))
for key in ("LOCALAPPDATA","APPDATA","USERPROFILE","XDG_CONFIG_HOME","XDG_CACHE_HOME","TMP"):Path(env[key]).mkdir(parents=True,exist_ok=True)
cmd=[sys.executable,"-B",str(tmp/"pytest_guard.py"),str(root),"-q","-p","no:cacheprovider","--basetemp",str(tmp/name/"pytest"),*sys.argv[2:]]
r=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace")
log=tmp/(name+".log");log.write_text(r.stdout+r.stderr,encoding="utf-8")
records=json.loads((tmp/"validation.json").read_text());records.append(dict(name=name,command=cmd,exit_code=r.returncode,log=str(log),isolation="temporary profile/cache/data; Qt offscreen; no pytest/bytecode cache; audit hook blocks network and non-Python subprocess"));(tmp/"validation.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
print(r.stdout+r.stderr);print("EXIT_CODE",r.returncode)

```

### test_audit_archive_roundtrip.py

```python
from pathlib import Path
from types import SimpleNamespace
import io, zipfile
from services.apps.archives import backup_app,restore_apps

def test_successful_backup_meets_restore_acceptance(tmp_path):
    content=io.BytesIO()
    with zipfile.ZipFile(content,"w",compression=zipfile.ZIP_STORED) as apk:
        apk.writestr("AndroidManifest.xml",b"synthetic manifest")
        apk.writestr("assets/padding.bin",b"x"*(2*1024*1024))
    events=[]; installs=[]
    def execute(*args,**kwargs):
        if args[0]=="shell":return SimpleNamespace(success=True,stdout="package:/data/app/synthetic/base.apk",error="")
        if args[0]=="pull":
            (Path(args[2])/"base.apk").write_bytes(content.getvalue())
            return SimpleNamespace(success=True,error="")
        installs.append(args)
        return SimpleNamespace(success=True,error="")
    callbacks=dict(log=lambda s:events.append(("log",s)),feedback=lambda *a:events.append(a),failure=lambda s:events.append(("failure",s)),completed=lambda s:events.append(("done",s)))
    backup_app("org.example.synthetic",str(tmp_path),0,execute=execute,cancelled=lambda:False,progress=lambda *a:None,**callbacks)
    archive=tmp_path/"backup_org.example.synthetic.zip"
    assert ("done","backup") in events and archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        item=zf.getinfo("base.apk")
        print("archive_bytes",archive.stat().st_size,"member_bytes",item.file_size,"ratio",item.file_size//item.compress_size)
    restore_apps([str(archive)],execute=execute,cancelled=lambda:False,confirm_user=lambda:0,**callbacks)
    print("events",events,"install_calls",len(installs))
    assert ("done","restore") in events,"successful local backup was rejected before any install"

```

### test_audit_data_handoff.py

```python
import hashlib
import io
import subprocess
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
import yaml


@pytest.mark.parametrize('user', ['u0', 'u10'])
def test_focus_activity_accepts_secondary_android_user(user):
    from mobileperf.android.tools.androiddevice import ADB
    device = ADB.__new__(ADB)
    device.run_shell_cmd = lambda _: f'mCurrentFocus=Window{{abc {user} com.example.app/.MainActivity}}'
    assert device.get_focus_activity() == 'com.example.app/.MainActivity'


def test_unread_unbacked_device_history_survives_next_save(tmp_path, monkeypatch):
    import models.device_store as mod
    store = mod.DeviceStore
    path = tmp_path / 'connected_devices.yaml'
    original = {'old': {'ip': '192.0.2.1:5555', 'Brand': 'fixture', 'Model': 'old'}}
    path.write_text(yaml.safe_dump(original), encoding='utf-8')
    monkeypatch.setattr(store, '_file_path', str(path))
    monkeypatch.setattr(store, '_legacy_file_path', str(tmp_path / 'absent.yaml'))
    monkeypatch.setattr(store, '_devices', {})
    monkeypatch.setattr(store, '_LOAD_RETRY_DELAY_S', 0)
    monkeypatch.setattr(store, '_note_load_failure', lambda _: None)
    def denied(*args, **kwargs):
        raise PermissionError('injected transient read/backup failure')
    with monkeypatch.context() as blocked:
        blocked.setattr(mod, 'open', denied, raising=False)
        blocked.setattr(mod.shutil, 'copy2', denied)
        store.load()
    assert store.get_all() == []
    assert not list(tmp_path.glob('*.corrupt-*'))
    assert yaml.safe_load(path.read_text(encoding='utf-8')) == original
    store.add_device('new', '192.0.2.2:5555')
    actual = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert 'old' in actual, actual


def test_failed_handoff_keeps_live_helper_ownership(tmp_path, monkeypatch):
    import core.installer_handoff as mod
    @dataclass
    class Asset:
        name: str = 'synthetic-setup.exe'
    verified = SimpleNamespace(path=tmp_path / 'synthetic-setup.exe', asset=Asset())
    source = tmp_path / 'synthetic-helper.exe'
    source.write_bytes(b'not executable; probe fixture only')
    class Parent:
        created = 1
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Helper:
        stdin = io.BytesIO()
        stdout = io.BytesIO()
        def poll(self): return None
        def wait(self, timeout):
            raise subprocess.TimeoutExpired('synthetic-helper', timeout)
    helper = Helper()
    handoff = mod.InstallerHandoff()
    monkeypatch.setattr(mod, 'verify_download', lambda *a, **kw: verified)
    monkeypatch.setattr(mod, 'ParentProcess', Parent)
    monkeypatch.setattr(mod, 'validate_request', lambda _: None)
    monkeypatch.setattr(mod, 'locked_file', lambda p: p.open('rb'))
    monkeypatch.setattr(mod, 'child_environment', lambda: {})
    monkeypatch.setattr(handoff, '_helper_source', lambda: (source, hashlib.sha256(source.read_bytes()).hexdigest()))
    monkeypatch.setattr(mod.subprocess, 'Popen', lambda *a, **kw: helper)
    def fail_handshake(*a, **kw):
        raise TimeoutError('injected handshake timeout')
    monkeypatch.setattr(mod, 'read_pipe_line', fail_handshake)
    with pytest.raises(TimeoutError, match='injected'):
        handoff.prepare(verified)
    retained = handoff._process is helper
    refused_retry = False
    try:
        handoff.reset_attempt()
    except RuntimeError:
        refused_retry = True
    assert retained and refused_retry, {'retained': retained, 'refused_retry': refused_retry, 'alive': helper.poll() is None}

```

### test_audit_display_ci.py

```python
import pytest

@pytest.mark.ui
def test_partial_monkey_completion_refreshes_visible_count(qt_application,monkeypatch,isolated_app_settings):
    from tests.test_responsive_panels import _show_feature_panel,_close_feature_panel
    owner,apps,_,_=_show_feature_panel('apps',960,12,qt_application,monkeypatch)
    try:
        apps._monkey_active_devices=('synthetic-a','synthetic-b')
        apps._monkey_pending_devices=set(apps._monkey_active_devices)
        apps._monkey_pending_count=2
        apps._monkey_batch_id='synthetic-batch'
        apps._set_monkey_running(True)
        assert apps.monkey_run_status.text()=='正在运行 · 2 台设备'
        apps.on_monkey_target_finished('synthetic-batch','synthetic-a')
        assert apps._monkey_active_devices==('synthetic-b',)
        assert apps.monkey_run_status.text()=='正在运行 · 1 台设备'
    finally:
        _close_feature_panel(owner)


def test_action_pin_gate_rejects_uncommented_unpinned_action(tmp_path,monkeypatch):
    from tests import test_ci_contracts as contracts
    sha,version=contracts.PINNED_ACTIONS['actions/checkout']
    fixture=(
        'name: synthetic\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n'
        f'      - name: pinned\n        uses: actions/checkout@{sha} # {version}\n'
        '      - name: unpinned\n        uses: actions/setup-python@main\n'
    )
    (tmp_path/'fixture.yaml').write_text(fixture,encoding='utf-8')
    monkeypatch.setattr(contracts,'WORKFLOW_DIR',tmp_path)
    with pytest.raises(AssertionError):
        contracts.test_all_actions_are_pinned_to_verified_commit_shas()

```

### test_audit_logcat_dialog.py

```python
import pytest
from PySide6.QtCore import QObject, Signal
from gui.features.logcat.page import LiveLogcatPage
from gui.features.logcat import stream
from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor
pytestmark=pytest.mark.ui

def test_close_inside_save_dialog_does_not_start_export(qt_application, monkeypatch, tmp_path):
    page=LiveLogcatPage(device_ip="synthetic",task_supervisor=FakeQtTaskSupervisor())
    starts=[]
    class FakeExport(QObject):
        completed=Signal(bool,str)
        finished=Signal()
        def __init__(self,text,path,parent=None): super().__init__(parent)
        def start(self): starts.append(True)
        def isRunning(self): return False
    monkeypatch.setattr(stream,"LogcatExportWorker",FakeExport)
    def choose(*a,**k):
        assert page.request_dispose()
        assert page._close_ready
        return str(tmp_path/"output.txt"),""
    monkeypatch.setattr(stream.QFileDialog,"getSaveFileName",choose)
    try:
        page._export()
        print("page_closed",page._closing,"dispose_emitted",page._dispose_emitted,"new_exports",len(starts))
        assert not starts,"export was admitted after disposal"
    finally:
        page._stream_controller._export_worker=None
        page._stream_controller._export_in_progress=False
        page.close()
        page.deleteLater()

```

### test_audit_logcat_shutdown.py

```python
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from shiboken6 import isValid

from gui.features import FeatureSessionKey, FeatureSessionRegistry
from gui.features.logcat import LiveLogcatPage
from tests.test_phase2_mainframe_shutdown_gate import _frame, _bind_settings_finalizer, _drive_until, CloseEvent

pytestmark = pytest.mark.ui


def test_application_close_waits_for_logcat_export(qt_application, isolated_app_settings):
    frame = _frame(lambda: None)
    registry = FeatureSessionRegistry()
    key = FeatureSessionKey('logcat', 'synthetic')
    page, _ = registry.get_or_create(key, lambda _: LiveLogcatPage(device_ip='synthetic', task_supervisor=frame.task_supervisor))
    class Export(QThread):
        def __init__(self):
            super().__init__(page)
            self.entered = threading.Event()
            self.release = threading.Event()
        def run(self):
            self.entered.set()
            self.release.wait(10)
    worker = Export()
    stream = page._stream_controller
    stream._export_worker = worker
    stream._export_in_progress = True
    worker.finished.connect(stream._on_export_finished)
    frame._workspace_feature_hosts = {'logcat': SimpleNamespace(
        registry=registry,
        register_shutdown_tasks=registry.register_shutdown_tasks,
        shutdown=lambda: registry.request_dispose_all('application_shutdown'),
    )}
    _bind_settings_finalizer(frame, SimpleNamespace(close=lambda: True))
    try:
        worker.start()
        assert worker.entered.wait(1)
        frame.closeEvent(CloseEvent())
        _drive_until(qt_application, lambda: frame._close_ready, frame=frame)
        actual = {'frame_close_ready': frame._close_ready,
                  'export_running': worker.isRunning(),
                  'page_disposing': registry.is_disposing(key),
                  'supervised_active': frame.task_supervisor.supervisor.active_count}
        assert not (frame._close_ready and worker.isRunning()), actual
    finally:
        worker.release.set()
        worker.wait(2000)
        frame.task_supervisor._pool.waitForDone(2000)
        for _ in range(5):
            qt_application.processEvents()
        if isValid(page):
            page.close()
            page.deleteLater()

```

### test_audit_native_cleanup.py

```python
import io, subprocess
from core import native_process
from core import exec as execution
class StubbornClient:
    def __init__(self):
        self.stdin=io.BytesIO(); self.stdout=io.BytesIO(); self.stderr=io.BytesIO(); self.killed=False
    def poll(self): return None
    def kill(self): self.killed=True
    def wait(self,timeout=None): raise subprocess.TimeoutExpired("synthetic",timeout)
    def communicate(self,input=None,timeout=None): raise subprocess.TimeoutExpired("synthetic",timeout)
def test_default_native_path_retains_unreleased_client(monkeypatch):
    process=StubbornClient()
    monkeypatch.setattr(native_process,"popen_native",lambda *a,**k:process)
    monkeypatch.setattr(execution,"_adb_runtime",None)
    monkeypatch.setattr(execution,"_log_if_slow",lambda *a,**k:None)
    result=execution.CommandRunner.run(["synthetic-audit-client"],timeout=.01)
    assert result.outcome == "failed"
    assert process.killed and process.poll() is None
    count=execution.CommandRunner.active_count()
    idle=execution.CommandRunner.wait_for_idle(0)
    print("observed",result.outcome,"still_alive",process.poll() is None,"active_count",count,"idle",idle)
    assert count > 0 and not idle, "live client cleanup obligation was lost"

```

### test_audit_numeric_locale.py

```python
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QLineEdit
from gui.panels.base_panel import BasePanel
from utils.adb_values import normalize_geo_coordinate, normalize_tcp_port

pytestmark = pytest.mark.ui

@pytest.mark.parametrize('locale,text,kind', [('de_DE','12,5','float'),('en_US','5,555','int')])
def test_accepted_numeric_input_can_cross_business_boundary(qt_application,locale,text,kind):
    previous=QLocale()
    QLocale.setDefault(QLocale(locale))
    field=None
    try:
        holder=SimpleNamespace(_in=lambda *a:QLineEdit())
        if kind=='float':
            field=BasePanel._in_float(holder,'synthetic',-90,90)
            normalize=lambda value:normalize_geo_coordinate(value,minimum=Decimal(-90),maximum=Decimal(90))
        else:
            field=BasePanel._in_int(holder,'synthetic',1,65535)
            normalize=normalize_tcp_port
        field.setText(text)
        assert field.hasAcceptableInput(), 'probe did not meet trigger'
        normalize(field.text())
    finally:
        if field is not None: field.deleteLater()
        QLocale.setDefault(previous)

```

### test_audit_supervisor.py

```python
from core.tasks.supervision import TaskSupervisor, StopDisposition
import pytest
@pytest.mark.parametrize("mode", ["single", "owner", "all"])
def test_completed_cleanup_error_is_not_success(mode):
    supervisor = TaskSupervisor()
    supervisor.register("cleanup", owner_id="owner", kind="shutdown", request_stop=lambda: None, wait=lambda _: True, is_running=lambda: False, error_type=lambda: "OSError")
    if mode == "single":
        result = supervisor.stop("cleanup", graceful_timeout=0, force_timeout=0)
    elif mode == "owner":
        result = supervisor.stop_owner("owner", deadline=0)[0]
    else:
        result = supervisor.stop_all(deadline=0)[0]
    assert result.disposition is StopDisposition.FAILED, result
    assert result.error_type == "OSError"

```

### test_audit_test_isolation.py

```python
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QThreadPool

pytestmark=pytest.mark.ui

def test_existing_projection_test_does_not_probe_machine_clients(monkeypatch,tmp_path,qt_application,isolated_app_settings):
    import tests.test_qt_adb_runtime as original
    import gui.widgets.adb_client_card as cards
    import services.adb_clients as clients
    from utils.adb_resolver import AdbCandidate
    path=tmp_path/'synthetic-client.exe'
    path.write_bytes(b'not executable')
    monkeypatch.setattr(cards,'list_adb_candidates',lambda *a,**kw:[AdbCandidate('bundled',str(path))])
    monkeypatch.setattr(cards,'resolve_adb_program',lambda *a,**kw:str(path))
    calls=[]
    def observe(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(success=True,output='Android Debug Bridge version 1.0.41\nVersion 1.0.0',error='')
    monkeypatch.setattr(clients.CommandRunner,'run',observe)
    pages=[]
    real_page=original.SettingsPage
    def page(*a,**kw):
        value=real_page(*a,**kw)
        pages.append(value)
        return value
    monkeypatch.setattr(original,'SettingsPage',page)
    try:
        original.test_main_frame_projects_initial_native_scope_without_selecting_manual_native(monkeypatch)
        QThreadPool.globalInstance().waitForDone(3000)
        assert calls==[], {'unexpected_external_probe_calls':calls}
    finally:
        for p in pages:
            p.prepare_shutdown()
        QThreadPool.globalInstance().waitForDone(3000)
        for _ in range(3):qt_application.processEvents()

```

## 失败输出摘录

### supervisor-probe

确认 F03：3 个断言失败，均是已失败结束任务被当作 ALREADY_STOPPED。

```text
>       assert result.disposition is StopDisposition.FAILED, result
E       AssertionError: TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='')
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  where <StopDisposition.ALREADY_STOPPED: 'already_stopped'> = TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='').disposition
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
>       assert result.disposition is StopDisposition.FAILED, result
E       AssertionError: TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='')
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  where <StopDisposition.ALREADY_STOPPED: 'already_stopped'> = TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='').disposition
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
>       assert result.disposition is StopDisposition.FAILED, result
E       AssertionError: TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='')
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  where <StopDisposition.ALREADY_STOPPED: 'already_stopped'> = TaskStopResult(task_id='cleanup', owner_id='owner', disposition=<StopDisposition.ALREADY_STOPPED: 'already_stopped'>, error_type='').disposition
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
FAILED ::test_completed_cleanup_error_is_not_success[single] - AssertionError...
FAILED ::test_completed_cleanup_error_is_not_success[owner] - AssertionError:...
FAILED ::test_completed_cleanup_error_is_not_success[all] - AssertionError: T...
```

### r1-direct

受阻／验证脚本错误：93 passed、1 failed、10 errors。临时审计钩子误拦 platform.uname 的 cmd /c ver，并未接受 Windows executable=None 的受控 Python 子进程。不是项目缺陷结论。

```text
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>           request.getfixturevalue("isolated_qt_run_library_storage")
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
>       result = subprocess.run(
>               raise RuntimeError("AUDIT_BOUNDARY_BLOCKED:external_process")
E               RuntimeError: AUDIT_BOUNDARY_BLOCKED:external_process
FAILED tests/test_device_context.py::test_device_context_imports_without_gui_or_services
ERROR tests/test_action_results.py::test_async_model_preserves_action_identity_and_original_operation_protocol
ERROR tests/test_action_results.py::test_native_screenshot_partial_batch_keeps_last_successful_unit_successful
ERROR tests/test_action_results.py::test_model_submission_error_ends_action_without_leaving_a_running_job
ERROR tests/test_action_results.py::test_automatic_recording_pull_creates_one_media_result_per_device
ERROR tests/test_phase1_operations.py::test_async_command_keeps_signal_signature_and_strips_reserved_operation_kwargs
ERROR tests/test_phase1_operations.py::test_async_command_carries_manager_generation_without_forwarding_it_to_model_method
ERROR tests/test_phase1_operations.py::test_async_command_carries_owner_token_without_forwarding_it_to_model_method
ERROR tests/test_phase1_operations.py::test_async_command_reports_business_runtime_error_with_same_operation_metadata
ERROR tests/test_phase1_operations.py::test_async_command_long_running_routes_to_long_pool
ERROR tests/test_phase1_operations.py::test_command_task_runs_in_real_thread_pool_and_emits_finished
```

### native-cleanup-probe

确认 F02：1 failed；failed/still_alive=True/active_count=0/idle=True。

```text
>       assert count > 0 and not idle, "live client cleanup obligation was lost"
E       AssertionError: live client cleanup obligation was lost
E       assert (0 > 0)
FAILED ::test_default_native_path_retains_unreleased_client - AssertionError:...
```

### logcat-dialog-probe

确认 F06：1 failed；关闭协议完成后启动一个新导出替身。

```text
>           assert not starts,"export was admitted after disposal"
E           AssertionError: export was admitted after disposal
E           assert not [True]
FAILED ::test_close_inside_save_dialog_does_not_start_export - AssertionError...
```

### archive-roundtrip-probe

确认 F08：1 failed；合成 APK 容器的备份成功、恢复安全策略拒绝。

```text
>       assert ("done","restore") in events,"successful local backup was rejected before any install"
E       AssertionError: successful local backup was rejected before any install
E       assert ('done', 'restore') in [('log', 'Backup: C:\\Users\\57289\\AppData\\Local\\Temp\\adblab-audit-20261028-l20c86vm\\archive-roundtrip-probe\\pyt...icious'), ('log', 'Restore incomplete: 0 succeeded, 1 failed'), ('error', 'Restore incomplete: 0 succeeded, 1 failed')]
FAILED ::test_successful_backup_meets_restore_acceptance - AssertionError: su...
```

### data-handoff-probes

确认 F01/F04/F09：3 failed、1 passed；u0 是通过对照。

```text
>       assert device.get_focus_activity() == 'com.example.app/.MainActivity'
E       AssertionError: assert 'u10' == 'com.example.....MainActivity'
E
E         - com.example.app/.MainActivity
E         + u10
>       assert 'old' in actual, actual
E       AssertionError: {'new': {'Aversion': '', 'Brand': 'Unknown', 'Model': 'Unknown', 'ip': '192.0.2.2:5555'}}
E       assert 'old' in {'new': {'Aversion': '', 'Brand': 'Unknown', 'Model': 'Unknown', 'ip': '192.0.2.2:5555'}}
>       assert retained and refused_retry, {'retained': retained, 'refused_retry': refused_retry, 'alive': helper.poll() is None}
E       AssertionError: {'retained': False, 'refused_retry': False, 'alive': True}
E       assert (False)
FAILED ::test_focus_activity_accepts_secondary_android_user[u10] - AssertionE...
FAILED ::test_unread_unbacked_device_history_survives_next_save - AssertionEr...
FAILED ::test_failed_handoff_keeps_live_helper_ownership - AssertionError: {'...
```

### logcat-shutdown-probe

受阻／探针替身缺字段：1 failed，fake host 缺 registry。此轮不作为产品失败证据，finally 已释放并等待线程。

```text
>           _drive_until(qt_application, lambda: frame._close_ready, frame=frame)
>           for page in host.registry.pages():
E           AttributeError: 'types.SimpleNamespace' object has no attribute 'registry'
FAILED ::test_application_close_waits_for_logcat_export - AttributeError: 'ty...
```

### logcat-shutdown-probe-v2

补齐临时 host 后确认 F05：1 failed；close_ready=True、export_running=True、page_disposing=True、active_count=0。

```text
>           assert not (frame._close_ready and worker.isRunning()), actual
E           AssertionError: {'frame_close_ready': True, 'export_running': True, 'page_disposing': True, 'supervised_active': 0}
E           assert not (True and True)
E            +  where True = <[RuntimeError("'__init__' method of object's base class (MainFrame) not called.") raised in repr()] MainFrame object at 0x15df6049f80>._close_ready
E            +  and   True = <built-in method isRunning of Export object at 0x0000015DF71099C0>()
E            +    where <built-in method isRunning of Export object at 0x0000015DF71099C0> = <test_audit_logcat_shutdown.Export(0x15df6660ba0) at 0x0000015DF71099C0>.isRunning
FAILED ::test_application_close_waits_for_logcat_export - AssertionError: {'f...
```

### numeric-locale-probe

确认 F12：2 failed；de_DE 小数及 en_US 分组端口被 GUI 接受而后端拒绝。

```text
>           normalize(field.text())
>           raise ValueError("坐标必须是普通十进制数")
E           ValueError: 坐标必须是普通十进制数
>           normalize(field.text())
>           raise ValueError("端口必须是 ASCII 十进制整数")
E           ValueError: 端口必须是 ASCII 十进制整数
FAILED ::test_accepted_numeric_input_can_cross_business_boundary[de_DE-12,5-float]
FAILED ::test_accepted_numeric_input_can_cross_business_boundary[en_US-5,555-int]
```

### test-isolation-probe

确认 F14：1 failed；原测试受控包装，记录到不应有的 version 调用，未执行程序。

```text
>           assert calls==[], {'unexpected_external_probe_calls':calls}
E           AssertionError: {'unexpected_external_probe_calls': [['C:\\Users\\57289\\AppData\\Local\\Temp\\adblab-audit-20261028-l20c86vm\\test-isolation-probe\\pytest\\test_existing_projection_test_0\\synthetic-client.exe', 'version']]}
E           assert [['C:\\Users\...', 'version']] == []
E
E             Left contains one more item: ['C:\\Users\\57289\\AppData\\Local\\Temp\\adblab-audit-20261028-l20c86vm\\test-isolation-probe\\pytest\\test_existing_projection_test_0\\synthetic-client.exe', 'version']
E             Use -v to get more diff
FAILED ::test_existing_projection_test_does_not_probe_machine_clients - Asser...
```

### display-ci-probes

确认 F15/F16：2 failed；真实标签计数陈旧、合成不固定 Actions 引用被原门禁放行。

```text
>           assert apps.monkey_run_status.text()=='正在运行 · 1 台设备'
E           AssertionError: assert '正在运行 · 2 台设备' == '正在运行 · 1 台设备'
E
E             - 正在运行 · 1 台设备
E             ?        ^
E             + 正在运行 · 2 台设备
E             ?        ^
>       with pytest.raises(AssertionError):
E       Failed: DID NOT RAISE AssertionError
FAILED ::test_partial_monkey_completion_refreshes_visible_count - AssertionEr...
FAILED ::test_action_pin_gate_rejects_uncommented_unpinned_action - Failed: D...
```
