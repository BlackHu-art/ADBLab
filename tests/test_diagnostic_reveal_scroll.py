"""诊断新结果只纵向定位，不横移页面，也不滚动已经隐藏的结果。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from controllers.signals import ADBControllerSignals
from gui.action_feedback import ActionFeedbackPresenter
from gui.widgets.action_result_view import ActionResultView
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def reveal_host(qt_application, monkeypatch):
    """保留真实呈现器、结果信号与滚动容器，仅替换业务及文件服务。"""
    frame = QWidget()
    frame.resize(480, 480)
    scroll = QScrollArea(frame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    layout = QVBoxLayout(frame)
    layout.addWidget(scroll)
    content = QWidget()
    content.setFixedSize(1000, 1600)
    scroll.setWidget(content)
    view = ActionResultView(content, diagnostic=True)
    view.setGeometry(16, 1100, 950, 360)
    task_view = ActionResultView(frame)
    frame._closing = False
    frame.left_panel = SimpleNamespace(
        _apps_tab=SimpleNamespace(diagnostic_results=view, report_artifacts=Mock()),
    )
    frame._task_page = SimpleNamespace(
        action_results=task_view, present_action_result=Mock(),
    )
    frame.adb_controller = SimpleNamespace(signals=ADBControllerSignals())
    frame.run_library = Mock()
    frame.log_service = Mock(diagnostics=SimpleNamespace(entries=[]))
    frame._settings_page = Mock()
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *_args, **_kwargs: None)
    presenter = ActionFeedbackPresenter(frame)
    frame.show()
    wait_for_stable_geometry(qt_application, (frame, scroll, content))
    yield SimpleNamespace(frame=frame, scroll=scroll, content=content, view=view,
                          presenter=presenter)
    frame.close()


def _publish_diagnostic(host):
    result = ActionResult(
        "cpu-query", ActionSpec("cpuinfo", "apps.diagnostics", "CPU 负载", "text"),
        ("fixture-device",), 1, "succeeded",
        items=(ActionItem("cpu-job", "fixture-device", "设备 1", "succeeded",
                          "CPU fixture\n3%"),),
        finished_at=2,
    )
    host.frame.adb_controller.signals.action_result_changed.emit(result)


@pytest.mark.parametrize("horizontal_position", [0, 80])
def test_new_diagnostic_reveals_vertically_without_moving_page_sideways(
    reveal_host, qt_application, horizontal_position,
):
    host = reveal_host
    bar = host.scroll.horizontalScrollBar()
    assert bar.maximum() > horizontal_position
    bar.setValue(horizontal_position)
    before_x = host.content.mapTo(host.scroll.viewport(), QPoint()).x()
    moved = []
    bar.valueChanged.connect(moved.append)

    _publish_diagnostic(host)
    wait_until(qt_application, lambda: host.scroll.verticalScrollBar().value() > 0)

    assert host.view.output.toPlainText() == "CPU fixture\n3%"
    assert bar.value() == horizontal_position
    assert moved == [], "结果定位不能短暂横移再复位"
    assert host.content.mapTo(host.scroll.viewport(), QPoint()).x() == before_x
    center = host.view.mapTo(host.scroll.viewport(), host.view.rect().center())
    assert 0 <= center.y() < host.scroll.viewport().height()


def test_hidden_diagnostic_does_not_scroll_when_queued_reveal_runs(reveal_host, qt_application):
    host = reveal_host
    _publish_diagnostic(host)
    host.view.hide()
    qt_application.processEvents()

    assert host.scroll.horizontalScrollBar().value() == 0
    assert host.scroll.verticalScrollBar().value() == 0
