"""审计发现的设备发现管道及跨线程设备快照竞态回归。"""

import threading
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.ui


def wait_ui(app, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(.002)
    return bool(predicate())


def test_device_scan_drains_pipes_before_waiting_for_exit(qt_application, monkeypatch):
    import subprocess
    import sys

    from core import exec as execution
    from gui.main_frame import _ScanThread

    output = 'List of devices attached\n' + ''.join(
        f'synthetic-device-{n:05d}\tdevice\n' for n in range(3000)
    )
    command = [sys.executable, '-B', '-c', (
        "import sys; sys.stderr.write('synthetic diagnostic\\n' * 10000); "
        "sys.stderr.flush(); sys.stdout.write('List of devices attached\\n' + "
        "''.join(f'synthetic-device-{n:05d}\\tdevice\\n' for n in range(3000))); "
        "sys.stdout.flush()"
    )]

    processes = []

    def spawn(_command, **kwargs):
        kwargs.pop('isolate', None)
        process = subprocess.Popen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(execution, 'resolve_command', lambda value: list(value))
    monkeypatch.setattr(execution, 'popen_native', spawn)
    monkeypatch.setattr(execution.ProcessRunner, '_global_procs', {})
    runner = execution.ProcessRunner()
    scan = _ScanThread()
    try:
        observed = scan._run_devices_scan(runner, deadline=time.monotonic() + 2)
        assert observed == output
        assert len(processes) == 1
        assert processes[0].returncode == 0
        assert processes[0].stdout.closed
        assert processes[0].stderr.closed
        assert runner.active_keys == []
        assert execution.ProcessRunner.tracked_active_count() == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)
        scan.deleteLater()


def test_old_overview_publication_cannot_overwrite_new_generation(qt_application, monkeypatch):
    from PySide6.QtCore import QObject, Qt, Slot

    from controllers.signals import ADBControllerSignals
    from gui.main_frame import MainFrame
    from tests.test_model_ci_controller import _device_metadata_controller
    controller = _device_metadata_controller()
    old_before_emit, release_old = threading.Event(), threading.Event()
    signals = ADBControllerSignals()
    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self._closing = False
            self.adb_controller = controller
            self._device_metadata = {}
            self.left_panel = SimpleNamespace(device_context_snapshot=lambda: SimpleNamespace(
                connected_devices=('device-1',),
            ))
            self.observed = []
        def _sync_device_metadata(self, *args, **kwargs):
            self.observed.append(self._device_metadata['device-1']['Model'])
        @Slot(str, dict)
        def receive(self, device, record):
            MainFrame._on_device_info_updated(self, device, record)
    receiver = Receiver()
    signals.device_info_updated.connect(receiver.receive, Qt.ConnectionType.QueuedConnection)
    def publish(device, record):
        if record.get('Model') == 'Old':
            old_before_emit.set()
            assert release_old.wait(2)
        signals.device_info_updated.emit(device, record)
    controller.signals.device_info_updated.emit = publish
    monkeypatch.setattr('controllers._device.DeviceStore.upsert_devices', lambda *_: None)
    monkeypatch.setattr(
        'controllers._device.ADBDevice.get_device_overview_info',
        lambda *_args, **kwargs: {'Model': 'Old'},
    )
    old_worker = new_worker = None
    try:
        controller._device_topology = ('device-1',)
        controller._async_update_devices(['device-1'], generation=1)
        old_worker = threading.Thread(target=controller.executor.submit.call_args.args[0])
        old_worker.start()
        assert old_before_emit.wait(1)
        monkeypatch.setattr(
            'controllers._device.ADBDevice.get_device_overview_info',
            lambda *_args, **kwargs: {'Model': 'New'},
        )
        controller._process_device_list([])
        controller._process_device_list(['device-1'])
        new_worker = threading.Thread(target=controller.executor.submit.call_args.args[0])
        new_worker.start()
        new_worker.join(1)
        assert not new_worker.is_alive()
        assert wait_ui(qt_application, lambda: receiver.observed == ['New'])
        release_old.set()
        old_worker.join(1)
        assert not old_worker.is_alive()
        qt_application.processEvents()
        assert receiver.observed == ['New']
    finally:
        release_old.set()
        for thread in (old_worker, new_worker):
            if thread is not None:
                thread.join(2)
                assert not thread.is_alive()
        receiver.deleteLater()
        signals.deleteLater()


@pytest.mark.parametrize('outcome', ['cancel', 'failed'])
def test_device_scan_cancellation_and_failed_exit_do_not_publish_output(
    qt_application, monkeypatch, outcome,
):
    import io
    import subprocess

    from core import exec as execution
    from gui.main_frame import _ScanThread

    scan = _ScanThread()

    class Process:
        def __init__(self):
            self.returncode = None if outcome == 'cancel' else 1
            self.stdin = None
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()
            self.kill_count = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            if self.returncode is None:
                scan.stop()
                raise subprocess.TimeoutExpired('synthetic scan', timeout)
            return 'partial device list', 'failed'

        def kill(self):
            self.kill_count += 1
            self.returncode = -9

        def wait(self, timeout=None):
            assert self.returncode is not None
            return self.returncode

    process = Process()
    monkeypatch.setattr(execution, 'resolve_command', lambda value: list(value))
    monkeypatch.setattr(execution, 'popen_native', lambda *_args, **_kwargs: process)
    monkeypatch.setattr(execution.ProcessRunner, '_global_procs', {})
    runner = execution.ProcessRunner()
    try:
        assert scan._run_devices_scan(runner) is None
        assert process.kill_count == (1 if outcome == 'cancel' else 0)
        assert process.returncode == (-9 if outcome == 'cancel' else 1)
        assert process.stdout.closed
        assert process.stderr.closed
        assert runner.active_keys == []
        assert execution.ProcessRunner.tracked_active_count() == 0
    finally:
        scan.deleteLater()


def test_overview_shutdown_rejects_late_result_and_legacy_payload_remains_compatible(
    qt_application,
):
    from unittest.mock import Mock

    from gui.main_frame import MainFrame
    from tests.test_model_ci_controller import _device_metadata_controller

    controller = _device_metadata_controller()
    frame = SimpleNamespace(
        _closing=False, adb_controller=controller, _device_metadata={},
        left_panel=SimpleNamespace(device_context_snapshot=lambda: SimpleNamespace(
            connected_devices=('device-1',),
        )), _sync_device_metadata=Mock(),
    )
    MainFrame._on_device_info_updated(frame, 'device-1', {'Model': 'Legacy'})
    assert frame._device_metadata['device-1'] == {'Model': 'Legacy'}
    controller._shutting_down = True
    MainFrame._on_device_info_updated(
        frame, 'device-1', {'Model': 'Late', '_overview_generation': 1},
    )
    assert frame._device_metadata['device-1'] == {'Model': 'Legacy'}
    assert frame._sync_device_metadata.call_count == 1
