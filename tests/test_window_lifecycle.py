import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, QSize, Signal
from PySide6.QtWidgets import QDialog
from shiboken6 import delete

from gui.dialogs.lifecycle import (
    alive_forwarding_callback,
    alive_signal_emitter,
    fit_secondary_window_to_owner_screen,
)


class _LifecycleProbe(QObject):
    message = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, *args):
        self.calls.append(args)


def test_secondary_window_is_clamped_to_owner_screen(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(100, 50, 800, 600))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)
    assert 100 <= dialog.x() <= 124
    assert 50 <= dialog.y() <= 74
    dialog.close()


def test_secondary_window_keeps_smaller_declared_minimum(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(520, 420)
    dialog.resize(760, 620)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1200, 800))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(100, 100, 860, 500),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(520, 420)
    assert dialog.size() == QSize(760, 620)
    dialog.close()


def test_secondary_window_restores_original_geometry_after_small_screen_clamp(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen_geometry = {"value": QRect(100, 50, 800, 600)}
    screen = SimpleNamespace(availableGeometry=lambda: screen_geometry["value"])
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)
    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)

    screen_geometry["value"] = QRect(0, 0, 1600, 1000)
    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(980, 700)
    assert dialog.size() == QSize(1100, 800)
    dialog.close()


def test_late_callbacks_ignore_deleted_qobject(qt_application):
    probe = _LifecycleProbe()
    probe.message.connect(probe.record)
    forward = alive_forwarding_callback(probe, "record")
    emit = alive_signal_emitter(probe, "message", "RAW")

    forward("direct")
    emit("signal")

    assert probe.calls == [("direct",), ("RAW", "signal")]

    delete(probe)
    forward("late-direct")
    emit("late-signal")
