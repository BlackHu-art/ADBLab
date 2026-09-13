"""堆转储只处理本工具清单中的精确路径。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from core.adb_transport import ExecutionResult
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.heap_ownership import HeapOwnership
from mobileperf.android.startup import StartUp
from mobileperf.android.tools.androiddevice import ADB


def test_startup_never_selects_public_files_by_package_substring(monkeypatch, tmp_path):
    monkeypatch.setattr(RuntimeData, "package_save_path", str(tmp_path))
    adb = SimpleNamespace(
        list_dir=Mock(return_value=["com.example.app.notes.txt", "other-com.example.app.hprof"]),
        is_overtime_days=Mock(return_value=True), delete_file=Mock(), pull_file=Mock(),
        cleanup_owned_heapdumps=Mock(), pull_owned_heapdumps=Mock(),
    )
    startup = SimpleNamespace(device=SimpleNamespace(adb=adb), packages=["com.example.app"])
    StartUp.clear_heapdump(startup)
    StartUp.pull_heapdump(startup)
    adb.list_dir.assert_not_called()
    adb.delete_file.assert_not_called()
    adb.pull_file.assert_not_called()
    adb.cleanup_owned_heapdumps.assert_called_once()
    adb.pull_owned_heapdumps.assert_called_once()


def test_manifest_rejects_unknown_paths_packages_and_other_devices(tmp_path):
    owned = HeapOwnership(str(tmp_path), "device-one")
    path = owned.reserve("com.example.app")
    data = json.loads(owned.path.read_text())
    data["files"].extend([
        {**data["files"][0], "path": "/data/local/tmp/com.example.app.hprof"},
        {**data["files"][0], "path": "/data/local/tmp/../valuable.hprof"},
        {**data["files"][0], "package": "../com.example.app"},
    ])
    owned.path.write_text(json.dumps(data))
    assert [row["path"] for row in owned.entries(["com.example.app"])] == [path]
    assert owned.entries(["com.example.app2"]) == []
    assert HeapOwnership(str(tmp_path), "device-two").entries() == []
    assert "device-one" not in owned.path.read_text()


def test_failed_pull_is_retained_and_successful_retry_cleans_exact_owned_path(tmp_path):
    owned = HeapOwnership(str(tmp_path), "device")
    path = owned.reserve("com.example.app")
    adb = ADB.__new__(ADB)
    adb._device_id = "device"
    adb._execution = None
    command = Mock(return_value=ExecutionResult(kind="completed", returncode=1))
    adb._owned_heap_command = command
    adb.pull_owned_heapdumps(str(tmp_path), ["com.example.app"])
    assert owned.entries()[0]["pulled"] is False
    command.assert_called_once_with(["pull", path, str(tmp_path)], 180)
    command.reset_mock()
    command.return_value = ExecutionResult(kind="completed", returncode=0)
    adb.pull_owned_heapdumps(str(tmp_path), ["com.example.app"])
    assert owned.entries() == []
    assert command.call_count == 2
    assert command.call_args.args[0] == ["shell", f"rm -f -- '{path}'"]


def test_cancelled_dump_never_reserves_or_launches(tmp_path):
    adb = ADB.__new__(ADB)
    adb._execution = SimpleNamespace(_cancelled=lambda _: True)
    adb._owned_heap_command = Mock()
    adb.dumpheap("com.example.app", str(tmp_path))
    adb._owned_heap_command.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_copied_manifest_cannot_authorize_another_task_namespace(tmp_path):
    first = HeapOwnership(str(tmp_path / "first"), "device")
    first.reserve("com.example.app")
    second = HeapOwnership(str(tmp_path / "second"), "device")
    second.root.mkdir()
    second.path.write_bytes(first.path.read_bytes())
    assert second.entries() == []


def test_cleanup_retains_unpulled_recent_and_failed_delete_entries(tmp_path):
    owned = HeapOwnership(str(tmp_path), "device")
    unpulled = owned.reserve("com.example.app")
    pulled = owned.reserve("com.example.app")
    owned.mark_pulled(pulled)
    adb = ADB.__new__(ADB)
    adb._device_id = "device"
    adb._execution = None
    adb._owned_heap_command = Mock(return_value=ExecutionResult(kind="completed", returncode=1))
    adb.cleanup_owned_heapdumps(str(tmp_path), older_than_days=3)
    adb._owned_heap_command.assert_not_called()
    adb.cleanup_owned_heapdumps(str(tmp_path))
    adb._owned_heap_command.assert_called_once_with(["shell", f"rm -f -- '{pulled}'"], 10)
    assert {row["path"] for row in owned.entries()} == {unpulled, pulled}
