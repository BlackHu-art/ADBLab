"""普通卡片与设置卡的局部材质适配，沿用 Fluent 控件、输入和非云母绘制。"""

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget
from qfluentwidgets import CardWidget, ExpandSettingCard, SettingCard, setCustomStyleSheet
from qfluentwidgets.components.settings.expand_setting_card import HeaderSettingCard

from gui.styles import BaseStyles
from gui.styles.material import MaterialObserver, ensure_material_observer, is_mica_active


class MaterialCard(CardWidget):
    """实际云母宿主下使用低覆盖层，普通窗口继续使用原生交互态。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ensure_material_observer(self, self._refresh_material)

    @staticmethod
    def _refresh_material(widget: QWidget, _mica: bool) -> None:
        """材质变化提交当前交互态，不让旧颜色动画覆盖新主题。"""
        if isinstance(widget, MaterialCard):
            widget._updateBackgroundColor()
            widget.backgroundColorAni.setCurrentTime(widget.backgroundColorAni.duration())

    def _normalBackgroundColor(self) -> QColor:
        if is_mica_active(self):
            return self._material_background_color("BG")
        return super()._normalBackgroundColor()

    def _hoverBackgroundColor(self) -> QColor:
        if is_mica_active(self):
            return self._material_background_color("HOVER")
        return super()._hoverBackgroundColor()

    def _pressedBackgroundColor(self) -> QColor:
        if is_mica_active(self):
            return self._material_background_color("PRESSED")
        return super()._pressedBackgroundColor()

    def _material_background_color(self, state: str) -> QColor:
        """默认承接云母；覆盖高对比图片的卡片可提供局部可读性配色。"""
        return BaseStyles.get_color(f"CARD_MICA_{state}")


class _SettingCardMaterial(MaterialObserver):
    """由设置卡拥有，仅在云母下替换其固定高覆盖底板，不截获鼠标或键盘。"""

    def __init__(self, card: SettingCard) -> None:
        super().__init__(card, self._refresh_surface)

    @staticmethod
    def _refresh_surface(widget: QWidget, mica: bool) -> None:
        widget.update()
        group = widget.parentWidget()
        if isinstance(widget, HeaderSettingCard) and isinstance(group, ExpandSettingCard):
            # 展开正文只由 view 绘制一层；滚动外壳继续沿用 Fluent 的透明底板。
            styles = [
                "QFrame#view { background-color: "
                f"{BaseStyles.color_for(theme, 'CARD_MICA_BG')}; }}" if mica else ""
                for theme in ("Light", "Dark")
            ]
            setCustomStyleSheet(group, *styles)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.parent() and isinstance(watched, SettingCard)
            and event.type() == QEvent.Type.Paint and is_mica_active(watched)
        ):
            self._paint_surface(watched)
            return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _paint_surface(card: SettingCard) -> None:
        """保持上游六像素圆角及展开标题直角，边框仍由原归属控件绘制。"""
        painter = QPainter(card)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(BaseStyles.get_color("CARD_MICA_BG"))
        if isinstance(card, HeaderSettingCard):
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            path.addRoundedRect(QRectF(card.rect().adjusted(1, 1, -1, -1)), 6, 6)
            group = card.parentWidget()
            if isinstance(group, ExpandSettingCard) and group.isExpand:
                path.addRect(1, card.height() - 8, card.width() - 2, 8)
            painter.drawPath(path.simplified())
        else:
            alpha = 50 if BaseStyles.resolved_theme() == "Dark" else 19
            painter.setPen(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(card.rect().adjusted(1, 1, -1, -1), 6, 6)
        painter.end()


def configure_setting_card_material(card: SettingCard) -> None:
    """幂等接入已有卡片，保留实例身份、信号、展开动画与 QObject 所有权。"""
    observer = getattr(card, "_adblab_setting_card_material", None)
    if isinstance(observer, _SettingCardMaterial):
        observer.refresh(force=True)
    else:
        card._adblab_setting_card_material = _SettingCardMaterial(card)
