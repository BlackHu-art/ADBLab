"""验证 APK 选择边界，不打开真实系统文件框。"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QWidget

pytestmark = pytest.mark.ui


def make_picker(provider):
    from adblab.presentation.qt_apk_file_picker import QtApkFilePicker

    return QtApkFilePicker(provider)


def test_selection_protocol_import_does_not_load_qt_or_controllers():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import adblab.application.apk_selection; "
         "assert not any(n == 'controllers' or n.startswith('PySide6') for n in sys.modules)"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_construction_is_lazy_and_parent_is_resolved_per_selection(qt_application, monkeypatch):
    parents = [QWidget(), QWidget(), None]
    provider = Mock(side_effect=parents)
    single = Mock(return_value=("", ""))
    multiple = Mock(return_value=([], ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", single)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", multiple)
    try:
        picker = make_picker(provider)
        provider.assert_not_called()
        single.assert_not_called()
        multiple.assert_not_called()
        picker.select_one()
        picker.select_many()
        picker.select_one()
        assert single.call_args_list[0].args[0] is parents[0]
        assert multiple.call_args.args[0] is parents[1]
        assert single.call_args_list[1].args[0] is None
        assert provider.call_count == 3
    finally:
        for parent in parents[:2]:
            parent.deleteLater()


@pytest.mark.parametrize("multiple,title", [
    (False, "Select APK File"), (True, "Select APK files to install"),
])
def test_single_and_multiple_preserve_dialog_parameters(monkeypatch, multiple, title):
    translate = Mock(side_effect=lambda _context, text: text)
    chooser = Mock(return_value=([] if multiple else "", ""))
    monkeypatch.setattr(QCoreApplication, "translate", translate)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames" if multiple else "getOpenFileName", chooser)
    picker = make_picker(lambda: None)
    (picker.select_many if multiple else picker.select_one)()
    chooser.assert_called_once_with(None, title, "", "APK Files (*.apk);;All Files (*)")
    assert [call.args for call in translate.call_args_list] == [
        ("ADBLab", title), ("ADBLab", "APK Files (*.apk);;All Files (*)"),
    ]


def test_selection_preserves_paths_order_and_duplicates(monkeypatch):
    paths = ["b.apk", "目录/demo one.APK", "b.apk"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", Mock(return_value=(paths[1], "filter")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", Mock(return_value=(paths, "filter")))
    picker = make_picker(lambda: None)
    assert picker.select_one() == "目录/demo one.APK"
    assert picker.select_many() == ("b.apk", "目录/demo one.APK", "b.apk")


def test_cancel_returns_none_or_empty_tuple(monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", Mock(return_value=("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", Mock(return_value=([], "")))
    picker = make_picker(lambda: None)
    assert picker.select_one() is None
    assert picker.select_many() == ()


@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("source", ["provider", "chooser"])
def test_picker_exceptions_propagate(monkeypatch, multiple, source):
    provider = Mock(return_value=None)
    chooser = Mock()
    (provider if source == "provider" else chooser).side_effect = RuntimeError("picker failed")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames" if multiple else "getOpenFileName", chooser)
    picker = make_picker(provider)
    with pytest.raises(RuntimeError, match="picker failed"):
        (picker.select_many if multiple else picker.select_one)()
    if source == "provider":
        chooser.assert_not_called()
