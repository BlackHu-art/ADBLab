"""通过受控设备进程表执行录屏停止脚本，验证归属而不访问真实设备。"""

import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models.adb_advanced import ADBAdvanced, _recording_launch_script


@pytest.fixture
def posix_shell():
    if os.name == "nt":
        git = shutil.which("git")
        shell = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
    else:
        shell = shutil.which("bash")
    if shell is None or not Path(shell).is_file():
        pytest.skip("生成的 Android Shell 脚本需要本机 POSIX shell；不安装系统软件")
    return str(shell)


def _start(model):
    process = SimpleNamespace(pid=123, returncode=None)
    process.poll = lambda: process.returncode
    with patch.object(model._rec_procs, "start", return_value=process) as start:
        result = ADBAdvanced.start_screen_record_async.__wrapped__(
            model, "mock-device", "unused", duration=30, batch_id="owned",
        )
    assert result["success"]
    return process, result, start.call_args.args[1]


def _run_with_device_table(shell, command, *, remote, registry, started, executable="screenrecord"):
    # 只替换设备 /proc 与信号边界；实际生成的条件、字段解析和信号选择由 shell 执行。
    stat = "42 (screenrecord) S " + " ".join(["0"] * 18 + [started])
    functions = f"""
cat() {{
    case "$1" in
      */adblab-record-*) printf '%s\\n' {shlex.quote(registry)} ;;
      /proc/42/stat) printf '%s\\n' {shlex.quote(stat)} ;;
      /proc/42/cmdline)
        printf '%s\\000' {shlex.quote(executable)} --time-limit 30 {shlex.quote(remote)} ;;
      *) return 1 ;;
    esac
}}
kill() {{ printf 'SIGNAL:%s\\n' "$*"; }}
pkill() {{ printf 'SIGNAL:-2 42\\nSIGNAL:-2 99\\n'; }}
"""
    script = command[4] if len(command) == 5 else shlex.join(command[4:])
    result = subprocess.run(
        [shell, "--noprofile", "--norc"], input=functions + "\n" + script,
        text=True, capture_output=True, timeout=3, check=False,
    )
    signals = [line.removeprefix("SIGNAL:") for line in result.stdout.splitlines()
               if line.startswith("SIGNAL:")]
    return result, signals


@pytest.mark.parametrize(
    ("registry", "current_start", "target", "executable", "expected_signals"),
    [
        ("42 777", "777", "owned", "screenrecord", ["-2 42"]),
        ("42 777", "888", "owned", "screenrecord", []),
        ("42 777", "777", "/sdcard/other-client.mp4", "screenrecord", []),
        ("42 777", "777", "owned", "unrelated", []),
        ("", "777", "owned", "screenrecord", []),
        ("42 777 extra", "777", "owned", "screenrecord", []),
        ("bad 777", "777", "owned", "screenrecord", []),
    ],
)
def test_recording_stop_signals_only_verified_owned_process(
    posix_shell, registry, current_start, target, executable, expected_signals,
):
    model = ADBAdvanced()
    process, started, _command = _start(model)
    signals = []

    def run(command, **_kwargs):
        outcome, actual = _run_with_device_table(
            posix_shell, command,
            remote=started["remote_path"] if target == "owned" else target,
            registry=registry, started=current_start, executable=executable,
        )
        signals.extend(actual)
        if outcome.returncode == 0:
            process.returncode = 0
        return {"success": outcome.returncode == 0, "error": outcome.stderr.strip()}

    with patch.object(model, "_run", side_effect=run), patch.object(model._rec_procs, "stop"):
        stopped = ADBAdvanced.stop_screen_record_async.__wrapped__(
            model, "mock-device", "owned",
        )

    assert signals == expected_signals
    assert stopped["success"] is bool(expected_signals)


def test_recording_stop_during_shutdown_never_signals_device():
    model = ADBAdvanced()
    _start(model)
    model.begin_shutdown()
    with patch.object(model, "_run") as run, patch.object(model._rec_procs, "stop"):
        stopped = ADBAdvanced.stop_screen_record_async.__wrapped__(
            model, "mock-device", "owned",
        )
    assert not stopped["success"]
    run.assert_not_called()


