"""投屏启动策略必须显式绑定 ADB 入口和会话环境。"""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core.exec import CommandResult
from services.remote import ScrcpyService
from tests.test_remote_services import _scrcpy_config


@pytest.fixture
def service(monkeypatch):
    runner = Mock()
    runner.run.side_effect = lambda command, **_kwargs: CommandResult(
        success=True,
        output="scrcpy 4.1" if "--version" in command else (
            "ok" if command[-1] == "echo ok" else "Physical size: 1080x2400"
        ),
    )
    instance = ScrcpyService(process_runner=Mock(active_keys=[]), command_runner=runner)
    monkeypatch.setattr("services.remote.scrcpy_service.adb_runtime", lambda: Mock(
        can_shell_fast=Mock(return_value=True),
    ), raising=False)
    monkeypatch.setattr(
        "services.remote.scrcpy_service.resolve_scrcpy_bridge", lambda: "bridge.exe", raising=False,
    )
    return instance


def test_fast_plan_binds_only_scrcpy_child_environment(service, monkeypatch, tmp_path):
    monkeypatch.setenv("ADB", "unrelated-adb.exe")
    exe = tmp_path / "scrcpy.exe"
    (tmp_path / "scrcpy-server").write_bytes(b"server")
    config = _scrcpy_config(exe=str(exe))
    plan = service.build_launch_plan(config)
    assert plan.backend == "direct"
    assert plan.env["ADB"] == "bridge.exe"
    assert plan.env["ADBLAB_SCRCPY_SERIAL"] == config.device
    assert Path(plan.env["ADBLAB_SCRCPY_SERVER"]) == tmp_path / "scrcpy-server"
    import os
    assert os.environ["ADB"] == "unrelated-adb.exe"


@pytest.mark.parametrize(
    "reason", ["native", "missing_bridge", "custom_arguments", "custom_server", "version"],
)
def test_unsupported_launch_selects_native_before_any_process(
    service, monkeypatch, tmp_path, reason,
):
    (tmp_path / "scrcpy-server").write_bytes(b"server")
    config = _scrcpy_config(exe=str(tmp_path / "scrcpy.exe"))
    if reason == "native":
        monkeypatch.setattr("services.remote.scrcpy_service.adb_runtime", lambda: None)
    elif reason == "missing_bridge":
        monkeypatch.setattr("services.remote.scrcpy_service.resolve_scrcpy_bridge", lambda: None)
    elif reason == "custom_arguments":
        config = replace(config, extra_args=["--tcpip"])
    elif reason == "custom_server":
        monkeypatch.setenv("SCRCPY_SERVER_PATH", str(tmp_path / "custom-server"))
    else:
        service._version_cache[config.exe] = "3.3"
    plan = service.build_launch_plan(config)
    assert plan.backend == "native"
    assert plan.env["ADB"] == config.adb
    service.process_runner.start.assert_not_called()


def test_start_plan_uses_frozen_environment_not_later_runtime_state(service, monkeypatch, tmp_path):
    from services.remote.types import ScrcpyLaunchPlan
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "chosen.exe"},
    )
    service.start_plan("mirror", plan)
    assert service.process_runner.start.call_args.kwargs["env"] == {"ADB": "chosen.exe"}


def test_bridge_path_requires_current_source_build(monkeypatch, tmp_path):
    from utils import scrcpy_bridge
    monkeypatch.setattr(scrcpy_bridge, "SOURCE_ROOT", tmp_path)
    assert scrcpy_bridge.resolve_scrcpy_bridge() is None


def test_direct_session_retains_shutdown_ownership_until_helpers_and_cleanup_finish(
    monkeypatch, tmp_path,
):
    import threading

    from services.remote.types import ScrcpyLaunchPlan

    parent_exited = threading.Event()
    cleanup_entered = threading.Event()
    cleanup_release = threading.Event()
    proc = Mock()
    proc.wait.side_effect = parent_exited.wait
    runner = Mock(active_keys=[])
    runner.start.return_value = proc
    runner.stop.side_effect = lambda *_args, **_kwargs: parent_exited.set() or 0
    service = ScrcpyService(process_runner=runner)
    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    monkeypatch.setattr("services.remote.scrcpy_service.has_active_helpers", lambda _path: False)

    def clean(environment, **_kwargs):
        assert Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]).parent.is_dir()
        cleanup_entered.set()
        assert cleanup_release.wait(5)

    monkeypatch.setattr("services.remote.scrcpy_service.cleanup_session_tunnels", clean)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "bridge.exe"},
        backend="direct",
    )
    try:
        service.start_plan("mirror", plan)
        assert "ADBLAB_SCRCPY_SESSION_FILE" not in plan.env
        folder = Path(runner.start.call_args.kwargs["env"]["ADBLAB_SCRCPY_SESSION_FILE"]).parent
        parent_exited.set()
        assert cleanup_entered.wait(2)
        assert service.is_active("mirror")
        assert service.stop("mirror", timeout=0) is None
        assert folder.is_dir()
        with pytest.raises(RuntimeError):
            service.start_plan("mirror", plan)
        cleanup_release.set()
        assert service.stop("mirror", timeout=2) == 0
        assert not service.is_active("mirror")
        assert not folder.exists()
    finally:
        parent_exited.set()
        cleanup_release.set()
        service.stop("mirror", timeout=2)


