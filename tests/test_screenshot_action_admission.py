"""验证截图按钮、请求准入和取消回调之间的状态收口。"""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QSignalSpy

from adblab.application.action_results import ActionResults
from adblab.application.operations import OperationManager
from controllers._media import ADBMediaMixin
from controllers.signals import ADBControllerSignals
from core.settings_manager import DEFAULTS, AppSettings
from gui.action_feedback import ActionFeedbackPresenter
from gui.features.media import ScreenshotPage
from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.panels.app_panel import AppPanel
from gui.panels.side_panel_signals import SidePanelSignals
from models.adb_model import ADBModelCore, async_command

pytestmark = [pytest.mark.ui, pytest.mark.integration]


class _ScreenshotModel(ADBModelCore):
    """仅替换外部截图工作，保留异步装饰器及其请求、操作身份。"""

    def __init__(self):
        super().__init__()
        self.tasks = []
        self.thread_pool = SimpleNamespace(start=self.tasks.append)
        self.outcome = "success"

    @async_command
    def take_screenshot_async(self, target, path, *, cancelled):
        if self.outcome == "cancelled" or (self.outcome != "late_success" and cancelled()):
            return {"success": False, "cancelled": True, "device_ip": target}
        if self.outcome == "failure":
            return {"success": False, "device_ip": target, "error": "capture failed"}
        image = QImage(2, 2, QImage.Format.Format_RGB32)
        image.fill(0xFF123456)
        assert image.save(path, "PNG")
        return {"success": True, "device_ip": target, "screenshot_path": path}


@pytest.fixture
def screenshot_actions(qt_application, tmp_path, monkeypatch):
    settings = SimpleNamespace(get=lambda key, default=None: DEFAULTS.get(key, default))
    monkeypatch.setattr(AppSettings, "instance", lambda: settings)
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *_args, **_kwargs: None)
    panel_owner = SimpleNamespace(
        signals=SidePanelSignals(), selected_devices=["demo-device"], _package_history=[],
        _font_sm=QFont(), _font_mono=QFont(), _font_base=QFont(),
    )
    panel = AppPanel(panel_owner)
    overview = panel.build_ui(parent=panel)
    panel.connect_signals()
    workspace = WorkspaceFeatureHost("apps", "应用", overview)
    page = ScreenshotPage()
    page.set_device_tools(panel.text_screen_tools, panel.text_screen_tools_parking)
    workspace.register_feature("media", "截图", None, lambda _key: page, requires_device=False)
    workspace.open_feature("media")
    workspace.resize(1000, 700)
    workspace.show()
    qt_application.processEvents()
    assert panel.btn_screenshot.isVisibleTo(workspace)

    model = _ScreenshotModel()
    model.setParent(panel)
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller.operation_manager = OperationManager()
    controller.testing_model = model
    controller.signals = ADBControllerSignals(panel)
    controller.log_service = Mock()
    controller._settings = settings
    controller._get_screenshot_dir = lambda: str(tmp_path)
    controller.action_results = ActionResults(controller.signals.action_result_changed.emit)
    controller._build_handler_map()
    controller.signals.operation_completed.connect(panel.on_operation_completed)
    model.command_finished.connect(controller._handle_async_response)
    frame = SimpleNamespace(
        _closing=False, adb_controller=controller, left_panel=SimpleNamespace(app_panel=panel),
        log_service=SimpleNamespace(diagnostics=SimpleNamespace(private_values=())),
        _device_metadata={},
        _global_device_bar=SimpleNamespace(device_label=lambda _target: "设备 1"),
    )
    presenter = SimpleNamespace(frame=frame, open_task=lambda _request: None)
    presenter.dispatch = MethodType(ActionFeedbackPresenter.dispatch, presenter)
    panel_owner.signals.screenshot_requested.connect(ActionFeedbackPresenter.bind(
        presenter, panel_owner.signals, panel_owner.signals.screenshot_requested,
        controller.take_screenshot,
    ))
    try:
        yield SimpleNamespace(panel=panel, controller=controller, model=model)
    finally:
        controller.action_results.close()
        workspace.shutdown()
        panel.shutdown()
        workspace.close()
        panel.close()


@pytest.mark.parametrize("old_outcome", ["cancelled", "late_success"])
def test_cancelled_screenshot_rejected_retry_does_not_disable_future_capture(
    screenshot_actions, old_outcome,
):
    panel, controller, model = (
        screenshot_actions.panel, screenshot_actions.controller, screenshot_actions.model,
    )
    captures = QSignalSpy(controller.signals.screenshot_captured)
    panel.btn_screenshot.click()
    operation = controller.operation_manager.active_snapshot()[0]
    controller.operation_manager.request_cancel(operation.operation_id)
    assert controller.cancel_screenshot(operation.operation_id)
    assert panel.btn_screenshot.isEnabled()
    assert controller.action_results.recent()[0].state == "running"

    panel.btn_screenshot.click()
    assert len(model.tasks) == 1
    assert panel.btn_screenshot.isEnabled()
    model.outcome = old_outcome
    model.tasks[0].run()
    assert captures.count() == 0
    assert controller.operation_manager.active_count == 0
    assert controller.action_results.recent()[0].state != "running"
    assert panel.btn_screenshot.isEnabled()

    panel.btn_screenshot.click()
    assert len(model.tasks) == 2
    assert not panel.btn_screenshot.isEnabled()
    model.outcome = "success"
    model.tasks[1].run()
    assert panel.btn_screenshot.isEnabled()
    assert captures.count() == 1
    assert controller.action_results.recent()[0].state == "succeeded"


@pytest.mark.parametrize("outcome, expected", [("success", "succeeded"), ("failure", "failed")])
def test_screenshot_completion_allows_reuse_while_duplicate_click_remains_blocked(
    screenshot_actions, outcome, expected,
):
    panel, controller, model = (
        screenshot_actions.panel, screenshot_actions.controller, screenshot_actions.model,
    )
    panel.btn_screenshot.click()
    assert not panel.btn_screenshot.isEnabled()
    panel.btn_screenshot.click()
    panel.signals.screenshot_requested.emit(["demo-device"])
    assert len(model.tasks) == 1
    assert not panel.btn_screenshot.isEnabled()
    model.outcome = outcome
    model.tasks[0].run()
    assert panel.btn_screenshot.isEnabled()
    assert controller.operation_manager.active_count == 0
    assert controller.action_results.recent()[0].state == expected

    panel.btn_screenshot.click()
    assert len(model.tasks) == 2
    model.tasks[1].run()
    assert panel.btn_screenshot.isEnabled()
