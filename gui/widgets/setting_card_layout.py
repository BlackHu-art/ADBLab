"""让原生 SettingCard 按项目字号换行，并保持操作控件可达。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget
from qfluentwidgets import SettingCard

from gui.styles import BaseStyles, FontRole


def apply_setting_text_style(widget: QWidget, role: FontRole, *, bold: bool = False) -> None:
    """只覆盖卡片叶子标签的字体，保留 Fluent 自身的主题颜色和背景。"""

    font = BaseStyles.font_for_role(role)
    family = font.family().replace("'", "\\'")
    widget.setStyleSheet(
        f"font-family: '{family}'; font-size: {font.pointSizeF()}pt; "
        f"font-weight: {600 if bold else 400};"
    )


class SettingsCardPresentation:
    """复用 SettingCard 的控件和信号，按文字度量调整说明与操作的排布。"""

    def __init__(self, card: SettingCard, control: QWidget) -> None:
        self.card = card
        self.control = control
        # 保留原卡片和操作控件的身份，仅替换固定高度的内部排布。
        while card.vBoxLayout.count():
            card.vBoxLayout.takeAt(0)
        while card.hBoxLayout.count():
            card.hBoxLayout.takeAt(0)
        self.body = QWidget(card)
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(6)
        # 高操作控件（例如二维码）跨两行时，文字仍作为紧邻的一组居中，
        # 不让多余行高把标题与说明分散到卡片上下两端。
        self.grid.addWidget(card.titleLabel, 0, 0, Qt.AlignmentFlag.AlignBottom)
        self.grid.addWidget(card.contentLabel, 1, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.setColumnStretch(0, 1)
        card.hBoxLayout.setContentsMargins(16, 16, 16, 16)
        card.hBoxLayout.setSpacing(16)
        card.hBoxLayout.addWidget(card.iconLabel, 0, Qt.AlignmentFlag.AlignTop)
        card.hBoxLayout.addWidget(self.body, 1)
        for label in (card.titleLabel, card.contentLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        control.setAccessibleName(card.titleLabel.text())
        control.setAccessibleDescription(card.contentLabel.text())
        self.compact = False

    def reflow(self, width: int) -> None:
        """窄卡片把操作移至说明下方；完整保留说明和按钮的可读尺寸。"""

        card = self.card
        body_width = max(1, width - 64)
        action_width = self.control.sizeHint().width()
        text_minimum = max(
            card.titleLabel.fontMetrics().horizontalAdvance(card.titleLabel.text()),
            card.contentLabel.fontMetrics().averageCharWidth() * 22,
        )
        self.compact = body_width < text_minimum + action_width + 16
        card.hBoxLayout.setAlignment(
            card.iconLabel,
            Qt.AlignmentFlag.AlignTop if self.compact else Qt.AlignmentFlag.AlignVCenter,
        )
        self.grid.removeWidget(self.control)
        self.grid.addWidget(
            self.control,
            2 if self.compact else 0,
            0 if self.compact else 1,
            1 if self.compact else 2,
            1,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        text_width = body_width if self.compact else max(1, body_width - action_width - 16)
        text_height = 0
        for label in (card.titleLabel, card.contentLabel):
            if label.isHidden():
                continue
            label.setMinimumHeight(0)
            label.setMaximumHeight(16777215)
            height = max(label.fontMetrics().height(), label.heightForWidth(text_width))
            label.setFixedHeight(height)
            text_height += height + (6 if text_height else 0)
        action_height = max(self.control.minimumHeight(), self.control.sizeHint().height())
        height = (
            text_height + 6 + action_height
            if self.compact else max(text_height, action_height)
        )
        card.setFixedHeight(height + 32)
        card.updateGeometry()
