"""验证后台保存、关闭排空、方案回填和文件失效提示。"""

import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

import gui.widgets.run_preset_bar as preset_module
from gui.dialogs.fluent_dialog import FluentInputDialog
from gui.i18n import tr
from gui.run_library import RunLibraryController
from gui.widgets.run_preset_bar import RunPresetBar
from services.run_library import RunLibrary, RunRecord


def wait_until(application, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def make_record(index=0):
    return RunRecord(
        str(index), "monkey", "com.example.app", 1, 2 + index, "succeeded", {"seed": index}
    )


def test_saves_run_off_gui_and_shutdown_drains_all_jobs(tmp_path, qt_application):
    store = RunLibrary(tmp_path / "runs.json")
    original = store.record_run
    threads = []

    def record(value):
        threads.append(threading.get_ident())
        original(value)

    store.record_run = record
    controller = RunLibraryController(store)
    for index in range(10):
        controller.record_run(make_record(index))
    assert controller.shutdown(3)
    restored = RunLibrary(tmp_path / "runs.json")
    restored.load()
    assert len(restored.records) == 10
    assert all(ident != threading.get_ident() for ident in threads)
    wait_until(qt_application, lambda: len(controller.records) == 10)


def test_write_failure_is_visible_and_not_published_as_success(
    tmp_path, monkeypatch, qt_application
):
    store = RunLibrary(tmp_path / "runs.json")
    controller = RunLibraryController(store)
    failures = []
    controller.error.connect(failures.append)

    def fail(*_args):
        raise PermissionError("private device path")

    monkeypatch.setattr(store, "record_run", fail)
    controller.record_run(make_record())
    wait_until(qt_application, lambda: bool(failures))
    assert controller.records == ()
    assert "private" not in failures[0]
    assert not controller.shutdown()


def test_preset_load_copies_parameters_without_starting_or_crossing_kind(qt_application):
    controller = RunLibraryController(RunLibrary())
    applied = Mock()
    bar = RunPresetBar("monkey", lambda: {"seed": 1}, applied)
    bar.set_library(controller)
    controller.save_preset("快速", "monkey", {"seed": 41})
    controller.save_preset("性能", "performance", {"frequency_seconds": 2})
    wait_until(qt_application, lambda: len(controller.presets) == 2)
    assert bar.combo.count() == 2
    bar.combo.setCurrentIndex(1)
    bar.load_button.click()
    applied.assert_called_once_with({"seed": 41})
    bar.setEnabled(False)
    bar._load()
    assert applied.call_count == 1
    assert controller.shutdown()


def test_missing_file_reports_error_and_existing_local_file_opens(
    tmp_path, monkeypatch, qt_application
):
    controller = RunLibraryController(RunLibrary())
    opened = []
    errors = []
    controller.error.connect(errors.append)
    monkeypatch.setattr(
        "gui.run_library.QDesktopServices.openUrl", lambda url: opened.append(url) or True
    )
    controller.open_artifact(str(tmp_path / "missing.txt"))
    wait_until(qt_application, lambda: bool(errors))
    assert opened == []
    target = tmp_path / "run.txt"
    target.write_text("log", encoding="utf-8")
    controller.open_artifact(str(target))
    wait_until(qt_application, lambda: bool(opened))
    assert opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == target
    assert controller.shutdown()


def test_invalid_timestamp_does_not_stop_later_writes(qt_application):
    controller = RunLibraryController(RunLibrary())
    errors = []
    controller.error.connect(errors.append)
    controller.record_run(replace(make_record(), started_at=10**500, finished_at=10**500))
    controller.record_run(make_record(1))
    try:
        wait_until(qt_application, lambda: bool(errors) and len(controller.records) == 1)
        assert controller.records == (make_record(1),)
    finally:
        assert not controller.shutdown()


@pytest.mark.parametrize("kind", ["performance", "monkey"])
def test_real_save_dialog_updates_selected_preset_and_loads_without_starting(
    qt_application, monkeypatch, tmp_path, kind
):
    owner = QWidget()
    owner.resize(720, 520)
    layout = QVBoxLayout(owner)
    parameters = {"seed": 12}
    applied = Mock()
    controller = RunLibraryController(RunLibrary(tmp_path / "runs.json"))
    bar = RunPresetBar(kind, lambda: dict(parameters), applied, owner)
    layout.addWidget(bar)
    layout.addStretch(1)
    bar.set_library(controller)
    owner.show()
    captured = []

    class NamedInputDialog(FluentInputDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            QTimer.singleShot(240, self.finish_input)

        def finish_input(self):
            captured.append(
                (
                    self.lineEdit.text(),
                    self.size(),
                    QRect(self.widget.mapTo(owner, QPoint()), self.widget.size()),
                )
            )
            self.lineEdit.setText("Repeatable run")
            QTest.mouseClick(self.yesButton, Qt.MouseButton.LeftButton)

    monkeypatch.setattr(preset_module, "FluentInputDialog", NamedInputDialog)
    try:
        qt_application.processEvents()
        QTest.mouseClick(bar.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_application, lambda: len(controller.presets) == 1)
        assert captured[0][0] == ""
        assert captured[0][1] == owner.size()
        assert owner.rect().contains(captured[0][2])
        assert bar.combo.currentText() == "Repeatable run"
        assert bar.load_button.isEnabled()
        identifier = bar.combo.currentData()

        parameters["seed"] = 39
        QTest.mouseClick(bar.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_application, lambda: controller.presets[0].parameters["seed"] == 39)
        assert captured[1][0] == "Repeatable run"
        assert len(controller.presets) == 1
        assert bar.combo.currentData() == identifier
        QTest.mouseClick(bar.load_button, Qt.MouseButton.LeftButton)
        applied.assert_called_once_with({"seed": 39})
    finally:
        assert controller.shutdown()
        owner.close()


@pytest.mark.parametrize("kind", ["performance", "monkey"])
def test_real_save_dialog_cancel_keeps_library_empty(qt_application, monkeypatch, kind):
    controller = RunLibraryController(RunLibrary())
    bar = RunPresetBar(kind, lambda: {"seed": 12}, Mock())
    bar.set_library(controller)
    bar.resize(620, bar.heightForWidth(620))
    bar.show()
    cancelled = []

    class CancelInputDialog(FluentInputDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            QTimer.singleShot(240, self.cancel_input)

        def cancel_input(self):
            cancelled.append(True)
            QTest.mouseClick(self.cancelButton, Qt.MouseButton.LeftButton)

    monkeypatch.setattr(preset_module, "FluentInputDialog", CancelInputDialog)
    try:
        qt_application.processEvents()
        QTest.mouseClick(bar.save_button, Qt.MouseButton.LeftButton)
        assert cancelled == [True]
        assert controller.shutdown()
        assert controller.presets == ()
        assert not bar.load_button.isEnabled()
    finally:
        bar.close()


def test_empty_preset_selector_explains_save_and_returns_after_last_delete(qt_application):
    controller = RunLibraryController(RunLibrary())
    bar = RunPresetBar("performance", lambda: {"frequency_seconds": 2}, Mock())
    bar.set_library(controller)
    bar.show()
    try:
        assert bar.combo.currentText() == tr("暂无方案，请先保存")
        assert not bar.combo.isEnabled()
        assert not bar.load_button.isEnabled()
        assert not bar.delete_button.isEnabled()
        assert bar.save_button.isEnabled()
        controller.save_preset("Monkey only", "monkey", {"seed": 1})
        wait_until(qt_application, lambda: len(controller.presets) == 1)
        assert not bar.combo.isEnabled()
        controller.save_preset("Performance", "performance", {"frequency_seconds": 2})
        wait_until(qt_application, lambda: len(controller.presets) == 2)
        assert bar.combo.isEnabled()
        bar.combo.setCurrentIndex(1)
        QTest.mouseClick(bar.delete_button, Qt.MouseButton.LeftButton)
        wait_until(qt_application, lambda: len(controller.presets) == 1)
        assert controller.presets[0].kind == "monkey"
        assert bar.combo.currentText() == tr("暂无方案，请先保存")
        assert not bar.combo.isEnabled()
        assert not bar.load_button.isEnabled()
        assert not bar.delete_button.isEnabled()
        assert bar.save_button.isEnabled()
    finally:
        assert controller.shutdown()
        bar.close()
