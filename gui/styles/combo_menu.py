"""下拉弹层的局部亚克力适配，视觉能力失败时保留实色菜单交互。"""

from __future__ import annotations

import logging
from typing import TypeVar

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox, EditableComboBox
from qfluentwidgets.components.material.acrylic_combo_box import AcrylicComboBoxMenu
from qfluentwidgets.components.widgets import acrylic_label
from qfluentwidgets.components.widgets.menu import (
    MenuAnimationManager,
    MenuAnimationType,
    RoundMenu,
)

from gui.styles.material import is_mica_active
from gui.widgets.transient_menu import TransientMenuFocusGuard

_WidgetT = TypeVar("_WidgetT", bound=QWidget)
_LOGGER = logging.getLogger(__name__)


class _OptionalAcrylicBrush(acrylic_label.AcrylicBrush):
    """仅在图像完整准备后绘制亚克力，否则交还列表的原生实色底板。"""

    enabled = False

    def paint(self) -> None:
        if self.enabled:
            super().paint()


class _MaterialComboBoxMenu(AcrylicComboBoxMenu):
    """复用 Fluent 的动作和留白行，在同一菜单上处理抓屏与模糊失败。

    截图和模糊沿用安装库的同步路径；不启动线程，也不重新绑定业务动作。
    失败只影响底板，选择、上下弹出动画、关闭及焦点清理仍归原菜单所有。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._material_brush = _OptionalAcrylicBrush(self.view.viewport(), 35)
        # 安装库按原图比例缩到此边界且不放大小图；只限制同步滤镜输入，
        # 最终绘制仍铺满原菜单视口，避免大弹层或高 DPI 放大计算成本。
        self._material_brush.setBlurPicSize(QSize(320, 320))
        self.view.acrylicBrush = self._material_brush

    def exec(
        self, pos: QPoint, ani: bool = True,
        aniType: MenuAnimationType = MenuAnimationType.DROP_DOWN,
    ) -> None:
        """在最终布局处准备材质，空图或已知图像错误均退回当前主题实色。"""
        self.view.adjustSize(pos, aniType)
        self.adjustSize()
        brush = self._material_brush
        brush.enabled = False
        # 同一个菜单被再次展示时不能复用上一次桌面图像。
        brush.originalImage = QPixmap()
        brush.image = QPixmap()
        if acrylic_label.isAcrylicAvailable:
            try:
                end_position = MenuAnimationManager.make(self, aniType)._endPosition(pos)
                brush.grabImage(QRect(end_position, self.hBoxLayout.sizeHint()))
                brush.enabled = not brush.originalImage.isNull() and not brush.image.isNull()
            except (OSError, RuntimeError, ValueError, TypeError, IndexError) as error:
                # 材质属于可降级效果；不把截图或第三方图像处理失败变成无法选择选项。
                _LOGGER.warning("下拉菜单材质准备失败，使用实色底板（%s）", type(error).__name__)
        if not brush.enabled:
            brush.originalImage = QPixmap()
            brush.image = QPixmap()
        self.view.setProperty("transparent", brush.enabled)
        # 动态属性决定 MENU QSS 的底色，重新抛光但保留动作、选中项与滚动位置。
        self.setStyleSheet(self.styleSheet())
        # AcrylicMenuBase.exec 会再次抓图；直接进入共同的动画展示边界，避免重复工作。
        RoundMenu.exec(self, pos, ani, aniType)


def configure_combo_menu(widget: _WidgetT) -> _WidgetT:
    """幂等配置下拉工厂；每次打开读取实际宿主，非云母仍调用原工厂。

    不替换控件类型或项目校验子类，不修改条目与信号。菜单属于原控件，
    焦点守卫在菜单或宿主释放前清理列表焦点，且不会重复安装。
    """
    if not isinstance(widget, (ComboBox, EditableComboBox)):
        return widget
    if widget.property("adblabComboMenuMaterial"):
        return widget
    original_factory = widget._createComboMenu

    def create_menu():
        menu = (
            _MaterialComboBoxMenu(widget)
            if is_mica_active(widget) and acrylic_label.isAcrylicAvailable
            else original_factory()
        )
        if not menu.findChildren(TransientMenuFocusGuard):
            TransientMenuFocusGuard(menu)
        return menu

    setattr(widget, "_createComboMenu", create_menu)
    widget.setProperty("adblabComboMenuMaterial", True)
    widget.setProperty("adblabMenuFocusGuard", True)
    return widget
