"""Fluent 瞬态弹窗外壳及原生 Qt 弹窗防回流契约。"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import FluentTitleBar, InfoBarIcon

import gui.dialogs.fluent_dialog as fluent_dialog_module
from gui.dialogs.fluent_dialog import (
    FluentDialog,
    FluentInputDialog,
    FluentMessageBox,
    MessageLevel,
    _FluentMessageDialog,
)
from gui.features import AboutPanel
from gui.features.logcat import LiveLogcatPage
from gui.features.performance import PerformancePage
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon


def _flush_deferred_deletes(application: QApplication) -> None:
    application.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def _dispose_dialog(application: QApplication, dialog: QWidget) -> None:
    dialog.hide()
    dialog.deleteLater()
    _flush_deferred_deletes(application)


def _pixmap_luminance(widget) -> float:
    image = widget.pixmap().toImage()
    samples = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() >= 128:
                samples.append((color.red() + color.green() + color.blue()) / 3)
    assert samples
    return sum(samples) / len(samples)


def test_modal_fluent_dialog_preserves_layout_and_keeps_only_close_chrome(qt_application):
    dialog = FluentDialog()
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 16, 20, 24)
    layout.addWidget(QWidget())
    try:
        dialog.finalize_fluent_layout()

        margins = layout.contentsMargins()
        assert isinstance(dialog.titleBar, FluentTitleBar)
        assert margins.left() == 12
        assert margins.top() == 16 + dialog.TITLE_BAR_HEIGHT
        assert margins.right() == 20
        assert margins.bottom() == 24
        assert dialog.windowType() == Qt.WindowType.Dialog
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
        assert not dialog.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint
        assert not dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
        assert dialog.titleBar.minBtn.isHidden()
        assert dialog.titleBar.maxBtn.isHidden()
    finally:
        dialog.close()


def test_inline_about_panel_keeps_qr_preview_compact(qt_application):
    panel = AboutPanel()
    try:
        assert panel.support_qr.size() == panel.support_qr.minimumSize()
        assert panel.support_qr.size().width() == 132
        assert panel.support_qr.size().height() == 132
        assert not hasattr(panel, "titleBar")
    finally:
        panel.close()


@pytest.mark.parametrize(
    "page_type",
    [
        pytest.param(LiveLogcatPage, id="live-logcat"),
        pytest.param(PerformancePage, id="performance"),
    ],
)
def test_workspace_feature_pages_have_no_dialog_chrome(
    qt_application,
    page_type,
):
    owner = QWidget()
    page = page_type(device_ip="", parent=owner)
    try:
        assert not isinstance(page, FluentDialog)
        assert page.isWindow() is False
        assert not hasattr(page, "titleBar")
        assert page.minimumWidth() == 0
    finally:
        timer = getattr(page, "_theme_sync_timer", None)
        if timer is not None:
            timer.stop()
        page.request_dispose("test_cleanup")
        page.close()
        owner.close()


def test_fluent_dialog_close_does_not_reenter_close_event(qt_application):
    class CloseProbeDialog(FluentDialog):
        def __init__(self):
            self.close_event_count = 0
            super().__init__()

        def closeEvent(self, event):
            self.close_event_count += 1
            super().closeEvent(event)

    dialog = CloseProbeDialog()
    dialog.show()
    qt_application.processEvents()

    assert dialog.close() is True
    qt_application.processEvents()

    assert dialog.close_event_count == 1
    assert not dialog.isVisible()


def test_fluent_dialog_escape_uses_close_event_and_respects_ignore(qt_application):
    class CloseProbeDialog(FluentDialog):
        def __init__(self):
            self.close_event_count = 0
            self.ignore_close = True
            super().__init__()

        def closeEvent(self, event):
            self.close_event_count += 1
            if self.ignore_close:
                event.ignore()
                return
            super().closeEvent(event)

    dialog = CloseProbeDialog()
    try:
        dialog.show()
        qt_application.processEvents()

        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        qt_application.processEvents()

        assert dialog.close_event_count == 1
        assert dialog.isVisible()

        dialog.ignore_close = False
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        qt_application.processEvents()

        assert dialog.close_event_count == 2
        assert not dialog.isVisible()
    finally:
        if dialog.isVisible():
            dialog.ignore_close = False
            dialog.close()


def test_theme_switch_repaints_the_fluent_title_icon(qt_application):
    BaseStyles.switch_theme("Light")
    dialog = FluentDialog()
    dialog.setWindowIcon(get_themed_icon("info.svg"))
    try:
        dialog.show()
        qt_application.processEvents()
        light_luminance = _pixmap_luminance(dialog.titleBar.iconLabel)

        BaseStyles.switch_theme("Dark")
        qt_application.processEvents()
        dark_luminance = _pixmap_luminance(dialog.titleBar.iconLabel)

        assert dark_luminance > light_luminance + 100
    finally:
        dialog.close()


def test_fluent_dialog_role_fonts_survive_qfluent_qss_polish(qt_application):
    role_font = QFont(qt_application.font().family(), 22)
    role_font.setBold(True)
    owner = QWidget()
    owner.resize(900, 700)
    owner.show()
    dialogs = []
    try:
        with patch.object(BaseStyles, "font_for_role", return_value=role_font):
            shell = FluentDialog(owner)
            message = _FluentMessageDialog(
                owner,
                "Title",
                "Body",
                MessageLevel.INFORMATION,
            )
            input_dialog = FluentInputDialog(owner, "Title", "Prompt", text="value")
            dialogs.extend((shell, message, input_dialog))
            for dialog in dialogs:
                dialog.show()
            qt_application.processEvents()

            widgets = (
                shell.titleBar.titleLabel,
                message.titleLabel,
                message.contentLabel,
                message.yesButton,
                input_dialog.titleLabel,
                input_dialog.label,
                input_dialog.lineEdit,
                input_dialog.yesButton,
                input_dialog.cancelButton,
            )
            for widget in widgets:
                widget.ensurePolished()
                assert widget.font().family() == role_font.family()
                assert widget.font().pointSizeF() == pytest.approx(22)
                assert widget.font().bold()
    finally:
        for dialog in dialogs:
            _dispose_dialog(qt_application, dialog)
        owner.close()


def test_fluent_input_dialog_exec_result_and_deferred_delete(qt_application):
    destroyed = []

    class AutoAcceptInputDialog(FluentInputDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.destroyed.connect(lambda *_args: destroyed.append(True))

        def exec(self):
            QTimer.singleShot(0, self.accept)
            return super().exec()

    parent = QWidget()
    parent.resize(640, 480)
    parent.show()
    value, accepted = AutoAcceptInputDialog.getText(
        parent,
        "Rename",
        "New name",
        text="demo.txt",
    )

    assert value == "demo.txt"
    assert accepted is True
    assert parent.findChildren(AutoAcceptInputDialog)

    _flush_deferred_deletes(qt_application)

    assert destroyed == [True]
    assert not parent.findChildren(AutoAcceptInputDialog)
    parent.close()


@pytest.mark.parametrize(
    ("method", "level", "icon"),
    [
        pytest.param(
            "information",
            MessageLevel.INFORMATION,
            InfoBarIcon.INFORMATION,
            id="information",
        ),
        pytest.param(
            "warning",
            MessageLevel.WARNING,
            InfoBarIcon.WARNING,
            id="warning",
        ),
        pytest.param(
            "critical",
            MessageLevel.ERROR,
            InfoBarIcon.ERROR,
            id="error",
        ),
    ],
)
def test_fluent_message_box_exec_visual_level_and_deferred_delete(
    qt_application,
    method,
    level,
    icon,
):
    destroyed = []
    captured = {}

    def create_dialog(parent, title, content, actual_level):
        dialog = _FluentMessageDialog(parent, title, content, actual_level)
        captured["dialog"] = dialog
        dialog.destroyed.connect(lambda *_args: destroyed.append(True))
        QTimer.singleShot(0, dialog.accept)
        return dialog

    parent = QWidget()
    parent.resize(640, 480)
    parent.show()
    with patch.object(
        fluent_dialog_module,
        "_FluentMessageDialog",
        side_effect=create_dialog,
    ):
        result = getattr(FluentMessageBox, method)(parent, "Title", "Content")

    dialog = captured["dialog"]
    assert result == 1
    assert dialog.level is level
    assert dialog.widget.property("messageLevel") == level.value
    assert dialog.iconWidget.accessibleName() == level.value
    assert dialog.iconWidget._icon is icon
    assert dialog.cancelButton.isHidden()
    assert parent.findChildren(_FluentMessageDialog)

    _flush_deferred_deletes(qt_application)

    assert destroyed == [True]
    assert not parent.findChildren(_FluentMessageDialog)
    parent.close()


def test_long_message_content_scrolls_without_exceeding_owner(qt_application):
    owner = QWidget()
    owner.resize(640, 468)
    owner.show()
    dialog = _FluentMessageDialog(
        owner,
        "Long message",
        "A long diagnostic line with selectable details. " * 120,
        MessageLevel.ERROR,
    )
    try:
        dialog.show()
        qt_application.processEvents()

        assert dialog.size().width() <= owner.width()
        assert dialog.size().height() <= owner.height()
        assert dialog.widget.width() <= owner.width()
        assert dialog.widget.height() <= owner.height()
        assert dialog.contentScroll.verticalScrollBar().maximum() > 0
        assert dialog.contentScroll.horizontalScrollBar().maximum() == 0
    finally:
        _dispose_dialog(qt_application, dialog)
        owner.close()


def test_runtime_ui_does_not_reintroduce_native_message_or_input_dialogs():
    root = Path(__file__).resolve().parents[1]
    targets = sorted((root / "gui").rglob("*.py"))
    violations = []
    for path in targets:
        if path.name == "fluent_dialog.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "PySide6.QtWidgets":
                for alias in node.names:
                    if alias.name in {"QDialog", "QInputDialog", "QMessageBox"}:
                        violations.append(f"{path.relative_to(root)}:{node.lineno}:{alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module == "qframelesswindow":
                violations.append(f"{path.relative_to(root)}:{node.lineno}:direct frameless dialog")
            if isinstance(node, ast.ImportFrom) and node.module == "qfluentwidgets":
                for alias in node.names:
                    if alias.name in {"MessageBox", "MessageBoxBase"}:
                        violations.append(f"{path.relative_to(root)}:{node.lineno}:{alias.name}")

    assert not violations, "旧 Qt 弹窗仍在运行时 UI 中：\n" + "\n".join(violations)
