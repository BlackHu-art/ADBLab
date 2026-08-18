"""验证严格整数输入与预设菜单控件。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QLocale, QRect, Qt
from PySide6.QtGui import QColor, QImage, QValidator
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QLineEdit,
    QStyle,
    QStyleOptionSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.styles import BaseStyles
from gui.widgets.preset_spin_box import PresetSpinBox, StrictIntSpinBox
from utils.resource_path import setup_qt_search_paths


def _region_contains_contrasting_pixel(
    image: QImage,
    rect: QRect,
    background: QColor,
    *,
    minimum_delta: int = 50,
) -> bool:
    """返回真实渲染区域中是否存在与按钮背景明显不同的像素。"""

    for x in range(max(0, rect.left()), min(image.width(), rect.right() + 1)):
        for y in range(max(0, rect.top()), min(image.height(), rect.bottom() + 1)):
            actual = image.pixelColor(x, y)
            delta = max(
                abs(actual.red() - background.red()),
                abs(actual.green() - background.green()),
                abs(actual.blue() - background.blue()),
            )
            if delta >= minimum_delta:
                return True
    return False


def _render_spin_subcontrols(qt_application, theme: str, *, enabled: bool):
    """按实际 QSS 渲染 spinbox，并返回上下按钮区域。"""

    setup_qt_search_paths()
    BaseStyles.switch_theme(theme)
    spin = StrictIntSpinBox(minimum=0, maximum=100, value=5)
    spin.setStyleSheet(BaseStyles.INPUT_STYLE())
    spin.resize(160, 36)
    spin.setEnabled(enabled)
    spin.show()
    qt_application.processEvents()

    option = QStyleOptionSpinBox()
    spin.initStyleOption(option)
    image = spin.grab().toImage()
    regions = tuple(
        spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            subcontrol,
            spin,
        )
        for subcontrol in (
            QStyle.SubControl.SC_SpinBoxUp,
            QStyle.SubControl.SC_SpinBoxDown,
        )
    )
    spin.close()
    return image, regions


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1,000",
        "1.000",
        " 15",
        "15 ",
        "+15",
        "-1",
        "abc",
        "101",
        "１５",
        "١٥",
        "0" * 256,
    ],
)
def test_strict_spin_rejects_noncanonical_or_out_of_range_text(qt_application, text):
    """放宽严格词法会让分组符、Unicode 数字或越界值进入业务配置。"""

    spin = StrictIntSpinBox(minimum=0, maximum=100)
    spin.lineEdit().setText(text)

    assert spin.input_is_acceptable() is False


def test_strict_spin_validator_and_parser_share_ascii_decimal_rule(qt_application):
    """校验器与提交解析分叉会造成界面可输入但无法提交的状态。"""

    spin = StrictIntSpinBox(minimum=1, maximum=100)

    state, _text, _position = spin.validate("15", 2)
    assert state is QValidator.State.Acceptable
    assert spin.valueFromText("15") == 15

    for text in ("1,000", "１５", "101"):
        state, _text, _position = spin.validate(text, len(text))
        assert state is not QValidator.State.Acceptable


def test_focused_valid_text_commits_once_before_value_read(qt_application):
    """遗漏显式提交会让仍聚焦的新文本被旧业务值覆盖。"""

    field = PresetSpinBox(1, 100, 5, presets=(1, 5, 10))
    spy = QSignalSpy(field.valueChanged)
    editor = field.findChild(QLineEdit)

    editor.setText("15")

    assert field.commit_value() is True
    assert field.value() == 15
    assert spy.count() == 1
    assert field.presets() == (1, 5, 10)


def test_invalid_enter_and_focus_out_preserve_raw_text_and_old_value(qt_application):
    """Qt 自动纠正非法文本会把旧值伪装成用户已提交的新值。"""

    host = QWidget()
    layout = QVBoxLayout(host)
    spin = StrictIntSpinBox(minimum=1, maximum=100, value=5)
    next_field = QLineEdit()
    layout.addWidget(spin)
    layout.addWidget(next_field)
    host.show()
    spin.focus_editor()
    qt_application.processEvents()
    editor = spin.lineEdit()
    value_spy = QSignalSpy(spin.valueChanged)
    validity_spy = QSignalSpy(spin.validityChanged)

    editor.setText("1,000")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    next_field.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()

    assert editor.text() == "1,000"
    assert spin.value() == 5
    assert value_spy.count() == 0
    assert validity_spy.count() == 1
    assert validity_spy.at(0) == [False]
    assert spin.property("inputInvalid") is True
    host.close()


@pytest.mark.parametrize("commit_key", [Qt.Key.Key_Return, Qt.Key.Key_Tab])
def test_real_keyboard_commit_emits_value_once(qt_application, commit_key):
    """重复解释 Enter 或 Tab 会让一次编辑触发两次业务刷新。"""

    host = QWidget()
    layout = QVBoxLayout(host)
    spin = StrictIntSpinBox(minimum=1, maximum=100, value=5)
    next_field = QLineEdit()
    layout.addWidget(spin)
    layout.addWidget(next_field)
    host.show()
    spin.focus_editor()
    qt_application.processEvents()
    editor = spin.lineEdit()
    editor.selectAll()
    QTest.keyClicks(editor, "15")
    value_spy = QSignalSpy(spin.valueChanged)

    QTest.keyClick(editor, commit_key)
    qt_application.processEvents()

    assert spin.value() == 15
    assert value_spy.count() == 1
    host.close()


def test_focus_out_commits_acceptable_text_once(qt_application):
    """只处理键盘提交会在鼠标切换焦点时遗失合法新值。"""

    host = QWidget()
    layout = QVBoxLayout(host)
    spin = StrictIntSpinBox(minimum=1, maximum=100, value=5)
    next_field = QLineEdit()
    layout.addWidget(spin)
    layout.addWidget(next_field)
    host.show()
    spin.focus_editor()
    qt_application.processEvents()
    spin.lineEdit().setText("21")
    value_spy = QSignalSpy(spin.valueChanged)

    next_field.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_application.processEvents()

    assert spin.value() == 21
    assert value_spy.count() == 1
    host.close()


def test_set_value_including_same_value_clears_invalid_and_normalizes_text(qt_application):
    """同值 setValue 若提前返回会留下非法原文和错误样式。"""

    spin = StrictIntSpinBox(minimum=1, maximum=100, value=5)
    validity_spy = QSignalSpy(spin.validityChanged)
    value_spy = QSignalSpy(spin.valueChanged)
    spin.lineEdit().setText("bad")

    spin.setValue(5)

    assert spin.lineEdit().text() == "5"
    assert spin.input_is_acceptable() is True
    assert spin.property("inputInvalid") is False
    assert validity_spy.count() == 2
    assert validity_spy.at(0) == [False]
    assert validity_spy.at(1) == [True]
    assert value_spy.count() == 0


def test_widget_locales_do_not_change_global_locale_or_accept_grouping(qt_application):
    """控件不得通过修改全局 QLocale 来实现无分组格式。"""

    default_before = QLocale()
    for locale_name, grouped in (("en_US", "1,000"), ("de_DE", "1.000")):
        spin = StrictIntSpinBox(minimum=0, maximum=10_000, value=1_000)
        spin.setLocale(QLocale(locale_name))
        spin.setValue(1_000)

        assert spin.lineEdit().text() == "1000"
        spin.lineEdit().setText(grouped)
        assert spin.input_is_acceptable() is False

    assert QLocale().name() == default_before.name()
    assert QLocale().numberOptions() == default_before.numberOptions()


def test_wrapper_forwards_validity_and_exposes_editor_focus(qt_application):
    """不转发有效性或焦点会让表单无法阻止启动并定位错误字段。"""

    host = QWidget()
    layout = QVBoxLayout(host)
    field = PresetSpinBox(1, 100, 5)
    layout.addWidget(field)
    host.show()
    qt_application.processEvents()
    validity_spy = QSignalSpy(field.validityChanged)
    editor = field.findChild(QLineEdit)

    editor.setText("")
    field.focus_editor()
    qt_application.processEvents()

    assert validity_spy.count() == 1
    assert validity_spy.at(0) == [False]
    assert field.input_is_acceptable() is False
    assert editor.hasFocus()
    assert field.focusProxy() is editor
    host.close()


def test_empty_presets_omit_button_and_nonempty_presets_are_immutable(qt_application):
    """空菜单按钮和可变预设集合会产生无效焦点或运行期配置漂移。"""

    plain = PresetSpinBox(1, 100, 5)
    field = PresetSpinBox(1, 100, 5, presets=[1, 5, 10])
    exposed = field.presets()

    assert plain.findChild(QToolButton) is None
    assert exposed == (1, 5, 10)
    assert isinstance(exposed, tuple)
    with pytest.raises(TypeError):
        exposed[0] = 2


@pytest.mark.parametrize("presets", [(0,), (11,), (1, 12)])
def test_out_of_range_preset_is_rejected_at_construction(qt_application, presets):
    """越界 QAction 若延迟到点击时处理会把无效配置带入业务层。"""

    with pytest.raises(ValueError):
        PresetSpinBox(1, 10, 5, presets=presets)


@pytest.mark.parametrize("preset", [1.0, "1", True, False])
def test_non_integer_preset_is_rejected_at_construction(qt_application, preset):
    """接受浮点、字符串或布尔值会让菜单文案与业务整数语义不一致。"""

    with pytest.raises(TypeError):
        PresetSpinBox(0, 10, 5, presets=(preset,))


def test_preset_button_is_keyboard_reachable_and_action_commits_once(qt_application):
    """预设按钮缺少键盘入口或重复绑定会破坏无障碍和单次提交契约。"""

    field = PresetSpinBox(1, 100, 5, presets=(1, 5, 10))
    button = field.findChild(QToolButton)
    value_spy = QSignalSpy(field.valueChanged)
    action = next(action for action in button.menu().actions() if action.data() == 10)

    action.trigger()

    assert field.value() == 10
    assert value_spy.count() == 1
    assert button.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert button.accessibleName().strip()
    assert not button.icon().isNull()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_strict_spin_style_covers_focus_invalid_disabled_and_scoped_button(
    qt_application,
    theme,
):
    """遗漏状态或使用裸 QToolButton 选择器会造成主题不可见和全局样式污染。"""

    BaseStyles.switch_theme(theme)
    qss = BaseStyles.INPUT_STYLE()

    assert "QSpinBox {" in qss
    assert "QSpinBox:focus" in qss
    assert 'QSpinBox[inputInvalid="true"]' in qss
    assert "QSpinBox:disabled" in qss
    assert "QSpinBox QLineEdit" in qss
    assert "QToolButton#presetMenuButton" in qss
    assert "QToolButton#presetMenuButton:hover" in qss
    assert "QToolButton#presetMenuButton:focus" in qss
    assert "QToolButton#presetMenuButton:disabled" in qss
    assert f"icons:caret-down-qss-{theme.lower()}.svg" in qss


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_spin_arrows_render_and_disabled_buttons_have_visible_state(qt_application, theme):
    """缺少箭头子控件样式会渲染空白，按钮规则也不能覆盖禁用状态。"""

    enabled_image, enabled_regions = _render_spin_subcontrols(
        qt_application,
        theme,
        enabled=True,
    )
    disabled_image, disabled_regions = _render_spin_subcontrols(
        qt_application,
        theme,
        enabled=False,
    )
    enabled_button_color = QColor(BaseStyles.color("BUTTON_BG"))
    disabled_button_color = QColor(BaseStyles.color("PANEL_BG"))

    for image, regions, background in (
        (enabled_image, enabled_regions, enabled_button_color),
        (disabled_image, disabled_regions, disabled_button_color),
    ):
        for region in regions:
            assert _region_contains_contrasting_pixel(
                image,
                region.adjusted(3, 2, -3, -2),
                background,
            )

    for region in disabled_regions:
        background_pixel = disabled_image.pixelColor(region.left() + 3, region.top() + 3)
        assert background_pixel.name() == disabled_button_color.name()