def test_direct_spawn_failure_removes_only_its_own_empty_session(monkeypatch, tmp_path):
    from services.remote.types import ScrcpyLaunchPlan

    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    sentinel = tmp_path / "scrcpy-sessions" / "prior-session"
    sentinel.mkdir(parents=True)
    runner = Mock(active_keys=[])
    runner.start.side_effect = OSError("synthetic spawn failure")
    service = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "bridge.exe"},
        backend="direct",
    )
    with pytest.raises(OSError):
        service.start_plan("mirror", plan)
    assert list(sentinel.parent.iterdir()) == [sentinel]
    assert not service.is_active("mirror")


def test_cleanup_failure_remains_owned_and_a_later_stop_retries(monkeypatch, tmp_path):
    from services.remote.types import ScrcpyLaunchPlan

    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    monkeypatch.setattr("services.remote.scrcpy_service.has_active_helpers", lambda _path: False)
    cleanup = Mock(side_effect=TimeoutError)
    monkeypatch.setattr("services.remote.scrcpy_service.cleanup_session_tunnels", cleanup)
    runner = Mock(active_keys=[])
    runner.stop.return_value = 0
    service = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "bridge.exe"},
        backend="direct",
    )
    service.start_plan("mirror", plan)
    session = service._bridge_sessions["mirror"]
    session.thread.join(2)
    assert service.is_active("mirror")
    assert session.cleanup_failed
    assert session.folder.is_dir()
    cleanup.side_effect = None
    assert service.stop("mirror", timeout=2) == 0
    assert not service.is_active("mirror")
    assert not session.folder.exists()
    assert cleanup.call_count == 2


@pytest.mark.parametrize("failure", ["construct", "start"])
def test_cleanup_thread_failure_requests_stop_and_preserves_ownership(
    monkeypatch, tmp_path, port_candidates, failure,
):
    import threading

    from services.remote import scrcpy_service
    from services.remote.types import ScrcpyLaunchPlan

    port_candidates([32106])
    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    monkeypatch.setattr("services.remote.scrcpy_service.has_active_helpers", lambda _path: False)
    monkeypatch.setattr("services.remote.scrcpy_service.cleanup_session_tunnels", Mock())
    runner = Mock(active_keys=[])
    runner.stop.return_value = 0
    service = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "bridge.exe"},
        backend="direct",
    )
    with monkeypatch.context() as patch:
        unavailable = Mock(side_effect=RuntimeError("thread unavailable"))
        if failure == "construct":
            patch.setattr(threading, "Thread", unavailable)
        else:
            patch.setattr(threading.Thread, "start", unavailable)
        with pytest.raises(RuntimeError):
            service.start_plan("mirror", plan)
    runner.request_stop.assert_called_once_with("mirror")
    assert service.is_active("mirror")
    assert 32106 in scrcpy_service._reserved_ports
    assert service.stop("mirror", timeout=2) == 0
    assert not service.is_active("mirror")
    assert 32106 not in scrcpy_service._reserved_ports


@pytest.fixture
def port_candidates(monkeypatch):
    from types import SimpleNamespace

    from services.remote import scrcpy_service

    candidates = iter(())
    probes = []

    def create(*_args):
        probe = MagicMock()
        probe.__enter__.return_value = probe
        probe.getsockname.return_value = ("127.0.0.1", next(candidates))
        probes.append(probe)
        return probe

    def install(ports):
        nonlocal candidates
        candidates = iter(ports)
        return probes

    monkeypatch.setattr(scrcpy_service, "socket", SimpleNamespace(
        socket=create, AF_INET=2, SOCK_STREAM=1, SOL_SOCKET=65535, SO_EXCLUSIVEADDRUSE=-5,
    ))
    return install


