"""Remote 手势使用当前逻辑屏幕，设置入口保持明确且可取消。"""

import threading
from unittest.mock import Mock

import pytest

from core.exec import CommandResult
from services.remote.control_mapping import parse_input_viewport_dimensions
from services.remote.control_service import RemoteControlService

PORTRAIT_VIEWPORT = (
    "Viewport INTERNAL: displayId=0, uniqueId=fixture, port=0, orientation=0, "
    "logicalFrame=[0, 0, 1080, 2400], physicalFrame=[0, 0, 1080, 2400], "
    "deviceSize=[1080, 2400], isActive=[1]"
)
LANDSCAPE_VIEWPORT = (
    "Viewport INTERNAL: displayId=0, uniqueId=fixture, port=0, orientation=1, "
    "logicalFrame=[0, 0, 2400, 1080], physicalFrame=[0, 0, 1080, 2400], "
    "deviceSize=[1080, 2400], isActive=[1]"
)


@pytest.mark.parametrize(
    ("action", "command"),
    [
        ("swipe_up", "swipe 1200 972 1200 108 300"),
        ("swipe_down", "swipe 1200 108 1200 972 300"),
        ("swipe_left", "swipe 2160 540 240 540 300"),
        ("swipe_right", "swipe 240 540 2160 540 300"),
        ("notif_expand", "swipe 1200 0 1200 1079 300"),
        ("notif_collapse", "swipe 1200 1079 1200 0 300"),
    ],
)
def test_gestures_use_current_landscape_viewport_instead_of_natural_dimensions(action, command):
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    adb.shell.return_value = CommandResult(success=True, output=LANDSCAPE_VIEWPORT)
    adb.shell_input.return_value = True
    service = RemoteControlService(adb)
    service.remember_dimensions("device-a", ["1080", "2400"])

    assert service.perform_action("device-a", action) is True

    adb.shell_input.assert_called_once_with(command, device_id="device-a")
    adb.shell.assert_called_once_with("dumpsys input", device_id="device-a")
    adb.get_dimensions.assert_not_called()


def test_gestures_refresh_viewport_after_external_rotation():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    adb.shell.side_effect = [
        CommandResult(success=True, output=PORTRAIT_VIEWPORT),
        CommandResult(success=True, output=LANDSCAPE_VIEWPORT),
    ]
    adb.shell_input.return_value = True
    service = RemoteControlService(adb)

    service.directional_swipe("device-a", "left")
    service.directional_swipe("device-a", "left")

    assert [call.args[0] for call in adb.shell_input.call_args_list] == [
        "swipe 972 1200 108 1200 300", "swipe 2160 540 240 540 300",
    ]


@pytest.mark.parametrize("action", ["swipe_up", "notif_expand", "notif_collapse"])
@pytest.mark.parametrize(
    "result",
    [CommandResult(success=False, error="denied"), CommandResult(success=True, output="unknown")],
)
def test_failed_viewport_query_does_not_guess_or_inject_coordinates(action, result):
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    adb.shell.return_value = result
    service = RemoteControlService(adb)
    service.remember_dimensions("device-a", ["1080", "2400"])

    assert service.perform_action("device-a", action) is False

    adb.shell_input.assert_not_called()


@pytest.mark.parametrize("action", ["swipe_left", "notif_expand", "notif_collapse"])
def test_cancellation_during_viewport_query_prevents_following_input(action):
    cancel_event = threading.Event()
    predicate = cancel_event.is_set
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    adb.shell_input.return_value = True

    def query(command, *, device_id, cancelled):
        assert command == "dumpsys input" and device_id == "device-a"
        assert cancelled is predicate
        cancel_event.set()
        return CommandResult(success=True, output=LANDSCAPE_VIEWPORT)

    adb.shell.side_effect = query
    service = RemoteControlService(adb)

    assert service.perform_action("device-a", action, cancelled=predicate) is False

    adb.shell_input.assert_not_called()


def test_settings_opens_settings_activity_and_preserves_cancellation_and_result():
    predicate = threading.Event().is_set
    adb = Mock()
    result = CommandResult(success=False, error="activity unavailable")
    adb.shell.return_value = result
    service = RemoteControlService(adb)

    assert service.send_keyevent("device-a", "SETTINGS", cancelled=predicate) is result

    adb.shell.assert_called_once_with(
        "am start -a android.settings.SETTINGS 2>&1", device_id="device-a", cancelled=predicate,
    )
    adb.shell_input.assert_not_called()


