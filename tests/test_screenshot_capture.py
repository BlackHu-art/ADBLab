"""截图的原子发布、完整性、取消和有限兼容路径回归。"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QImage

from core import exec as execution
from core.exec import CommandResult
from models import adb_testing as module
from models.adb_testing import ADBTesting


def write_png(path):
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0xFF123456)
    assert image.save(str(path), "PNG")


@pytest.mark.parametrize("failure", ["cancelled", "shutdown", "timeout", "partial", "save"])
def test_capture_failure_preserves_previous_file_and_removes_staging(
    tmp_path, monkeypatch, failure,
):
    model = ADBTesting()
    path = tmp_path / "existing.png"
    write_png(path)
    original = path.read_bytes()
    stop = threading.Event()

    def capture(cmd, staged, *, timeout, cancelled):
        assert not cancelled()
        assert Path(staged).parent == path.parent and str(path) != staged
        write_png(staged)
        if failure == "cancelled":
            stop.set()
        elif failure == "shutdown":
            model.begin_shutdown()
        elif failure == "timeout":
            return CommandResult(False, error="Timeout(30s)")
        elif failure == "partial":
            Path(staged).write_bytes(Path(staged).read_bytes()[:-12])
        return CommandResult(True)

    monkeypatch.setattr(module.CommandRunner, "run_to_file", capture)
    native = Mock(side_effect=AssertionError("unexpected capture replay"))
    monkeypatch.setattr(module.CommandRunner, "run", native)
    if failure == "save":
        monkeypatch.setattr(module.os, "replace", Mock(side_effect=PermissionError))
    result = model.take_screenshot_async.__wrapped__(
        model, "test-device", str(path), cancelled=stop.is_set,
    )
    assert not result["success"]
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".adblab-shot-*"))
    native.assert_not_called()


def test_pre_cancelled_capture_never_creates_file(tmp_path, monkeypatch):
    capture = Mock(side_effect=AssertionError("unexpected command"))
    monkeypatch.setattr(module.CommandRunner, "run_to_file", capture)
    model = ADBTesting()
    result = model.take_screenshot_async.__wrapped__(
        model, "test-device", str(tmp_path / "shot.png"), cancelled=lambda: True,
    )
    assert not result["success"] and result["error"] == "Cancelled"
    assert not list(tmp_path.iterdir())


def test_locked_temporary_file_does_not_mask_capture_failure(tmp_path, monkeypatch, caplog):
    model = ADBTesting()
    path = tmp_path / "existing.png"
    write_png(path)
    original = path.read_bytes()
    monkeypatch.setattr(module.CommandRunner, "run_to_file", Mock(return_value=CommandResult(
        False, error="Cancelled",
    )))
    with monkeypatch.context() as locked:
        locked.setattr(module.os, "unlink", Mock(side_effect=PermissionError("private path")))
        result = model.take_screenshot_async.__wrapped__(model, "test-device", str(path))
    assert not result["success"] and result["error"] == "Cancelled"
    assert path.read_bytes() == original
    assert "Temporary screenshot cleanup failed (PermissionError)" in caplog.text
    assert "private path" not in caplog.text
    assert len(list(tmp_path.glob(".adblab-shot-*"))) == 1


@pytest.mark.parametrize("pull_succeeds", [True, False])
def test_legacy_capture_uses_unique_remote_file_and_cleans_on_failure(
    tmp_path, monkeypatch, pull_succeeds,
):
    model = ADBTesting()
    monkeypatch.setattr(module.CommandRunner, "run_to_file", Mock(return_value=CommandResult(
        False, error="unknown command exec-out", returncode=1,
    )))
    commands = []

    def run(cmd, *, timeout, cancelled):
        assert 0 < timeout <= 30
        commands.append(cmd)
        if "pull" in cmd:
            write_png(cmd[-1])
            return CommandResult(pull_succeeds, error="failed" if not pull_succeeds else "")
        return CommandResult(True)

    monkeypatch.setattr(module.CommandRunner, "run", run)
    remotes = []
    for index in range(2):
        output = tmp_path / f"shot-{index}.png"
        result = model.take_screenshot_async.__wrapped__(model, "test-device", str(output))
        assert result["success"] == pull_succeeds
        assert output.exists() == pull_succeeds
        capture, pull, cleanup = commands[-3:]
        remote = capture[-1]
        assert remote.startswith("/sdcard/adblab_screenshot_")
        assert pull[-2] == cleanup[-1] == remote
        assert cleanup[-3:-1] == ["rm", "-f"]
        remotes.append(remote)
    assert len(set(remotes)) == 2
    assert not list(tmp_path.glob(".adblab-shot-*"))


def test_complete_image_after_budget_does_not_publish(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def capture(_cmd, staged, **kwargs):
        write_png(staged)
        now[0] += 31
        return CommandResult(True)

    monkeypatch.setattr(module.CommandRunner, "run_to_file", capture)
    model = ADBTesting()
    result = model.take_screenshot_async.__wrapped__(
        model, "test-device", str(tmp_path / "shot.png"),
    )
    assert not result["success"] and result["error"].startswith("Timeout")
    assert not list(tmp_path.iterdir())


def test_png_validation_requires_both_complete_boundaries_and_decodable_pixels(tmp_path):
    path = tmp_path / "shot.png"
    write_png(path)
    valid = path.read_bytes()
    assert ADBTesting._is_valid_png(str(path), decode=True)
    path.write_bytes(valid[:-12])
    assert not ADBTesting._is_valid_png(str(path))
    path.write_bytes(valid[:8] + b"corrupt image" + valid[-12:])
    assert not ADBTesting._is_valid_png(str(path), decode=True)


@pytest.mark.parametrize("mode", ["success", "cancelled", "timeout"])
def test_native_file_capture_preserves_bytes_and_reaps_client(tmp_path, monkeypatch, mode):
    """原生后端真实子进程写二进制；完成、取消及超时均释放本次客户端和活动计数。"""
    path = tmp_path / "native.part"
    payload = b"\x89PNG\r\n\x1a\n\x00\xff"
    monkeypatch.setattr(execution, "adb_runtime", lambda: None)
    original_popen = execution.subprocess.Popen
    clients = []

    def create(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        clients.append(proc)
        return proc

    monkeypatch.setattr(execution.subprocess, "Popen", create)
    script = (
        f"import os, time; os.write(1, {payload!r}); time.sleep({0 if mode == 'success' else 30})"
    )
    result = execution.CommandRunner.run_to_file(
        [sys.executable, "-c", script], str(path), timeout=0.3 if mode == "timeout" else 5,
        cancelled=lambda: mode == "cancelled" and path.exists() and path.stat().st_size > 0,
    )
    assert result.success == (mode == "success")
    if mode != "timeout":
        assert path.read_bytes() == payload
    if mode == "cancelled":
        assert result.error == "Cancelled"
    elif mode == "timeout":
        assert result.error.startswith("Timeout")
    else:
        assert result.output == str(path)
    assert len(clients) == 1 and clients[0].poll() is not None
    assert execution.CommandRunner.active_count() == 0