@pytest.mark.parametrize("recording_exit", [0, 7])
def test_recording_wrapper_registers_pid_waits_and_cleans_own_file(
    posix_shell, tmp_path, recording_exit,
):
    owner = tmp_path / "adblab-record-owned"
    arguments = tmp_path / "arguments.txt"
    gate = tmp_path / "finish"
    script = f"""
screenrecord() {{
    printf '%s\\n' "$@" > {shlex.quote(arguments.as_posix())}
    while [ ! -e {shlex.quote(gate.as_posix())} ]; do sleep 0.05; done
    return {recording_exit}
}}
""" + _recording_launch_script(owner.as_posix(), "/sdcard/owned.mp4")
    process = subprocess.Popen(
        [posix_shell, "--noprofile", "--norc", "-c", script, "adblab-record",
         "--time-limit", "30", "/sdcard/owned.mp4"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 3
        while not owner.exists() or not owner.read_text().strip():
            assert time.monotonic() < deadline, "recording ownership was not registered"
            threading.Event().wait(0.01)
        pid, start = owner.read_text().strip().split()
        assert int(pid) > 1 and start.isdecimal()
        assert process.poll() is None
        assert arguments.read_text().splitlines() == [
            "--time-limit", "30", "/sdcard/owned.mp4",
        ]
    finally:
        gate.touch()
        _stdout, stderr = process.communicate(timeout=3)
    assert process.returncode == recording_exit, stderr
    assert not owner.exists()


def test_recording_wrapper_refuses_existing_ownership_without_starting(posix_shell, tmp_path):
    owner = tmp_path / "adblab-record-existing"
    owner.write_text("other owner")
    marker = tmp_path / "started"
    script = (
        f"screenrecord() {{ touch {shlex.quote(marker.as_posix())}; }}\n"
        + _recording_launch_script(owner.as_posix(), "/sdcard/owned.mp4")
    )
    result = subprocess.run(
        [posix_shell, "--noprofile", "--norc", "-c", script, "adblab-record"],
        text=True, capture_output=True, timeout=3, check=False,
    )
    assert result.returncode != 0
    assert owner.read_text() == "other owner"
    assert not marker.exists()


@pytest.mark.parametrize("delayed_exec", [False, True])
@pytest.mark.parametrize("interrupt_phase", ["registration", "before_pid_assignment"])
def test_recording_wrapper_hangup_during_identity_registration_stops_child(
    posix_shell, tmp_path, delayed_exec, interrupt_phase,
):
    owner = tmp_path / "adblab-record-owned"
    wrapper_pid = tmp_path / "wrapper.pid"
    reading = tmp_path / "reading"
    read_gate = tmp_path / "read-gate"
    child_gate = tmp_path / "child-gate"
    child_running = tmp_path / "child-running"
    signalled = tmp_path / "signalled"
    cmdline_seen = tmp_path / "cmdline-seen"
    def quote(path):
        return shlex.quote(path.as_posix())

    prefix = f"""
printf '%s' "$$" > {quote(wrapper_pid)}
cat() {{
    case "$1" in
      */stat)
        touch {quote(reading)}
        while [ ! -e {quote(read_gate)} ]; do sleep 0.05; done
        command cat "$@" ;;
      */cmdline)
        if [ {shlex.quote(str(delayed_exec))} = True ] && [ ! -e {quote(cmdline_seen)} ]; then
            touch {quote(cmdline_seen)}
            printf '%s\\000' sh /sdcard/owned.mp4
        else
            printf '%s\\000' screenrecord /sdcard/owned.mp4
        fi ;;
      *) command cat "$@" ;;
    esac
}}
screenrecord() {{
    trap 'exit 0' TERM
    touch {quote(child_running)}
    while [ ! -e {quote(child_gate)} ]; do sleep 0.05; done
}}
kill() {{
    printf '%s' "$*" > {quote(signalled)}
    builtin kill -TERM "$2"
}}
interrupt_before_pid() {{
    if [ "$1" = 'pid=$!' ]; then
        trap - DEBUG
        builtin kill -HUP "$$"
    fi
}}
if [ {shlex.quote(interrupt_phase)} = before_pid_assignment ]; then
    trap 'interrupt_before_pid "$BASH_COMMAND"' DEBUG
fi
"""
    process = subprocess.Popen(
        [posix_shell, "--noprofile", "--norc", "-c",
         prefix + _recording_launch_script(owner.as_posix(), "/sdcard/owned.mp4"),
         "adblab-record", "/sdcard/owned.mp4"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 3
        while not reading.exists() or not child_running.exists():
            assert time.monotonic() < deadline, "recording registration did not block"
            threading.Event().wait(0.01)
        if interrupt_phase == "registration":
            target = str(int(wrapper_pid.read_text()))
            subprocess.run(
                [posix_shell, "--noprofile", "--norc", "-c", 'kill -HUP "$1"', "signal", target],
                check=True, capture_output=True, timeout=3,
            )
        read_gate.touch()
        deadline = time.monotonic() + 2
        while not signalled.exists() and process.poll() is None:
            assert time.monotonic() < deadline, "wrapper did not stop its recording"
            threading.Event().wait(0.01)
        assert signalled.exists(), "hangup discarded ownership without stopping the child"
        assert signalled.read_text().startswith("-2 ")
    finally:
        read_gate.touch()
        child_gate.touch()
        process.communicate(timeout=3)
    assert process.returncode != 0
    assert not owner.exists()
