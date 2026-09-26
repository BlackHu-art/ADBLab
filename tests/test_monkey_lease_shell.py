"""在隔离临时目录执行真实 shell 协议，kill 用函数替身记录目标，不接触系统进程。"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from core.monkey_process import MonkeyProcessLease


@pytest.fixture
def shell_lease(tmp_path, monkeypatch):
    bash = shutil.which("bash")
    if bash is None:
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        bash = str(candidate) if candidate.is_file() else None
    if bash is None:
        pytest.skip("需要本机 POSIX shell；协议纯 Python 边界另有单元测试")
    lease = MonkeyProcessLease()
    lease.path = (tmp_path / "lease").as_posix()
    state = tmp_path / "state"
    killed = tmp_path / "killed"
    state.write_text("111")
    monkeypatch.setattr(lease, "_identity_function", lambda: (
        f"identity() {{ cat {shlex.quote(state.as_posix())}; }}; "
    ))

    def run(command, *, deny=False):
        script = shlex.split(command)[2]
        kill = (
            "kill() { return 1; }; " if deny else
            f"kill() {{ printf '%s' \"$2\" >> {shlex.quote(killed.as_posix())}; "
            f"printf GONE > {shlex.quote(state.as_posix())}; }}; "
        )
        result = subprocess.run(
            [bash, "-c", kill + "sleep() { :; }; " + script],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout

    return lease, state, killed, run


@pytest.mark.parametrize("current", ["111", "222", "GONE"])
def test_stop_checks_start_identity_before_signalling_and_removes_only_lease(shell_lease, current):
    lease, state, killed, run = shell_lease
    directory = Path(lease.path)
    directory.mkdir()
    (directory / "identity").write_bytes(b"123 111\n")
    state.write_text(current)
    assert lease.stop(run)
    assert not directory.exists()
    if current == "111":
        assert killed.read_text() == "123"
    else:
        assert not killed.exists()


def test_permission_failure_retains_lease_until_confirmed_retry(shell_lease):
    lease, _state, killed, run = shell_lease
    directory = Path(lease.path)
    directory.mkdir()
    (directory / "identity").write_bytes(b"123 111\n")
    assert not lease.stop(lambda command: run(command, deny=True))
    assert directory.exists() and not lease.released
    assert not killed.exists()
    assert lease.stop(run)
    assert not directory.exists()


def test_stop_before_remote_launch_prevents_exec_and_retains_obligation_until_ack(shell_lease):
    lease, state, killed, run = shell_lease
    assert not lease.stop(run)
    assert Path(lease.path, "cancel").exists()
    command_ran = Path(lease.path, "unexpected")
    run(lease.command(["touch", command_ran.as_posix()]))
    assert not command_ran.exists()
    assert Path(lease.path, "identity").exists()
    state.write_text("GONE")
    assert lease.stop(run)
    assert not Path(lease.path).exists()
    assert not killed.exists()
