"""尺寸输出经真实桥接解析后驱动 Remote 坐标，不连接设备。"""

from unittest.mock import Mock

import pytest

from core.adb_bridge import ADBBridge
from core.exec import CommandResult
from services.remote.control_service import RemoteControlService
from services.remote.scrcpy_service import ScrcpyService


@pytest.mark.parametrize("old_cache", [False, True])
def test_override_dimensions_reach_control_coordinates(monkeypatch, old_cache):
    bridge = ADBBridge(path="unused-adb")
    monkeypatch.setattr(bridge, "shell", Mock(return_value=CommandResult(
        True, "Physical size: 1080x2400\nOverride size: 720x1280\n", "", 0,
    )))
    send = Mock()
    monkeypatch.setattr(bridge, "shell_input", send)
    service = RemoteControlService(adb=bridge, dimension_ttl_seconds=-1)
    if old_cache:
        service.remember_dimensions("test-device", ["1080", "2400"])
    service.directional_swipe("test-device", "up")
    send.assert_called_once_with("swipe 360 1152 360 128 300", device_id="test-device")


@pytest.mark.parametrize(("output", "expected"), [
    ("Physical size: 1080x2400\n", ["1080", "2400"]),
    ("Override size: 720x1280\nPhysical size: 1080x2400", ["720", "1280"]),
    ("Physical size: 1080x2400\nOverride size: 0x1280", ["1080", "2400"]),
    ("Override size: -1x1280", None),
    ("Override size: 720x1280 trailing", None),
    ("error: Physical size: 720x1280", None),
    ("Override size: 720x0", None),
    ("", None),
])
def test_bridge_and_scrcpy_accept_same_valid_dimensions(monkeypatch, output, expected):
    result = CommandResult(True, output, "", 0)
    bridge = ADBBridge(path="unused-adb")
    monkeypatch.setattr(bridge, "shell", Mock(return_value=result))
    service = ScrcpyService(command_runner=Mock(run=Mock(return_value=result)))
    assert bridge.get_dimensions("test-device") == expected
    assert service.device_info("unused-adb", "test-device") == (
        "x".join(expected) if expected else ""
    )


def test_failed_dimensions_query_never_uses_output_or_error(monkeypatch):
    result = CommandResult(False, "Physical size: 1080x2400", "Override size: 720x1280", 1)
    bridge = ADBBridge(path="unused-adb")
    monkeypatch.setattr(bridge, "shell", Mock(return_value=result))
    service = ScrcpyService(command_runner=Mock(run=Mock(return_value=result)))
    assert bridge.get_dimensions("test-device") is None
    assert service.device_info("unused-adb", "test-device") == ""
