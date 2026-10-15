"""方向动作使用设备当前基础尺寸，不把自然方向或旧缓存固定为竖屏。"""

import threading

import pytest

from core.adb_bridge import ADBBridge
from core.exec import CommandResult
from services.remote.control_service import RemoteControlService


@pytest.mark.parametrize("initial_rotation", [0, 1, 2, 3])
@pytest.mark.parametrize(("size", "action", "expected_rotation"), [
    ((1080, 2400), "rotate_portrait", 0),
    ((1080, 2400), "rotate_landscape", 1),
    ((2560, 1600), "rotate_portrait", 1),
    ((2560, 1600), "rotate_landscape", 0),
])
def test_orientation_uses_unrotated_device_size_for_every_current_rotation(
    monkeypatch, initial_rotation, size, action, expected_rotation,
):
    bridge = ADBBridge(path="unused-adb")
    commands = []
    rotation = initial_rotation

    def shell(command, *, device_id):
        nonlocal rotation
        assert device_id == "screen-a"
        commands.append(command)
        if command == "wm size":
            return CommandResult(True, f"Physical size: {size[0]}x{size[1]}\n")
        if command.startswith("settings put system user_rotation "):
            rotation = int(command.rsplit(" ", 1)[1])
        return CommandResult(True)

    monkeypatch.setattr(bridge, "shell", shell)
    service = RemoteControlService(bridge)
    service.remember_dimensions("screen-a", (size[1], size[0]))

    result = service.perform_action("screen-a", action)

    assert result.success
    assert commands == [
        "wm size", "settings put system accelerometer_rotation 0",
        f"settings put system user_rotation {expected_rotation}",
    ]
    width, height = size if rotation % 2 == 0 else (size[1], size[0])
    assert (height > width) == (action == "rotate_portrait")


@pytest.mark.parametrize(("output", "rotation"), [
    ("Physical size: 1080x2400\nOverride size: 1920x1080\n", 1),
    ("Physical size: 2560x1600\nOverride size: 1080x1920\n", 0),
])
def test_orientation_uses_effective_override_instead_of_cached_or_physical_size(
    monkeypatch, output, rotation,
):
    bridge = ADBBridge(path="unused-adb")
    commands = []

    def shell(command, *, device_id):
        assert device_id == "screen-a"
        commands.append(command)
        return CommandResult(True, output if command == "wm size" else "")

    monkeypatch.setattr(bridge, "shell", shell)
    service = RemoteControlService(bridge)
    service.remember_dimensions("screen-a", (600, 800))

    assert service.rotate_portrait("screen-a").success

    assert commands == [
        "wm size", "settings put system accelerometer_rotation 0",
        f"settings put system user_rotation {rotation}",
    ]


def test_orientation_requeries_each_target_and_does_not_reuse_previous_device(monkeypatch):
    bridge = ADBBridge(path="unused-adb")
    sizes = {"screen-a": "1080x2400", "screen-b": "2560x1600"}
    commands = []

    def shell(command, *, device_id):
        commands.append((device_id, command))
        output = f"Physical size: {sizes[device_id]}" if command == "wm size" else ""
        return CommandResult(True, output)

    monkeypatch.setattr(bridge, "shell", shell)
    service = RemoteControlService(bridge)
    for device in ("screen-a", "screen-b"):
        assert service.rotate_portrait(device).success
    sizes["screen-a"] = "2400x1080"
    assert service.rotate_portrait("screen-a").success

    assert commands == [
        ("screen-a", "wm size"),
        ("screen-a", "settings put system accelerometer_rotation 0"),
        ("screen-a", "settings put system user_rotation 0"),
        ("screen-b", "wm size"),
        ("screen-b", "settings put system accelerometer_rotation 0"),
        ("screen-b", "settings put system user_rotation 1"),
        ("screen-a", "wm size"),
        ("screen-a", "settings put system accelerometer_rotation 0"),
        ("screen-a", "settings put system user_rotation 1"),
    ]


@pytest.mark.parametrize("action", ["rotate_portrait", "rotate_landscape"])
@pytest.mark.parametrize("cache_ttl", [-1.0, 30.0])
@pytest.mark.parametrize("query_result", [
    CommandResult(False, "Physical size: 1080x2400", "denied", 1),
    CommandResult(True, "unknown"),
    CommandResult(True, "Physical size: 0x2400"),
    CommandResult(True, "Physical size: 1200x1200"),
])
def test_unknown_or_ambiguous_orientation_never_changes_settings(
    monkeypatch, action, query_result, cache_ttl,
):
    bridge = ADBBridge(path="unused-adb")
    commands = []

    def shell(command, *, device_id):
        commands.append(command)
        return query_result

    monkeypatch.setattr(bridge, "shell", shell)
    service = RemoteControlService(bridge, dimension_ttl_seconds=cache_ttl)
    service.remember_dimensions("screen-a", (1080, 2400))

    assert service.perform_action("screen-a", action) is False

    assert commands == ["wm size"]


@pytest.mark.parametrize("cancel_before_query", [False, True])
def test_orientation_cancellation_prevents_setting_writes(monkeypatch, cancel_before_query):
    bridge = ADBBridge(path="unused-adb")
    stopped = threading.Event()
    predicate = stopped.is_set
    commands = []
    if cancel_before_query:
        stopped.set()

    def shell(command, *, device_id, cancelled):
        assert device_id == "screen-a" and cancelled is predicate
        commands.append(command)
        stopped.set()
        return CommandResult(True, "Physical size: 2560x1600")

    monkeypatch.setattr(bridge, "shell", shell)

    assert RemoteControlService(bridge).rotate_portrait("screen-a", cancelled=predicate) is False

    assert commands == ([] if cancel_before_query else ["wm size"])


def test_reset_rotation_keeps_existing_auto_rotate_operation_without_size_query(monkeypatch):
    bridge = ADBBridge(path="unused-adb")
    commands = []

    def shell(command, *, device_id):
        commands.append((device_id, command))
        return CommandResult(True)

    monkeypatch.setattr(bridge, "shell", shell)

    assert RemoteControlService(bridge).reset_rotation("screen-a").success

    assert commands == [("screen-a", "settings put system accelerometer_rotation 1")]
