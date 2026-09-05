"""验证 GUI 缩放启动顺序、设置诊断及 CLI 分派边界。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from core import settings_manager


@pytest.mark.parametrize("invalid_json", [False, True])
def test_gui_reads_scale_before_application_and_delivers_early_and_late_diagnostics(
    tmp_path, monkeypatch, invalid_json,
):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        "{" if invalid_json else json.dumps({"schema_version": 3, "ui_scale": 1.5}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setattr(settings_manager.AppSettings, "_instance", None)
    monkeypatch.setattr(settings_manager, "_error_sink", None)
    for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_SCALE_FACTOR_ROUNDING_POLICY"):
        monkeypatch.delenv(key, raising=False)
    steps = []
    original_instance = settings_manager.AppSettings.instance

    def load_settings():
        steps.append("settings")
        return original_instance()

    monkeypatch.setattr(settings_manager.AppSettings, "instance", staticmethod(load_settings))

    class FakeApplication:
        def __init__(self, _argv):
            steps.append("application")
            assert os.environ.get("QT_SCALE_FACTOR") == (None if invalid_json else "1.5")

        def setWindowIcon(self, _icon):
            pass

        def exec(self):
            return 23

    logger = Mock()

    def create_logger():
        steps.append("logger")
        return logger

    def reload_fonts():
        steps.append("fonts")
        settings_manager._log_error("INFO", "late-diagnostic")

    frame = Mock()
    styles = SimpleNamespace(
        reload_from_settings=reload_fonts, set_accent_color=Mock(), switch_theme=Mock(),
    )
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", FakeApplication)
    monkeypatch.setattr("PySide6.QtGui.QIcon", Mock())
    monkeypatch.setattr(main, "setup_qt_search_paths", Mock())
    monkeypatch.setitem(sys.modules, "core.log_service", SimpleNamespace(LogService=create_logger))
    monkeypatch.setitem(sys.modules, "gui.main_frame", SimpleNamespace(MainFrame=lambda: frame))
    monkeypatch.setitem(sys.modules, "gui.styles", SimpleNamespace(BaseStyles=styles))
    if sys.platform == "win32":
        monkeypatch.setattr(
            main.ctypes.windll.shell32, "SetCurrentProcessExplicitAppUserModelID", Mock(),
        )

    assert main._run_gui() == 23
    assert steps == ["settings", "application", "logger", "fonts"]
    frame.show.assert_called_once_with()
    calls = [call.args for call in logger.log.call_args_list]
    if invalid_json:
        assert calls[0][0] == "WARNING"
        assert calls[0][1].startswith("Failed to load settings")
        assert len(calls) == 2
    else:
        assert len(calls) == 1
    assert calls[-1] == ("INFO", "late-diagnostic")


def test_cli_dispatch_never_applies_gui_scale_or_constructs_qt(tmp_path):
    script = """
import json, os, sys
import main
before = dict(os.environ)
calls = []
main._run_mobileperf_worker = lambda args: calls.append(['worker', args]) or 7
main._run_self_check = lambda args: calls.append(['self-check', args]) or 9
def forbidden_scale(value):
    raise AssertionError('CLI entered GUI scaling')
main._configure_gui_scaling = forbidden_scale
assert main._dispatch_cli(['--mobileperf-worker', '--config', 'synthetic.json']) == 7
assert main._dispatch_cli(['--self-check', 'packaging']) == 9
assert main._dispatch_cli([]) is None
assert dict(os.environ) == before
assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
print(json.dumps(calls))
"""
    environment = dict(os.environ, LOCALAPPDATA=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", script], env=environment, capture_output=True,
        text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        ["worker", ["--config", "synthetic.json"]], ["self-check", ["packaging"]],
    ]
