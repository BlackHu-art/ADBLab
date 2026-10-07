"""下拉弹层按实际宿主选择材质，视觉失败不能改变选择或关闭语义。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, EditableComboBox
from qfluentwidgets.common import image_utils
from qfluentwidgets.components.material.acrylic_combo_box import AcrylicComboBoxMenu
from qfluentwidgets.components.widgets import acrylic_label
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.styles.combo_menu import configure_combo_menu
from gui.widgets.preset_spin_box import StrictIntComboBox
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class _MaterialHost(QWidget):
    def __init__(self):
        super().__init__()
        self.mica = True

    def isMicaEffectEnabled(self):
        return self.mica


@pytest.fixture(autouse=True)
def _isolated_capture(monkeypatch):
    """仅替代外部屏幕来源，模糊和菜单绘制仍运行安装库的真实实现。"""
    def capture(brush, rect):
        image = QPixmap(max(1, rect.width()), max(1, rect.height()))
        image.fill(QColor("#245884"))
        brush.setImage(image)

    monkeypatch.setattr(acrylic_label.AcrylicBrush, "grabImage", capture)


def _field(kind, host):
    if kind == "strict":
        field = StrictIntComboBox(1, 100, 30, presets=(10, 30, 60), parent=host)
    else:
        field = (ComboBox if kind == "combo" else EditableComboBox)(host)
        field.addItems(["10", "30", "60"])
        field.setCurrentIndex(1)
    for index in range(3):
        field.setItemData(index, {"option": index})
    field.setItemEnabled(2, False)
    return field


def _open(app, field):
    field._showComboMenu()
    menu = field.dropMenu
    wait_until(app, lambda: menu.isVisible())
    wait_until(app, lambda: menu.aniManager.ani.state() == QAbstractAnimation.State.Stopped)
    return menu


def _dispose(widget):
    if isValid(widget):
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _background(menu):
    image = menu.view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    return image.pixelColor(round((menu.view.viewport().width() - 12) * scale), round(8 * scale))


@pytest.mark.parametrize("kind", ["combo", "editable", "strict"])
def test_mica_menu_preserves_control_selection_data_and_disabled_items(qt_application, kind):
    """材质工厂只更换弹层，不能重建控件或把留白行当作业务索引。"""
    host = _MaterialHost()
    field = _field(kind, host)
    original_type = type(field)
    layout = QVBoxLayout(host)
    layout.addWidget(field)
    host.resize(360, 100)
    host.show()
    assert configure_combo_menu(field) is field
    configure_combo_menu(field)
    changed = QSignalSpy(field.currentIndexChanged)
    activated = QSignalSpy(field.activated)
    try:
        menu = _open(qt_application, field)
        assert isinstance(menu, AcrylicComboBoxMenu)
        assert type(field) is original_type
        assert field.currentIndex() == 1 and field.currentData() == {"option": 1}
        assert menu.view.currentItem() is menu.actions()[1].property("item")
        assert changed.count() == activated.count() == 0
        disabled = menu.actions()[2].property("item")
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(disabled).center(),
        )
        assert field.currentIndex() == 1 and activated.count() == 0
        first = menu.actions()[0].property("item")
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(first).center(),
        )
        assert field.currentIndex() == 0 and field.currentData() == {"option": 0}
        assert changed.count() == activated.count() == 1
        if kind == "strict":
            assert field.value() == 10
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(menu)
    finally:
        _dispose(host)


def test_original_factory_is_preserved_when_material_changes(qt_application, monkeypatch):
    """每次打开读取实际宿主，并在非云母或缺少模糊能力时复用原工厂。"""
    class OriginalMenu(ComboBoxMenu):
        pass

    host = _MaterialHost()
    field = _field("combo", host)
    field._createComboMenu = lambda: OriginalMenu(field)
    configure_combo_menu(field)
    configure_combo_menu(field)
    try:
        host.mica = False
        native = field._createComboMenu()
        assert isinstance(native, OriginalMenu)
        host.mica = True
        material = field._createComboMenu()
        assert isinstance(material, AcrylicComboBoxMenu)
        monkeypatch.setattr(acrylic_label, "isAcrylicAvailable", False)
        unavailable = field._createComboMenu()
        assert isinstance(unavailable, OriginalMenu)
    finally:
        _dispose(host)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_successful_material_tracks_captured_image_without_selection_changes(
    qt_application, monkeypatch, theme,
):
    """成功路径必须实际合成捕获图，不能始终走可操作但不透色的回退。"""
    BaseStyles.switch_theme(theme)
    host = _MaterialHost()
    field = configure_combo_menu(_field("combo", host))
    field.setCurrentIndex(-1)
    layout = QVBoxLayout(host)
    layout.addWidget(field)
    host.resize(360, 100)
    host.show()
    changed = QSignalSpy(field.currentIndexChanged)
    samples = []
    try:
        for color in ("#245884", "#99522f"):
            def capture(brush, rect, color=color):
                image = QPixmap(max(1, rect.width()), max(1, rect.height()))
                image.fill(QColor(color))
                brush.setImage(image)

            monkeypatch.setattr(acrylic_label.AcrylicBrush, "grabImage", capture)
            menu = _open(qt_application, field)
            samples.append(_background(menu))
            field._closeComboMenu()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert max(abs(a - b) for a, b in zip(samples[0].getRgb(), samples[1].getRgb())) >= 12
        assert changed.count() == 0 and field.currentIndex() == -1
    finally:
        _dispose(host)


@pytest.mark.parametrize(
    ("capture_size", "filter_shape"),
    [((960, 640), (213, 320)), ((480, 960), (320, 160)), ((120, 60), (60, 120))],
)
def test_blur_bounds_actual_filter_input_without_resizing_menu_or_losing_selection(
    qt_application, monkeypatch, capture_size, filter_shape,
):
    """滤镜处理等比例缩小的像素，小图不放大；材质仍透色且长列表末项可选。"""
    host = _MaterialHost()
    field = configure_combo_menu(ComboBox(host))
    for index in range(40):
        field.addItem(f"Option {index}", userData=index)
    field.setCurrentIndex(-1)
    field.setMaxVisibleItems(5)
    field.setMinimumWidth(500)
    layout = QVBoxLayout(host)
    layout.addWidget(field)
    host.resize(540, 100)
    host.show()
    actual_shapes = []
    gaussian_filter = image_utils.gaussian_filter

    def observed_filter(channel, *args, **kwargs):
        actual_shapes.append(channel.shape)
        return gaussian_filter(channel, *args, **kwargs)

    monkeypatch.setattr(image_utils, "gaussian_filter", observed_filter)
    samples = []
    try:
        for color in ("#245884", "#99522f"):
            def capture(brush, _rect, color=color):
                image = QPixmap(*capture_size)
                image.fill(QColor(color))
                brush.setImage(image)

            monkeypatch.setattr(acrylic_label.AcrylicBrush, "grabImage", capture)
            menu = _open(qt_application, field)
            assert actual_shapes and all(shape == filter_shape for shape in actual_shapes)
            assert menu.view.width() >= 500
            assert menu.view.verticalScrollBar().maximum() > 0
            samples.append(_background(menu))
            final_item = menu.actions()[-1].property("item")
            menu.view.scrollToItem(final_item)
            qt_application.processEvents()
            QTest.mouseClick(
                menu.view.viewport(), Qt.MouseButton.LeftButton,
                pos=menu.view.visualItemRect(final_item).center(),
            )
            assert field.currentData() == 39
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            field.setCurrentIndex(-1)
        assert max(abs(a - b) for a, b in zip(samples[0].getRgb(), samples[1].getRgb())) >= 12
    finally:
        _dispose(host)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("failure", ["empty", "capture", "blur"])
def test_material_failure_opens_same_menu_with_native_opaque_background(
    qt_application, monkeypatch, theme, failure,
):
    """抓屏为空或抓屏、模糊失败时保留同一弹层与动作，并恢复可读的原生底板。"""
    BaseStyles.switch_theme(theme)
    host = _MaterialHost()
    field = _field("combo", host)
    field.setCurrentIndex(-1)
    layout = QVBoxLayout(host)
    layout.addWidget(field)
    host.resize(360, 100)
    host.show()
    native = _open(qt_application, field)
    native_color = _background(native)
    field._closeComboMenu()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    configure_combo_menu(field)
    if failure == "empty":
        monkeypatch.setattr(
            acrylic_label.AcrylicBrush, "grabImage", lambda brush, _rect: brush.setImage(QPixmap()),
        )
    elif failure == "capture":
        def broken_capture(_brush, _rect):
            raise RuntimeError("synthetic capture failure")

        monkeypatch.setattr(acrylic_label.AcrylicBrush, "grabImage", broken_capture)
    else:
        def broken_blur(*_args, **_kwargs):
            raise ValueError("synthetic blur failure")

        monkeypatch.setattr(acrylic_label, "gaussianBlur", broken_blur)
    try:
        menu = _open(qt_application, field)
        assert isinstance(menu, AcrylicComboBoxMenu)
        assert field.dropMenu is menu
        assert len(menu.actions()) == 3
        assert _background(menu) == native_color
        action = menu.actions()[1]
        assert action.isEnabled()
        item = action.property("item")
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(item).center(),
        )
        assert field.currentData() == {"option": 1}
    finally:
        _dispose(host)


@pytest.mark.parametrize("dismissal", ["escape", "owner"])
def test_material_menu_clears_focus_before_destruction(qt_application, dismissal):
    """材质弹层仍在自身或宿主销毁前释放列表焦点，不提交选择。"""
    host = _MaterialHost()
    field = configure_combo_menu(_field("editable", host))
    host.resize(360, 100)
    host.show()
    changed = QSignalSpy(field.currentIndexChanged)
    menu = _open(qt_application, field)
    menu.view.setFocus(Qt.FocusReason.TabFocusReason)
    wait_until(qt_application, menu.view.hasFocus)
    focus_on_destruction = []
    menu.destroyed.connect(lambda: focus_on_destruction.append(menu.view.hasFocus()))
    try:
        if dismissal == "escape":
            QTest.keyClick(menu, Qt.Key.Key_Escape)
        else:
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert focus_on_destruction == [False]
        assert not isValid(menu)
        assert changed.count() == 0
    finally:
        _dispose(host)


@pytest.mark.parametrize("at_bottom", [False, True])
def test_material_long_menu_keeps_both_animation_directions_and_scrolling(
    qt_application, at_bottom,
):
    """靠近屏幕上下边界时仍选择正确弹出方向，长列表末项可滚动选择。"""
    host = _MaterialHost()
    field = configure_combo_menu(ComboBox(host))
    for index in range(40):
        field.addItem(f"Option {index}", userData=index)
    field.setMaxVisibleItems(5)
    layout = QVBoxLayout(host)
    layout.addWidget(field)
    host.resize(300, 80)
    screen = qt_application.primaryScreen().availableGeometry()
    host.move(screen.left() + 20, screen.bottom() - 100 if at_bottom else screen.top() + 20)
    host.show()
    try:
        menu = _open(qt_application, field)
        end = menu.aniManager.ani.endValue()
        assert (end.y() < field.mapToGlobal(QPoint()).y()) is at_bottom
        assert menu.view.verticalScrollBar().maximum() > 0
        final_item = menu.actions()[-1].property("item")
        menu.view.scrollToItem(final_item)
        qt_application.processEvents()
        assert menu.view.viewport().rect().intersects(menu.view.visualItemRect(final_item))
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(final_item).center(),
        )
        assert field.currentData() == 39
    finally:
        _dispose(host)
