"""验证面板内分类栈的导航同步与响应式切换。"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QWidget

from gui.widgets.category_stack import AdaptiveCategoryStack


def _category_stack() -> tuple[AdaptiveCategoryStack, dict[str, QWidget]]:
    stack = AdaptiveCategoryStack("apps")
    pages = {
        "overview": stack.add_category("overview", "概览", (QWidget(),)),
        "packages": stack.add_category("packages", "应用管理", (QWidget(),)),
        "automation": stack.add_category("automation", "自动化", (QWidget(),)),
    }
    return stack, pages


def test_first_category_initializes_stack_pivot_and_combo(qt_application):
    stack, pages = _category_stack()
    try:
        assert stack.category_keys == ("overview", "packages", "automation")
        assert stack.current_key == "overview"
        assert stack.stack.currentWidget() is pages["overview"]
        assert stack.pivot.currentRouteKey() == "apps:overview"
        assert stack.combo.currentData() == "overview"
        assert stack.page("packages") is pages["packages"]
    finally:
        stack.close()


def test_pivot_and_combo_changes_stay_synchronized_and_emit_once(qt_application):
    stack, pages = _category_stack()
    changes = QSignalSpy(stack.current_changed)
    try:
        stack.pivot.widget("apps:packages").click()
        qt_application.processEvents()

        assert stack.current_key == "packages"
        assert stack.stack.currentWidget() is pages["packages"]
        assert stack.pivot.currentRouteKey() == "apps:packages"
        assert stack.combo.currentData() == "packages"
        assert changes.count() == 1
        assert changes.at(0) == ["packages"]

        stack.combo.setCurrentIndex(stack.category_keys.index("automation"))
        qt_application.processEvents()

        assert stack.current_key == "automation"
        assert stack.stack.currentWidget() is pages["automation"]
        assert stack.pivot.currentRouteKey() == "apps:automation"
        assert stack.combo.currentData() == "automation"
        assert changes.count() == 2
        assert changes.at(1) == ["automation"]

        assert stack.set_current("automation") is True
        assert changes.count() == 2
    finally:
        stack.close()


def test_unknown_category_keeps_current_selection(qt_application):
    stack, pages = _category_stack()
    changes = QSignalSpy(stack.current_changed)
    try:
        before = stack.stack.currentWidget()

        assert stack.set_current("missing") is False
        assert stack.current_key == "overview"
        assert stack.stack.currentWidget() is before is pages["overview"]
        assert stack.pivot.currentRouteKey() == "apps:overview"
        assert stack.combo.currentData() == "overview"
        assert changes.count() == 0
    finally:
        stack.close()


def test_navigation_uses_combo_below_compact_width_and_pivot_at_boundary(
    qt_application,
):
    stack, _pages = _category_stack()
    try:
        stack.resize(stack.COMPACT_WIDTH - 1, 360)
        stack.show()
        qt_application.processEvents()

        assert stack.width() == stack.COMPACT_WIDTH - 1
        assert stack.combo.isVisibleTo(stack)
        assert stack.pivot.isHidden()

        stack.resize(stack.COMPACT_WIDTH, 360)
        qt_application.processEvents()

        assert stack.width() == stack.COMPACT_WIDTH
        assert stack.pivot.isVisibleTo(stack)
        assert stack.combo.isHidden()
        assert stack.current_key == "overview"
    finally:
        stack.close()


@pytest.mark.parametrize(
    ("width", "visible_navigation"),
    (
        (AdaptiveCategoryStack.COMPACT_WIDTH - 1, "combo"),
        (AdaptiveCategoryStack.COMPACT_WIDTH, "pivot"),
    ),
)
def test_navigation_can_be_hidden_restored_and_switched_programmatically(
    qt_application,
    width,
    visible_navigation,
):
    stack, pages = _category_stack()
    try:
        stack.resize(width, 360)
        stack.show()
        qt_application.processEvents()

        stack.set_navigation_visible(False)
        qt_application.processEvents()

        assert stack.pivot.isHidden()
        assert stack.combo.isHidden()
        assert stack.stack.isVisibleTo(stack)
        assert stack.set_current("packages") is True
        assert stack.current_key == "packages"
        assert stack.stack.currentWidget() is pages["packages"]
        assert stack.pivot.currentRouteKey() == "apps:packages"
        assert stack.combo.currentData() == "packages"

        stack.set_navigation_visible(True)
        qt_application.processEvents()

        assert stack.pivot.isVisibleTo(stack) is (visible_navigation == "pivot")
        assert stack.combo.isVisibleTo(stack) is (visible_navigation == "combo")
        assert stack.current_key == "packages"
        assert stack.stack.currentWidget() is pages["packages"]
    finally:
        stack.close()


def test_resize_while_navigation_hidden_does_not_reveal_controls(qt_application):
    stack, _pages = _category_stack()
    try:
        stack.resize(stack.COMPACT_WIDTH, 360)
        stack.show()
        qt_application.processEvents()
        stack.set_navigation_visible(False)

        stack.resize(stack.COMPACT_WIDTH - 1, 360)
        qt_application.processEvents()

        assert stack.pivot.isHidden()
        assert stack.combo.isHidden()

        stack.set_navigation_visible(True)
        qt_application.processEvents()

        assert stack.pivot.isHidden()
        assert stack.combo.isVisibleTo(stack)
    finally:
        stack.close()


def test_hidden_long_category_does_not_keep_scroll_height(qt_application):
    """分类切换后只用当前页估算高度，隐藏长页不能继续撑大外层滚动区。"""

    stack = AdaptiveCategoryStack("height")
    short_content = QWidget()
    short_content.setFixedHeight(40)
    tall_content = QWidget()
    tall_content.setFixedHeight(260)
    stack.add_category("short", "简短", (short_content,))
    stack.add_category("tall", "较长", (tall_content,))
    try:
        short_height = stack.stack.sizeHint().height()
        stack.set_current("tall")
        tall_height = stack.stack.sizeHint().height()
        stack.set_current("short")

        assert tall_height > short_height
        assert stack.stack.sizeHint().height() == short_height
    finally:
        stack.close()


def test_empty_and_duplicate_category_keys_are_rejected(qt_application):
    with pytest.raises(ValueError, match="route_prefix"):
        AdaptiveCategoryStack(" ")

    stack = AdaptiveCategoryStack("system")
    try:
        stack.add_category(" diagnostics ", "诊断")

        with pytest.raises(ValueError, match="duplicate category key"):
            stack.add_category("diagnostics", "重复诊断")
        with pytest.raises(ValueError, match="category key"):
            stack.add_category(" ", "空分类")

        assert stack.category_keys == ("diagnostics",)
        assert stack.stack.count() == 1
        assert stack.combo.count() == 1
    finally:
        stack.close()
