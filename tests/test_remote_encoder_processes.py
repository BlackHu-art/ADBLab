"""编码器查询取消、超时后回收自有客户端，保留独立服务。"""

import json
import sys
import threading
import time

import psutil
import pytest

from core.exec import CommandRunner
from services.remote.scrcpy_service import ScrcpyService
from services.remote.types import ScrcpyConfig
from tests import test_native_process

frozen_launcher = test_native_process.frozen_launcher


@pytest.mark.parametrize("cancel", [True, False])
@pytest.mark.parametrize("parent_exits", [False, True])
@pytest.mark.parametrize("isolate", [False, True])
def test_encoder_probe_reaps_client_and_preserves_independent_server(
    tmp_path, cancel, parent_exits, isolate, request, monkeypatch,
):
    if isolate:
        request.getfixturevalue("frozen_launcher")
    original_children = psutil.Process.children

    class Vanished:
        def exe(self):
            raise psutil.NoSuchProcess(-1)

    def children(process, recursive=False):
        existing = original_children(process, recursive=recursive)
        return [Vanished(), *existing] if recursive else existing

    monkeypatch.setattr(psutil.Process, "children", children)
    marker = tmp_path / "processes.json"
    executable = sys._base_executable
    server_code = "import time; time.sleep(120)"
    client_code = (
        "import subprocess,sys,time,json; from pathlib import Path; "
        f"server=subprocess.Popen([sys.executable,'-c',{server_code!r},'fork-server','server'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(marker)!r}).write_text(json.dumps([__import__('os').getpid(),server.pid])); "
        "time.sleep(120)"
    )
    parent_code = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable,'-c',{client_code!r}]); "
        + ("sys.exit(1)" if parent_exits else "child.wait()")
    )
    stopped = threading.Event()
    failure = []

    class Runner:
        @staticmethod
        def run(command, **kwargs):
            return CommandRunner.run([executable, "-c", parent_code], **kwargs)

    config = ScrcpyConfig(
        exe=executable, adb=executable, device="fixture-device", maxsize="1280",
        fps="30", bitrate="8", codec="auto", buffer="20", orientation="0",
    )
    service = ScrcpyService(command_runner=Runner)

    def probe():
        try:
            service.detect_video_encoder(
                config, deadline=time.monotonic() + (10 if cancel else 2),
                cancelled=stopped.is_set,
            )
        except (InterruptedError, TimeoutError) as error:
            failure.append(error)

    thread = threading.Thread(target=probe)
    thread.start()
    processes = []
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        processes = [psutil.Process(pid) for pid in json.loads(marker.read_text())]
        if cancel:
            stopped.set()
        thread.join(4)
        assert not thread.is_alive()
        assert len(failure) == 1
        client, server = processes
        assert not client.is_running(), "编码器查询遗留 ADB 子客户端"
        assert server.is_running(), "查询取消不得停止独立 ADB 服务"
        assert not service.encoder_probes_running()
    finally:
        stopped.set()
        thread.join(2)
        if not processes and marker.exists():
            processes = [psutil.Process(pid) for pid in json.loads(marker.read_text())]
        for process in processes:
            try:
                process.kill()
                process.wait(2)
            except psutil.NoSuchProcess:
                pass


def test_probe_cleanup_failure_remains_owned_after_parent_exit(tmp_path, monkeypatch):
    marker = tmp_path / "client.pid"
    executable = sys._base_executable
    code = (
        "import subprocess,sys,time; from pathlib import Path; "
        "client=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        f"Path({str(marker)!r}).write_text(str(client.pid)); client.wait()"
    )
    refuse_kill = threading.Event()
    refuse_kill.set()
    original_kill = psutil.Process.kill

    def kill(process):
        if marker.exists() and process.pid == int(marker.read_text()) and refuse_kill.is_set():
            raise psutil.AccessDenied(process.pid)
        return original_kill(process)

    monkeypatch.setattr(psutil.Process, "kill", kill)

    class Runner:
        @staticmethod
        def run(command, **kwargs):
            return CommandRunner.run([executable, "-c", code], **kwargs)

    service = ScrcpyService(command_runner=Runner)
    config = ScrcpyConfig(
        exe=executable, adb=executable, device="fixture-device", maxsize="1280",
        fps="30", bitrate="8", codec="auto", buffer="20", orientation="0",
    )
    client = parent = None
    try:
        with pytest.raises(OSError, match="清理"):
            service.detect_video_encoder(config, deadline=time.monotonic() + 2)
        assert marker.exists()
        client = psutil.Process(int(marker.read_text()))
        parent = client.parent()
        assert parent is not None
        assert service.encoder_probes_running()
        original_kill(parent)
        parent.wait(2)
        assert service.encoder_probes_running(), "父退出不能解除尚有客户端的资源登记"
        service.request_stop_encoder_probes()
        assert not service.wait_encoder_probes(0.02)
        assert service.encoder_probes_running()
        refuse_kill.clear()
        assert service.wait_encoder_probes(2)
        assert not client.is_running()
        assert not service.encoder_probes_running()
        with pytest.raises(InterruptedError):
            service.detect_video_encoder(config, deadline=time.monotonic() + 1)
    finally:
        refuse_kill.clear()
        for process in (client, parent):
            if process is not None:
                try:
                    original_kill(process)
                    process.wait(2)
                except psutil.NoSuchProcess:
                    pass
