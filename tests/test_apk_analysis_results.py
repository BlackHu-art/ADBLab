"""验证 APK 分析沿真实结果路由仅保留一次错误，并保留成功字段。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adblab.application.action_results import (
    ActionEnvelope,
    ActionResults,
    capture_action_job,
)
from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers.action_catalog import ACTION_SIGNALS


class _APKResultController(ADBAppMixin, _ADBControllerBase):
    def __init__(self, publish):
        self._shutting_down = False
        self.signals = SimpleNamespace(operation_completed=Mock())
        self.log_service = Mock()
        self.action_results = ActionResults(publish)
        self._handler_map = {"parse_apk_info": self._process_parse_apk_info_result}


def _deliver_apk_result(payload):
    events = []
    controller = _APKResultController(events.append)
    job = controller.action_results.run(
        ACTION_SIGNALS["parse_apk_info_requested"], (),
        lambda: capture_action_job("parse_apk_info_async", "fixture.apk"),
    )
    assert job is not None
    envelope = ActionEnvelope({"apk_path": "fixture.apk", **payload}, job)
    controller._handle_async_response("parse_apk_info_async", envelope)
    return controller, events, envelope


@pytest.mark.parametrize("error", [
    "aapt executable not found in PATH",
    "Android resource packaging tool failed\nerror: invalid APK format",
])
def test_apk_analysis_failure_preserves_original_error_once(error):
    controller, events, envelope = _deliver_apk_result({"success": False, "error": error})

    result = events[-1]
    assert result.state == "failed"
    assert len(result.items) == 1
    assert result.items[0].detail == error
    assert result.message == error
    assert len([event for event in events if event.state != "running"]) == 1
    controller.signals.operation_completed.emit.assert_called_once_with("apk_info", False, error)
    controller.log_service.log.assert_not_called()

    previous_count = len(events)
    controller._handle_async_response("parse_apk_info_async", envelope)
    assert len(events) == previous_count
    assert controller.signals.operation_completed.emit.call_count == 1


def test_apk_analysis_failure_without_error_retains_fallback():
    _, events, _ = _deliver_apk_result({"success": False})

    result = events[-1]
    assert result.state == "failed"
    assert result.items[0].detail == "Unknown error"
    assert len([event for event in events if event.state != "running"]) == 1


def test_apk_analysis_success_preserves_fields_and_raw_output():
    output = "\n".join([
        "package: name='org.example.fixture' versionCode='42' versionName='1.2.3' "
        "compileSdkVersion='35' platformBuildVersionName='15'",
        "sdkVersion:'23'",
        "targetSdkVersion:'35'",
        "application-label:'Fixture App'",
        "application: label='Fixture App' icon='res/mipmap/icon.png'",
        "uses-permission: name='android.permission.INTERNET'",
        "uses-permission: name='android.permission.CAMERA'",
        "uses-feature: name='android.hardware.camera'",
        "uses-feature-not-required: name='android.hardware.bluetooth'",
        "native-code: 'arm64-v8a'",
    ])
    controller, events, _ = _deliver_apk_result({"success": True, "output": output})

    result = events[-1]
    assert result.state == "succeeded"
    assert len(result.items) == 1
    assert result.items[0].detail == output
    for field in (
        "App: Fixture App", "Package: org.example.fixture", "Version: 1.2.3 (Code: 42)",
        "SDK: min=23, target=35, compile=35", "Build: 15", "Icon: res/mipmap/icon.png",
        "Permissions: 2 items", "Features: android.hardware.camera, android.hardware.bluetooth",
        "Architectures: arm64-v8a",
    ):
        assert field in result.message
    assert len([event for event in events if event.state != "running"]) == 1
    controller.signals.operation_completed.emit.assert_called_once_with(
        "apk_info", True, result.message,
    )
    controller.log_service.log.assert_not_called()
