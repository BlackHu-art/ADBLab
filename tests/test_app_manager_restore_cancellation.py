import zipfile
from unittest.mock import patch

import pytest

from core.exec import CommandResult
from models.app_manager_worker import AppManagerWorker


@pytest.mark.parametrize(
    ("archive_name", "members", "expected_modes"),
    [
        ("ordinary.zip", ["one.apk", "two.apk"], ["install", "install"]),
        ("base.apk-backup.zip", ["one.apk", "two.apk"], ["install", "install"]),
        ("ordinary.zip", ["base.apk-folder/one.apk", "two.apk"], ["install", "install"]),
        ("ordinary.zip", ["not-base.apk", "two.apk"], ["install", "install"]),
        ("ordinary.zip", ["base.apk", "split.apk"], ["install-multiple"]),
    ],
)
def test_restore_chooses_split_mode_only_from_exact_apk_basename(
    tmp_path, archive_name, members, expected_modes,
):
    archive = tmp_path / archive_name
    with zipfile.ZipFile(archive, "w") as zf:
        for member in members:
            zf.writestr(member, b"fake apk")
    worker = AppManagerWorker("mock-device", "restore_apps")
    modes, completed = [], []
    worker.operation_done.connect(completed.append)

    def install(*args, **_kwargs):
        modes.append(args[0])
        return CommandResult(success=True)

    with patch.object(worker, "_adb", side_effect=install):
        worker._restore_apps([str(archive)])

    assert modes == expected_modes
    assert completed == ["restore"]


@pytest.mark.parametrize("cancel_phase", ["extract", "first_install", "last_install"])
def test_restore_cancellation_stops_new_installs_and_success(tmp_path, cancel_phase):
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("one.apk", b"apk")
        zf.writestr("two.apk", b"apk")
    worker = AppManagerWorker("mock-device", "restore_apps")
    done, feedback, calls = [], [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda level, message: feedback.append((level, message)))

    def install(*args, **kwargs):
        calls.append(args)
        if cancel_phase == "first_install" or (cancel_phase == "last_install" and len(calls) == 2):
            worker.abort()
        return CommandResult(success=True)

    from models.app_manager_worker import safe_extract_zip

    def extract(zf, target):
        safe_extract_zip(zf, target)
        if cancel_phase == "extract":
            worker.abort()

    with (
        patch.object(worker, "_adb", side_effect=install),
        patch("models.app_manager_worker.safe_extract_zip", side_effect=extract),
    ):
        worker._restore_apps([str(archive)])
    assert len(calls) == {"extract": 0, "first_install": 1, "last_install": 2}[cancel_phase]
    assert done == []
    assert feedback[-1][0] == "warning"
    assert f"{len(calls)}" in feedback[-1][1]


def test_backup_cancellation_does_not_start_remaining_pulls(tmp_path):
    worker = AppManagerWorker("mock-device", "backup_app")
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        if args[0] == "shell":
            return CommandResult(
                success=True, output="package:/app/base.apk\npackage:/app/split.apk"
            )
        worker.abort()
        return CommandResult(success=True)

    with patch.object(worker, "_adb", side_effect=adb):
        worker._backup_app("org.example.app", str(tmp_path))
    assert len([args for args in calls if args[0] == "pull"]) == 1
    assert not list(tmp_path.glob("*.zip"))


def test_backup_last_pull_cancellation_preserves_old_zip_and_emits_no_success(tmp_path):
    from pathlib import Path

    worker = AppManagerWorker("mock-device", "backup_app")
    old = tmp_path / "backup_org.example.app.zip"
    old.write_bytes(b"previous backup")
    done, feedback = [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda level, message: feedback.append((level, message)))

    def adb(*args, **kwargs):
        if args[0] == "shell":
            return CommandResult(success=True, output="package:/app/base.apk")
        (Path(args[2]) / "base.apk").write_bytes(b"new apk")
        worker.abort()
        return CommandResult(success=True)

    with (
        patch.object(worker, "_adb", side_effect=adb),
        patch("models.app_manager_worker.shutil.make_archive") as archive,
    ):
        worker._backup_app("org.example.app", str(tmp_path))
    archive.assert_not_called()
    assert old.read_bytes() == b"previous backup"
    assert done == []
    assert feedback and all(level != "success" for level, _ in feedback)


def test_backup_cancel_during_compression_preserves_old_zip(tmp_path):
    from pathlib import Path
    from shutil import make_archive

    worker = AppManagerWorker("mock-device", "backup_app")
    previous = tmp_path / "backup_org.example.app.zip"
    previous.write_bytes(b"previous backup")
    done, feedback = [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda level, message: feedback.append((level, message)))

    def adb(*args, **kwargs):
        if args[0] == "shell":
            return CommandResult(success=True, output="package:/app/base.apk")
        (Path(args[2]) / "base.apk").write_bytes(b"new apk")
        return CommandResult(success=True)

    def compress(*args):
        archive = make_archive(*args)
        worker.abort()
        return archive

    with (
        patch.object(worker, "_adb", side_effect=adb),
        patch("models.app_manager_worker.shutil.make_archive", side_effect=compress),
    ):
        worker._backup_app("org.example.app", str(tmp_path))

    assert previous.read_bytes() == b"previous backup"
    assert list(tmp_path.iterdir()) == [previous]
    assert done == []
    assert feedback and all(level != "success" for level, _ in feedback)