@pytest.mark.parametrize(
    "output",
    [
        "Error: Activity not started, unable to resolve Intent",
        "Error type 3\nActivity class does not exist.",
        "java.lang.SecurityException: Permission Denial",
        "Permission Denial: starting Intent",
    ],
)
def test_settings_does_not_report_zero_exit_am_error_as_success(output):
    adb = Mock()
    adb.shell.return_value = CommandResult(success=True, output=output)

    assert RemoteControlService(adb).send_keyevent("device-a", "SETTINGS") is False

    adb.shell_input.assert_not_called()


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (PORTRAIT_VIEWPORT, (1080, 2400)),
        (LANDSCAPE_VIEWPORT, (2400, 1080)),
        (LANDSCAPE_VIEWPORT.replace("orientation=1", "orientation=3"), (2400, 1080)),
        (LANDSCAPE_VIEWPORT.replace("2400, 1080]", "1280, 720]", 1), (1280, 720)),
        (LANDSCAPE_VIEWPORT.replace(", isActive=[1]", ""), (2400, 1080)),
        (
            "DisplayViewport{type=INTERNAL, valid=true, isActive=true, displayId=0, "
            "orientation=1, logicalFrame=Rect(0, 0 - 2400, 1080), "
            "physicalFrame=Rect(0, 0 - 1080, 2400)}", (2400, 1080),
        ),
        (
            LANDSCAPE_VIEWPORT.replace("displayId=0", "displayId=2")
            + "\n" + PORTRAIT_VIEWPORT, (1080, 2400),
        ),
        (LANDSCAPE_VIEWPORT.replace("displayId=0", "displayId=10"), None),
        (LANDSCAPE_VIEWPORT.replace("displayId=0", "displayId=-1"), None),
        (LANDSCAPE_VIEWPORT.replace("isActive=[1]", "isActive=[0]"), None),
        (LANDSCAPE_VIEWPORT.replace("isActive=[1]", "isActive=false"), None),
        (LANDSCAPE_VIEWPORT.replace("[0, 0, 2400, 1080]", "[10, 0, 2400, 1080]"), None),
        (LANDSCAPE_VIEWPORT.replace("[0, 0, 2400, 1080]", "[0, 0, 0, 1080]"), None),
        (LANDSCAPE_VIEWPORT.replace("logicalFrame=", "unrecognizedFrame="), None),
        (LANDSCAPE_VIEWPORT + "\n" + PORTRAIT_VIEWPORT, None),
        (LANDSCAPE_VIEWPORT + "\n" + LANDSCAPE_VIEWPORT, (2400, 1080)),
        (
            "DisplayViewport{valid=false, displayId=0, logicalFrame=Rect(0, 0 - 1080, 2400)}",
            None,
        ),
        (
            "DisplayViewport{displayId=0, logicalFrame=Rect(0, 0 - 1080, 2400)}",
            None,
        ),
        (
            "mViewports=[DisplayViewport{valid=true, displayId=1, "
            "logicalFrame=Rect(0, 0 - 800, 600)}, "
            "DisplayViewport{valid=true, displayId=0, logicalFrame=Rect(0, 0 - 2400, 1080)}]",
            (2400, 1080),
        ),
        (
            "mViewports=[DisplayViewport{valid=true, displayId=0, "
            "logicalFrame=Rect(0, 0 - 800, 600)}, "
            "DisplayViewport{valid=true, displayId=0, logicalFrame=Rect(0, 0 - 2400, 1080)}]",
            None,
        ),
        ("Physical size: 1080x2400\nOverride size: 720x1280", None),
    ],
)
def test_input_viewport_dimensions_only_accept_current_default_logical_region(output, expected):
    assert parse_input_viewport_dimensions(output) == expected


@pytest.mark.parametrize("action", ["swipe_up", "notif_expand", "notif_collapse"])
def test_cancelled_action_does_not_start_viewport_query(action):
    adb = Mock()

    assert RemoteControlService(adb).perform_action(
        "device-a", action, cancelled=lambda: True,
    ) is False

    adb.shell.assert_not_called()
    adb.shell_input.assert_not_called()


@pytest.mark.parametrize("size", [(1, 1), (8, 12)])
@pytest.mark.parametrize(
    "action",
    ["swipe_up", "swipe_down", "swipe_left", "swipe_right", "notif_expand", "notif_collapse"],
)
def test_small_valid_viewport_never_injects_out_of_bounds_coordinates(size, action):
    width, height = size
    adb = Mock()
    adb.shell.return_value = CommandResult(
        success=True,
        output=(
            f"Viewport INTERNAL: displayId=0, logicalFrame=[0, 0, {width}, {height}], "
            "isActive=[1]"
        ),
    )
    adb.shell_input.return_value = True

    assert RemoteControlService(adb).perform_action("device-a", action) is True

    command = adb.shell_input.call_args.args[0]
    x1, y1, x2, y2 = map(int, command.split()[1:5])
    assert 0 <= x1 < width and 0 <= x2 < width
    assert 0 <= y1 < height and 0 <= y2 < height
