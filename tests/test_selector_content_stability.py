"""观察实际绘制及同步高度变化，覆盖最终几何断言无法发现的列表闪跳。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar

pytestmark = pytest.mark.ui


@pytest.fixture(params=[12, 22], ids=["normal-font", "large-font"])
def content_selector(qt_application, monkeypatch, request):
    font_size = request.param
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    window = QWidget()
    window.resize(900, 800)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    bar = DeviceContextBar(window)
    body = QWidget(window)
    body_layout = QVBoxLayout(body)
    body_layout.addWidget(QPushButton("正文操作", body))
    body_layout.addStretch(1)
    layout.addWidget(bar)
    layout.addWidget(body, 1)
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    bar.set_device_labels({"demo-a": "V2458A", "demo-b": "23113RKC6C"})
    bar.set_device_details({
        "demo-a": {"brand": "vivo", "android_version": "16", "connection": "USB"},
        "demo-b": {"brand": "Redmi", "android_version": "15", "connection": "模拟器"},
    })
    window.show()
    window.activateWindow()
    qt_application.processEvents()
    yield window, bar
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait_for_transition(bar):
    # 只推进事件循环，不主动 activate 布局，否则会掩盖到达 Paint 的过渡错位。
    for _ in range(100):
        QTest.qWait(10)
        if (bar._selector_animation.state() == QAbstractAnimation.State.Stopped
                and not bar._selector_release_pending):
            QTest.qWait(20)
            return
    pytest.fail("设备列表过渡未完成")


def _rect_in_window(widget, window):
    position = widget.mapTo(window, QPoint())
    return position.x(), position.y(), widget.width(), widget.height()


class _PaintPositions(QObject):
    def __init__(self, window, widgets):
        super().__init__(window)
        self.window = window
        self.positions = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.positions[watched].append(_rect_in_window(watched, self.window))
        return False


@pytest.mark.parametrize("phase", ["first-open", "collapse", "reopen"])
def test_visible_toolbar_and_device_fields_keep_their_painted_positions(
    content_selector, phase,
):
    window, bar = content_selector
    bar.open_picker()
    if phase != "first-open":
        _wait_for_transition(bar)
        bar.collapse_selector(animated=phase == "collapse")
        if phase == "reopen":
            QTest.qWait(20)
            bar.open_picker()
    picker = bar._picker
    widgets = [picker.summary_label, picker.clear_button]
    for row in picker._rows.values():
        widgets.extend(getattr(row, name) for name in (
            "brand_label", "name_label", "version_label", "connection_label",
        ))
    observer = _PaintPositions(window, widgets)
    _wait_for_transition(bar)

    # 对每个实际绘制的字段取样，既覆盖首帧前后，也覆盖列表收起时的头部拉伸。
    for widget, positions in observer.positions.items():
        expected = _rect_in_window(widget, window)
        assert len(positions) >= 2, (phase, widget.text(), positions)
        assert set(positions) == {expected}, (phase, widget.text(), positions, expected)


@pytest.mark.parametrize("fraction", [.35, .65])
def test_reversing_animation_never_applies_old_progress_before_restart(
    content_selector, fraction,
):
    _window, bar = content_selector
    bar.open_picker()
    animation = bar._selector_animation
    animation.pause()
    animation.setCurrentTime(round(animation.duration() * fraction))
    starting_height = bar._selector_reveal.height()
    assert 0 < starting_height < bar._selector_target_height
    synchronous_heights = []
    animation.valueChanged.connect(
        lambda _value: synchronous_heights.append(bar._selector_reveal.height()),
    )

    bar.collapse_selector()

    # 尚未推进事件循环；重新设置 duration 不应先跳到旧时间对应的结束位置再回退。
    assert all(height == starting_height for height in synchronous_heights), synchronous_heights
    assert bar._selector_reveal.height() == starting_height
    _wait_for_transition(bar)
    assert not bar.is_selector_expanded and not bar._picker.isVisible()
