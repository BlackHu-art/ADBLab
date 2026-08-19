"""MobilePerf 5037 端口冲突清理路径的契约测试（ADR-0003 Phase 1 重写后）。"""

from unittest.mock import patch

from mobileperf.android.tools.androiddevice import ADB


def test_kill_occupy_5037_uses_process_utils_and_kills_each_listener():
    with (
        patch("core.process_utils.find_pids_listening_on", return_value=[111, 222]),
        patch("core.process_utils.process_name", side_effect=["adb.exe", "ddms.exe"]),
        patch("core.process_utils.kill_process_tree", return_value=(True, "terminated")) as kill,
    ):
        ADB.killOccupy5037Process()

    assert kill.call_count == 2
    assert [call.args[0] for call in kill.call_args_list] == [111, 222]


def test_kill_occupy_5037_no_listener_is_noop():
    with (
        patch("core.process_utils.find_pids_listening_on", return_value=[]),
        patch("core.process_utils.kill_process_tree") as kill,
    ):
        ADB.killOccupy5037Process()

    kill.assert_not_called()


def test_kill_occupy_5037_logs_failure_without_raising():
    with (
        patch("core.process_utils.find_pids_listening_on", return_value=[111]),
        patch("core.process_utils.process_name", return_value="adb.exe"),
        patch("core.process_utils.kill_process_tree", return_value=(False, "access-denied")),
    ):
        ADB.killOccupy5037Process()  # 不应抛出异常，失败只记日志
