"""故障控制器的安全边界与真实编译检查；本机不运行任何安装事件。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.fixtures.windows_installer import fault_smoke as faults


@pytest.mark.parametrize("entry", ["fixture", "product"])
def test_fault_runs_refuse_desktop(tmp_path, monkeypatch, entry):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    workspace = tmp_path / "run"
    with pytest.raises(ValueError, match="一次性"):
        if entry == "fixture":
            faults.run_fault_fixture(tmp_path / "ISCC.exe", workspace, disposable=True)
        else:
            faults.run_product_install_race(
                tmp_path / "ISCC.exe", tmp_path / "app", "1.0.0", workspace, disposable=True
            )
    assert not workspace.exists()


def test_stage_arrival_requires_exact_nonce_stage_and_pid(tmp_path):
    report = tmp_path / "reached"
    report.write_text("nonce\ninstalling\n123\nADBLab.exe\n", encoding="utf-8")
    assert faults._wait_stage(report, "nonce", "installing", timeout=0.1) == (123, "ADBLab.exe")


@pytest.mark.parametrize(
    "text", ["other\ninstalling\n123\n\n", "nonce\nready\n123\n\n", "nonce\ninstalling\n0\n\n"]
)
def test_mismatched_stage_evidence_fails(tmp_path, text):
    report = tmp_path / "reached"
    report.write_text(text, encoding="utf-8")
    with pytest.raises(RuntimeError, match="屏障"):
        faults._wait_stage(report, "nonce", "installing", timeout=0.1)


def test_stage_timeout_is_failure_not_injected_crash(tmp_path):
    with pytest.raises(TimeoutError, match="阶段"):
        faults._wait_stage(tmp_path / "missing", "nonce", "installing", timeout=0)


def test_channel_action_uses_exact_lf_bytes(tmp_path):
    channel = faults.Channel(tmp_path / "channel", "probe")
    channel.action("continue")
    assert (channel.root / "action").read_bytes() == f"{channel.token}\ncontinue".encode("ascii")


@pytest.mark.parametrize("location", ["runner-temp", "standard-default"])
def test_race_accepts_only_runner_temp_or_verified_standard_default(
    tmp_path, monkeypatch, location
):
    from scripts.windows_installer import standard_user

    temporary = tmp_path / "runner"
    local = tmp_path / "standard-profile/AppData/Local"
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    monkeypatch.setattr(
        standard_user, "assert_standard_user", lambda: {"local_appdata": str(local)}
    )
    app = temporary / "test/app" if location == "runner-temp" else local / "Programs/ADBLab"
    assert faults._race_location(app) == app.resolve()


@pytest.mark.parametrize("relative", ["ADBLab", "Programs/other-app", "Programs/ADBLab/child"])
def test_race_rejects_other_standard_profile_locations(tmp_path, monkeypatch, relative):
    from scripts.windows_installer import standard_user

    local = tmp_path / "standard-profile/AppData/Local"
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))
    monkeypatch.setattr(
        standard_user, "assert_standard_user", lambda: {"local_appdata": str(local)}
    )
    with pytest.raises(ValueError, match="默认位置"):
        faults._race_location(local / relative)


def test_default_race_requires_standard_user_identity(tmp_path, monkeypatch):
    from scripts.windows_installer import standard_user

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))

    def administrator():
        raise ValueError("非管理员且未提升")

    monkeypatch.setattr(standard_user, "assert_standard_user", administrator)
    with pytest.raises(ValueError, match="非管理员"):
        faults._race_location(tmp_path / "profile/AppData/Local/Programs/ADBLab")


def test_controller_uses_engine_exit_not_launcher_zero(tmp_path, monkeypatch):
    channel = faults.Channel(tmp_path / "channel", "uninstall-post")
    closed = []
    monkeypatch.setattr(faults, "_wait_stage", lambda *a, **k: (123, ""))
    monkeypatch.setattr(
        faults, "OwnedProcess", lambda *a: SimpleNamespace(wait=lambda **kw: 0, close=lambda: None)
    )
    monkeypatch.setattr(
        faults,
        "Engine",
        lambda pid: SimpleNamespace(
            wait=lambda **kw: 73, stop=lambda: None, close=lambda: closed.append(pid)
        ),
    )
    assert (
        faults._fault_run(["not-executed"], channel, tmp_path / "process.log", action="continue")
        == 73
    )
    assert closed == [123]
    assert (channel.root / "engine-exit.txt").read_text() == "73"


def test_controller_timeout_releases_held_file_and_engine(tmp_path, monkeypatch):
    channel = faults.Channel(tmp_path / "channel", "uninstall-file")
    closed, waits = [], []
    monkeypatch.setattr(faults, "_wait_stage", lambda *a, **k: (123, "ADBLab.exe"))
    monkeypatch.setattr(
        faults,
        "OwnedProcess",
        lambda *a: SimpleNamespace(wait=lambda **kw: 0, close=lambda: closed.append("job")),
    )

    def wait(**kwargs):
        waits.append(kwargs)
        raise TimeoutError("engine still running")

    monkeypatch.setattr(
        faults,
        "Engine",
        lambda pid: SimpleNamespace(
            wait=wait,
            stop=lambda: closed.append("terminated"),
            close=lambda: closed.append("engine"),
        ),
    )
    with pytest.raises(TimeoutError, match="engine still running"):
        faults._fault_run(
            ["not-executed"],
            channel,
            tmp_path / "process.log",
            action="continue",
            at_stage=lambda _: SimpleNamespace(close=lambda: closed.append("file")),
        )
    assert closed == ["terminated", "job", "engine", "file"]
    assert (channel.root / "action").read_bytes().endswith(b"\ncontinue")
    assert not (channel.root / "engine-exit.txt").exists()


def test_controller_wrong_crash_code_is_failure(tmp_path, monkeypatch):
    channel = faults.Channel(tmp_path / "channel", "installing")
    monkeypatch.setattr(faults, "_wait_stage", lambda *a, **k: (123, ""))
    monkeypatch.setattr(
        faults, "OwnedProcess", lambda *a: SimpleNamespace(wait=lambda **kw: 0, close=lambda: None)
    )
    monkeypatch.setattr(
        faults,
        "Engine",
        lambda pid: SimpleNamespace(wait=lambda **kw: 0, stop=lambda: None, close=lambda: None),
    )
    with pytest.raises(RuntimeError, match="实际引擎"):
        faults._fault_run(["not-executed"], channel, tmp_path / "process.log")
    assert (channel.root / "engine-exit.txt").read_text() == "0"


def test_fixture_uninstall_zero_with_remaining_control_is_failure(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / faults.protocol.INSTALL_LOCK).write_bytes(b"")
    monkeypatch.setattr(faults.common, "_run", lambda *a, **k: None)
    monkeypatch.setattr(faults.common, "_registrations", lambda app_id: [])
    times = iter([0, 31])
    monkeypatch.setattr(faults.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="后置核验"):
        faults._uninstall(app, set(), tmp_path / "not-executed.log")


def test_native_owned_job_reaps_orphaned_descendant(tmp_path, native_compiler):
    """只启动本测试自己的睡眠 Python 子进程，验证父进程已退出仍能等待清空整个任务。"""
    pid_file = tmp_path / "child-pid"
    source = (
        "import pathlib,subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(60)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))"
    )
    with (tmp_path / "orphan.log").open("wb") as stream:
        owned = faults.OwnedProcess([sys.executable, "-I", "-S", "-c", source], stream)
        engine = None
        try:
            owned.wait(timeout=10)
            assert pid_file.exists()
            engine = faults.Engine(int(pid_file.read_text()))
            with pytest.raises(TimeoutError):
                engine.wait(timeout=0)
            owned.close()
            assert engine.wait(timeout=5) == 93
        finally:
            owned.close()
            if engine:
                engine.close()


def test_compiler_success_without_file_is_failure(tmp_path, monkeypatch):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    monkeypatch.setattr(faults, "verify_compiler", lambda path: None)
    monkeypatch.setattr(faults.common, "_run", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="编译产物"):
        faults._compile(tmp_path / "ISCC.exe", payload, "1.0.0", tmp_path / "build")


def test_compile_failure_does_not_launch_fixture(tmp_path, monkeypatch):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    monkeypatch.setattr(faults, "verify_compiler", lambda path: None)
    calls = []

    def fail(command, *args, **kwargs):
        calls.append(command)
        raise RuntimeError("compiler failed")

    monkeypatch.setattr(faults.common, "_run", fail)
    with pytest.raises(RuntimeError, match="compiler failed"):
        faults._compile(tmp_path / "ISCC.exe", payload, "1.0.0", tmp_path / "build")
    assert len(calls) == 1 and Path(calls[0][0]).name == "ISCC.exe"


@pytest.fixture
def native_compiler():
    compiler = Path(__file__).resolve().parents[1] / "build/tools/inno-6.7.3/ISCC.exe"
    if sys.platform != "win32" or not compiler.is_file():
        pytest.skip("固定 Inno 6.7.3 不可用，原生编译检查未执行")
    return compiler


@pytest.mark.parametrize("macro", ["ADBLAB_TEST_FAULTS", "FaultRoot", "FaultStage", "FaultToken"])
@pytest.mark.parametrize("origin", ["include", "command"])
def test_production_rejects_every_fault_macro(tmp_path, native_compiler, macro, origin):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    include = tmp_path / "protocol.iss"
    faults._write_protocol(include, faults.protocol.APP_ID)
    # 来自 include 的定义也必须被生产入口拒绝，不能仅检查命令行。
    if origin == "include":
        with include.open("a", encoding="utf-8") as stream:
            stream.write(f'#define {macro} "forbidden"\n')
    result = subprocess.run(
        [
            str(native_compiler),
            "/Q",
            f"/DProtocolInclude={include}",
            "/DAppVersion=1.0.0",
            f"/DAppSourceDir={payload}",
            f"/O{tmp_path}",
            *([f"/D{macro}=forbidden"] if origin == "command" else []),
            str(faults.REPOSITORY / "scripts/windows_installer/ADBLab.iss"),
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert b"Fault injection is forbidden" in result.stdout + result.stderr
    assert not list(tmp_path.glob("*.exe"))


@pytest.mark.parametrize("enabled", [False, True])
def test_full_event_fault_fixture_compiles_without_running(tmp_path, native_compiler, enabled):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    channel = faults.Channel(tmp_path / "channel", "installing") if enabled else None
    executable = faults._compile(
        native_compiler, payload, "1.0.0", tmp_path / "build", channel=channel
    )
    assert executable.is_file()


def test_production_preprocessed_code_contains_no_fault_controller(tmp_path, native_compiler):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    include = tmp_path / "protocol.iss"
    faults._write_protocol(include, faults.protocol.APP_ID)
    script, output = tmp_path / "inspect.iss", tmp_path / "preprocessed.iss"
    script.write_text(
        f'#include "{faults.REPOSITORY / "scripts/windows_installer/ADBLab.iss"}"\n'
        f'#call SaveToFile("{output}")\n',
        encoding="utf-8",
    )
    faults.common._run(
        [
            str(native_compiler),
            "/Q",
            f"/DProtocolInclude={include}",
            "/DAppVersion=1.0.0",
            f"/DAppSourceDir={payload}",
            f"/O{tmp_path}",
            str(script),
        ],
        tmp_path / "compile.log",
    )
    compiled_source = output.read_text(encoding="utf-8-sig")
    for forbidden in (
        "InstallerTestCheckpoint",
        "TestCheckpointUsed",
        "TestProcessId",
        "FaultRoot",
    ):
        assert forbidden not in compiled_source
    assert "procedure CurUninstallStepChanged" in compiled_source


def _compile_safe_probe(tmp_path, native_compiler, *, block_after_continue=False):
    channel = faults.Channel(tmp_path / "channel", "probe")
    script = tmp_path / "probe.iss"
    hooks = faults.REPOSITORY / "tests/fixtures/windows_installer/fault_hooks.iss"
    script.write_text(
        "#define ADBLAB_TEST_FAULTS\n"
        f'#define FaultRoot "{channel.root}"\n'
        f'#define FaultToken "{channel.token}"\n'
        '#define FaultStage "probe"\n'
        "[Setup]\nAppId=ADBLabFaultBarrierProbe\nAppName=ADBLab barrier probe\n"
        "AppVersion=1\nDefaultDirName={tmp}\\unused-fault-probe\n"
        "CreateAppDir=no\nUninstallable=no\nPrivilegesRequired=lowest\n"
        "OutputBaseFilename=barrier-probe\n"
        "[Code]\n"
        "function WinMoveFile(OldName, NewName: String; Flags: LongWord): Boolean;\n"
        "  external 'MoveFileExW@kernel32.dll stdcall';\n"
        "procedure WinExitProcess(ExitCode: LongWord);\n"
        "  external 'ExitProcess@kernel32.dll stdcall';\n"
        f'#include "{hooks}"\n'
        "function InitializeSetup: Boolean;\nbegin\n"
        "  InstallerTestCheckpoint('probe', 'helper-only');\n"
        f"  if not SaveStringToFile('{tmp_path / 'continued'}', 'yes', False) then\n"
        "    RaiseException('cannot record continuation');\n"
        + ("  Sleep(60000);\n" if block_after_continue else "")
        + "  Result := False;\nend;\n",
        encoding="utf-8",
    )
    faults.common._run(
        [str(native_compiler), "/Q", f"/O{tmp_path}", str(script)], tmp_path / "compile.log"
    )
    return channel, tmp_path / "barrier-probe.exe"


@pytest.mark.parametrize("action,code", [("continue", 1), ("crash", 91)])
def test_native_barrier_probe_stops_before_installation(tmp_path, native_compiler, action, code):
    """InitializeSetup 明确返回 False；此探针没有安装文件、登记或卸载器。"""
    channel, executable = _compile_safe_probe(tmp_path, native_compiler)
    actual = faults._fault_run(
        [str(executable), "/VERYSILENT", "/SUPPRESSMSGBOXES"],
        channel,
        tmp_path / "probe.log",
        action=action,
    )
    assert actual == code
    assert (channel.root / "engine-exit.txt").read_text() == str(code)
    assert (channel.root / "reached").read_text().splitlines()[3] == "helper-only"
    assert (tmp_path / "continued").exists() == (action == "continue")


def test_native_continue_timeout_terminates_actual_probe_engine(
    tmp_path, native_compiler, monkeypatch
):
    channel, executable = _compile_safe_probe(tmp_path, native_compiler, block_after_continue=True)
    original_wait = faults.Engine.wait
    observed = []

    def short_wait(self, timeout=180):
        if timeout != 180:
            return original_wait(self, timeout=timeout)
        deadline = time.monotonic() + 5
        while not (tmp_path / "continued").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "continued").exists()
        observed.append(self)
        return original_wait(self, timeout=0)

    actual_close = faults.Engine.close

    def confirm_exited(self):
        assert original_wait(self, timeout=0) == 93
        actual_close(self)

    monkeypatch.setattr(faults.Engine, "wait", short_wait)
    monkeypatch.setattr(faults.Engine, "close", confirm_exited)
    with pytest.raises(TimeoutError, match="Inno 引擎"):
        faults._fault_run(
            [str(executable), "/VERYSILENT", "/SUPPRESSMSGBOXES"],
            channel,
            tmp_path / "probe.log",
            action="continue",
        )
    assert len(observed) == 1


@pytest.mark.parametrize("failure", ["stage-timeout", "engine-construction"])
def test_native_early_controller_failure_reaps_job(tmp_path, native_compiler, monkeypatch, failure):
    channel, executable = _compile_safe_probe(tmp_path, native_compiler)
    original_stage, real_engine = faults._wait_stage, faults.Engine
    observed = []

    def stage_then_timeout(*args, **kwargs):
        pid, detail = original_stage(*args, **kwargs)
        observed.append(real_engine(pid))
        if failure == "stage-timeout":
            raise TimeoutError("injected stage wait failure")
        return pid, detail

    def failed_engine(pid):
        raise OSError("injected engine handle failure")

    monkeypatch.setattr(faults, "_wait_stage", stage_then_timeout)
    monkeypatch.setattr(faults, "Engine", failed_engine)
    try:
        with pytest.raises((TimeoutError, OSError), match="injected"):
            faults._fault_run(
                [str(executable), "/VERYSILENT", "/SUPPRESSMSGBOXES"],
                channel,
                tmp_path / "probe.log",
            )
        assert len(observed) == 1
        assert observed[0].wait(timeout=0) in {91, 93}
    finally:
        for engine in observed:
            engine.stop()
            engine.close()


def test_fault_compilation_contract_keeps_injection_outside_production(tmp_path, monkeypatch):
    payload = faults._payload(tmp_path / "source", tmp_path / "payload", "1.0.0")
    channel = faults.Channel(tmp_path / "channel", "payload")
    output = tmp_path / "build"
    monkeypatch.setattr(faults, "verify_compiler", lambda path: None)
    commands = []

    def compile_only(command, *args, **kwargs):
        commands.append(command)
        (output / "fault-fixture.exe").write_bytes(b"compiler output")

    monkeypatch.setattr(faults.common, "_run", compile_only)
    faults._compile(tmp_path / "ISCC.exe", payload, "1.0.0", output, channel=channel)
    assert len(commands) == 1
    command = commands[0]
    assert Path(command[-1]).name == "fault_fixture.iss"
    assert f"/DFaultStage={channel.stage}" in command
    assert f"/DFaultToken={channel.token}" in command
    assert f"/DFaultRoot={channel.root}" in command
    assert faults.FIXTURE_APP_ID in (output / "protocol.iss").read_text()
    assert faults.protocol.APP_ID not in (output / "protocol.iss").read_text()