@pytest.mark.parametrize(
    "backends", [("native", "native"), ("direct", "direct"), ("direct", "native")],
)
def test_concurrent_services_reserve_distinct_ports_and_bind_direct_environment(
    monkeypatch, tmp_path, port_candidates, backends,
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from services.remote.types import ScrcpyLaunchPlan

    probes = port_candidates([32101, 32101, 32102])
    rendezvous = threading.Barrier(2)
    parent_exit = threading.Event()
    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    monkeypatch.setattr("services.remote.scrcpy_service.has_active_helpers", lambda _path: False)
    monkeypatch.setattr("services.remote.scrcpy_service.cleanup_session_tunnels", Mock())
    services, plans, runners = [], [], []
    for backend in backends:
        process = Mock()
        process.wait.side_effect = parent_exit.wait
        runner = Mock(active_keys=[])

        def start(*_args, proc=process, **_kwargs):
            rendezvous.wait(timeout=3)
            return proc

        runner.start.side_effect = start
        runner.stop.return_value = 0
        runners.append(runner)
        services.append(ScrcpyService(process_runner=runner))
        plans.append(ScrcpyLaunchPlan(
            args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "chosen.exe"},
            backend=backend,
        ))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(subject.start_plan, "mirror", plan)
                for subject, plan in zip(services, plans, strict=True)
            ]
            for future in futures:
                future.result(timeout=5)
        ports = set()
        for subject, plan, runner in zip(services, plans, runners, strict=True):
            assert subject.is_active("mirror")
            call = runner.start.call_args
            port_args = [arg for arg in call.args[1] if arg.startswith("--port=")]
            assert len(port_args) == 1
            port = int(port_args[0].split("=")[1])
            ports.add(port)
            if plan.backend == "direct":
                assert call.kwargs["env"]["ADBLAB_SCRCPY_PORT_RANGE"] == f"{port}:{port}"
            assert plan.args == ["scrcpy.exe"]
            assert plan.env == {"ADB": "chosen.exe"}
        assert ports == {32101, 32102}
        assert len(probes) == 3
        for probe in probes:
            probe.bind.assert_called_once_with(("127.0.0.1", 0))
            probe.setsockopt.assert_called_once_with(65535, -5, 1)
    finally:
        parent_exit.set()
        for subject in services:
            assert subject.stop("mirror", timeout=2) == 0
    from services.remote import scrcpy_service

    assert not {32101, 32102} & scrcpy_service._reserved_ports


@pytest.mark.parametrize("backend", ["native", "direct"])
def test_spawn_failure_releases_reserved_port_for_the_next_launch(
    monkeypatch, tmp_path, port_candidates, backend,
):
    import threading

    from services.remote.types import ScrcpyLaunchPlan

    probes = port_candidates([32103, 32103])
    monkeypatch.setattr("services.remote.scrcpy_service.user_data_root", lambda: tmp_path)
    monkeypatch.setattr("services.remote.scrcpy_service.has_active_helpers", lambda _path: False)
    monkeypatch.setattr("services.remote.scrcpy_service.cleanup_session_tunnels", Mock())
    exited = threading.Event()
    process = Mock()
    process.wait.side_effect = exited.wait
    runner = Mock(active_keys=[])
    runner.start.side_effect = [OSError("synthetic spawn failure"), process]
    runner.stop.return_value = 0
    subject = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "chosen.exe"},
        backend=backend,
    )
    with pytest.raises(OSError):
        subject.start_plan("mirror", plan)
    assert not subject.is_active("mirror")
    if backend == "direct":
        assert not list((tmp_path / "scrcpy-sessions").iterdir())
    try:
        subject.start_plan("mirror", plan)
        assert runner.start.call_args.args[1][-1] == "--port=32103"
        assert len(probes) == 2
    finally:
        exited.set()
        assert subject.stop("mirror", timeout=2) == 0


def test_cleanup_failure_keeps_port_reserved_until_successful_retry(
    monkeypatch, tmp_path, port_candidates,
):
    from services.remote import scrcpy_service
    from services.remote.types import ScrcpyLaunchPlan

    port_candidates([32104])
    monkeypatch.setattr(scrcpy_service, "user_data_root", lambda: tmp_path)
    monkeypatch.setattr(scrcpy_service, "has_active_helpers", lambda _path: False)
    cleanup = Mock(side_effect=TimeoutError)
    monkeypatch.setattr(scrcpy_service, "cleanup_session_tunnels", cleanup)
    runner = Mock(active_keys=[])
    runner.stop.return_value = 0
    subject = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe"], device_info="", version="4.1", env={"ADB": "chosen.exe"},
        backend="direct",
    )
    try:
        subject.start_plan("mirror", plan)
        session = subject._bridge_sessions["mirror"]
        session.thread.join(2)
        assert not session.thread.is_alive()
        assert session.cleanup_failed
        assert 32104 in scrcpy_service._reserved_ports
        assert subject.stop("mirror", timeout=0) is None
        assert 32104 in scrcpy_service._reserved_ports
        assert session.folder.is_dir()
    finally:
        cleanup.side_effect = None
        assert subject.stop("mirror", timeout=2) == 0
    assert 32104 not in scrcpy_service._reserved_ports
    assert not session.folder.exists()


@pytest.mark.parametrize("arguments", [["--port", "32105"], ["--port=32105"], ["-p32105"]])
def test_explicit_native_port_is_preserved(monkeypatch, arguments):
    from services.remote.types import ScrcpyLaunchPlan

    reserve = Mock(side_effect=AssertionError("explicit port must not be replaced"))
    monkeypatch.setattr("services.remote.scrcpy_service._reserve_port", reserve)
    runner = Mock(active_keys=[])
    runner.stop.return_value = 0
    subject = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=["scrcpy.exe", *arguments], device_info="", version="4.1", backend="native",
    )
    subject.start_plan("mirror", plan)
    assert runner.start.call_args.args[1] == plan.args
    reserve.assert_not_called()
    assert subject.stop("mirror", timeout=2) == 0
