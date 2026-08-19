"""面向真实 Qt 控件的几何、可见性和文本断言。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import combinations

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEvent, QEventLoop, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget


def mapped_rect(widget: QWidget, ancestor: QWidget) -> QRect:
    """返回控件映射到指定祖先坐标系后的实际矩形。"""

    current = widget
    while current is not None:
        if current is ancestor:
            break
        current = current.parentWidget()
    else:
        raise ValueError("ancestor must be the widget itself or one of its QWidget ancestors")
    top_left = widget.mapTo(ancestor, QPoint(0, 0))
    return QRect(top_left, widget.size())


def _process_events() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def wait_until(app: QApplication, predicate: Callable[[], bool], *, timeout_ms: int = 6000) -> None:
    """在明确 deadline 内让 Qt 事件循环推进至条件成立。

    全量套件运行到末尾时进程内 Qt 对象与延迟删除事件大量累积，单次 processEvents
    调度变慢，1500ms 会出现确定性超时（与具体前置文件无关、单独跑该文件不复现），
    因此把默认 deadline 放宽到 6000ms 以保证顺序无关的稳定性。
    """

    del app
    deadline = QDeadlineTimer(timeout_ms)
    while not predicate():
        if deadline.hasExpired():
            raise AssertionError("condition did not become true before deadline")
        _process_events()


def _geometry_snapshot(widgets: Iterable[QWidget]) -> tuple[tuple[int, int, int, int], ...]:
    return tuple((widget.x(), widget.y(), widget.width(), widget.height()) for widget in widgets)


def wait_for_stable_geometry(
    app: QApplication,
    widgets: QWidget | Iterable[QWidget],
    *,
    timeout_ms: int = 1500,
) -> None:
    """等待至少两次连续的控件几何快照一致。"""

    del app
    tracked_widgets = (widgets,) if isinstance(widgets, QWidget) else tuple(widgets)
    deadline = QDeadlineTimer(timeout_ms)
    previous_snapshot = None
    while True:
        snapshot = _geometry_snapshot(tracked_widgets)
        if snapshot == previous_snapshot:
            return
        if deadline.hasExpired():
            raise AssertionError("geometry did not become stable before deadline")
        previous_snapshot = snapshot
        _process_events()


def assert_positive_geometry(widget: QWidget, ancestor: QWidget | None = None) -> None:
    """断言控件在其自身或祖先坐标中有正面积。"""

    rect = widget.rect() if ancestor is None else mapped_rect(widget, ancestor)
    assert rect.width() > 0 and rect.height() > 0, f"positive geometry required: {rect!r}"


def assert_contained(widget: QWidget, ancestor: QWidget) -> None:
    """断言控件完整位于祖先可用矩形内。"""

    rect = mapped_rect(widget, ancestor)
    assert ancestor.rect().contains(rect), (
        f"widget is not contained: {rect!r} in {ancestor.rect()!r}"
    )


def assert_non_overlapping(widgets: Iterable[QWidget], ancestor: QWidget) -> None:
    """断言同一祖先中的控件矩形没有相交。"""

    widget_list = tuple(widgets)
    for first, second in combinations(widget_list, 2):
        first_rect = mapped_rect(first, ancestor)
        second_rect = mapped_rect(second, ancestor)
        assert not first_rect.intersects(second_rect), (
            f"widgets overlap: {first.objectName() or first!r} {first_rect!r} and "
            f"{second.objectName() or second!r} {second_rect!r}"
        )


def assert_scroll_target_reachable(scroll_area: QScrollArea, target: QWidget) -> None:
    """断言普通目标可完整显示，超宽目标的左右边缘均可到达。"""

    horizontal = scroll_area.horizontalScrollBar()
    vertical = scroll_area.verticalScrollBar()
    viewport_rect = scroll_area.viewport().rect()

    for vertical_value in (vertical.minimum(), vertical.maximum()):
        vertical.setValue(vertical_value)
        scroll_area.ensureWidgetVisible(target, 0, 4)
        _process_events()
        target_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
        if target_rect.top() < viewport_rect.top():
            vertical.setValue(vertical.value() + target_rect.top() - viewport_rect.top())
            _process_events()
            target_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
        elif target_rect.bottom() > viewport_rect.bottom():
            vertical.setValue(vertical.value() + target_rect.bottom() - viewport_rect.bottom())
            _process_events()
            target_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
        assert (
            target_rect.top() >= viewport_rect.top()
            and target_rect.bottom() <= viewport_rect.bottom()
        ), f"scroll target vertical extent is not reachable from {vertical_value}: {target_rect!r}"

    if target.width() <= viewport_rect.width():
        for horizontal_value in (horizontal.minimum(), horizontal.maximum()):
            horizontal.setValue(horizontal_value)
            scroll_area.ensureWidgetVisible(target, 4, 0)
            _process_events()
            target_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
            if target_rect.left() < viewport_rect.left():
                horizontal.setValue(horizontal.value() + target_rect.left() - viewport_rect.left())
                _process_events()
                target_rect = QRect(
                    target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size()
                )
            elif target_rect.right() > viewport_rect.right():
                horizontal.setValue(
                    horizontal.value() + target_rect.right() - viewport_rect.right()
                )
                _process_events()
                target_rect = QRect(
                    target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size()
                )
            assert viewport_rect.left() <= target_rect.left()
            assert target_rect.right() <= viewport_rect.right()
        return

    content = scroll_area.widget()
    assert content is not None
    target_x = target.mapTo(content, QPoint(0, 0)).x()
    horizontal.setValue(max(horizontal.minimum(), min(horizontal.maximum(), target_x)))
    _process_events()
    left_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
    assert viewport_rect.left() <= left_rect.left() <= viewport_rect.right()

    right_value = target_x + target.width() - viewport_rect.width()
    horizontal.setValue(max(horizontal.minimum(), min(horizontal.maximum(), right_value)))
    _process_events()
    right_rect = QRect(target.mapTo(scroll_area.viewport(), QPoint(0, 0)), target.size())
    assert viewport_rect.left() <= right_rect.right() <= viewport_rect.right()


def assert_text_fits(widget: QWidget) -> None:
    """断言单行可见文本可在控件内容宽度内完整显示。"""

    text = getattr(widget, "text", lambda: "")()
    available_width = widget.contentsRect().width()
    required_width = widget.fontMetrics().horizontalAdvance(text)
    assert required_width <= available_width, (
        f"text fits assertion failed: requires {required_width}px "
        f"but only {available_width}px available"
    )


def assert_square(widget: QWidget) -> None:
    """断言控件具有相等的宽高。"""

    assert widget.width() == widget.height(), (
        f"square geometry required: {widget.width()}x{widget.height()}"
    )


def assert_elided_accessible_text(widget: QWidget) -> None:
    """文本发生省略时，断言完整文本可通过辅助信息获得。"""

    text = getattr(widget, "text", lambda: "")()
    elided = widget.fontMetrics().elidedText(
        text,
        Qt.TextElideMode.ElideRight,
        widget.contentsRect().width(),
    )
    if elided == text:
        return
    accessible_text = " ".join(
        value
        for value in (
            widget.toolTip(),
            widget.accessibleName(),
            widget.accessibleDescription(),
        )
        if value
    )
    assert text in accessible_text, (
        "elided text must remain accessible through tooltip or accessible text"
    )
