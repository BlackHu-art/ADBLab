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


def test_packaging_check_reports_missing_tls_without_network(tmp_path, monkeypatch, capsys):
    from PySide6.QtNetwork import QNetworkAccessManager, QSslSocket

    monkeypatch.setattr(main, "user_data_root", lambda: tmp_path)
    monkeypatch.setenv("MOBILEPERF_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(QSslSocket, "supportsSsl", staticmethod(lambda: False))

    def forbidden_request(*_args):
        raise AssertionError("Packaging self-check must stay offline")

    monkeypatch.setattr(QNetworkAccessManager, "get", forbidden_request)
    assert main._self_check_packaging() == 1
    assert "FAIL network:tls_backend" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("missing_paths", "expected_check"),
    [
        (("resources/images/gallery_header.png",), "resource:resources/images/gallery_header.png"),
        (
            ("resources/images/LICENSE.gallery.txt", "licenses/gallery/LICENSE.gallery.txt"),
            "resource:gallery-license",
        ),
    ],
)
def test_packaging_check_reports_missing_gallery_resource(
    tmp_path, monkeypatch, capsys, missing_paths, expected_check,
):
    """首页原图和随附许可均为发布资源，缺失时自检必须失败而不是只验证目录存在。"""

    from PySide6.QtNetwork import QNetworkAccessManager, QSslSocket

    resolve = main.resource_path
    monkeypatch.setattr(
        main, "resource_path",
        lambda relative: (
            str(tmp_path / "missing") if relative in missing_paths else resolve(relative)
        ),
    )
    monkeypatch.setattr(main, "user_data_root", lambda: tmp_path)
    monkeypatch.setenv("MOBILEPERF_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(QSslSocket, "supportsSsl", staticmethod(lambda: True))
    monkeypatch.setattr("utils.scrcpy_bridge.resolve_scrcpy_bridge", lambda: "synthetic-bridge")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=b"scrcpy-adb-bridge: ready\n",
        ),
    )

    def forbidden_request(*_args):
        raise AssertionError("Packaging self-check must stay offline")

    monkeypatch.setattr(QNetworkAccessManager, "get", forbidden_request)
    assert main._self_check_packaging() == 1
    assert f"FAIL {expected_check}" in capsys.readouterr().out


@pytest.mark.parametrize("invalid_json", [False, True])
def test_gui_reads_scale_before_application_and_delivers_early_and_late_diagnostics(
    tmp_path, monkeypatch, invalid_json,
):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        "{" if invalid_json else json.dumps({
            "schema_version": 3, "ui_scale": 1.5, "language": "en_US",
        }),
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
    monkeypatch.setattr(main, "_load_fluent_widgets", lambda: steps.append("fluent"))

    class FakeApplication:
        def __init__(self, _argv):
            steps.append("application")
            assert os.environ.get("QT_SCALE_FACTOR") == (None if invalid_json else "1.5")

        def setWindowIcon(self, _icon):
            pass

        def exec(self):
            assert steps.index("translations") < steps.index("window")
            return 23

    def install_translators(app, language):
        assert isinstance(app, FakeApplication)
        assert language == ("Auto" if invalid_json else "en_US")
        steps.append("translations")
        return ()

    logger = Mock()

    def create_logger():
        steps.append("logger")
        return logger

    def reload_fonts():
        steps.append("fonts")
        settings_manager._log_error("INFO", "late-diagnostic")

    frame = Mock()

    def create_frame():
        steps.append("window")
        return frame
    styles = SimpleNamespace(
        reload_from_settings=reload_fonts, set_accent_color=Mock(), switch_theme=Mock(),
    )
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", FakeApplication)
    monkeypatch.setattr("PySide6.QtGui.QIcon", Mock())
    monkeypatch.setattr(main, "setup_qt_search_paths", Mock())
    monkeypatch.setitem(sys.modules, "core.log_service", SimpleNamespace(LogService=create_logger))
    monkeypatch.setitem(sys.modules, "gui.main_frame", SimpleNamespace(MainFrame=create_frame))
    monkeypatch.setitem(
        sys.modules, "gui.i18n", SimpleNamespace(install_translators=install_translators),
    )
    monkeypatch.setitem(sys.modules, "gui.styles", SimpleNamespace(BaseStyles=styles))
    if sys.platform == "win32":
        monkeypatch.setattr(
            main.ctypes.windll.shell32, "SetCurrentProcessExplicitAppUserModelID", Mock(),
        )

    assert main._run_gui() == 23
    assert steps == [
        "settings", "fluent", "application", "translations", "logger", "fonts", "window",
    ]
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


def test_real_fluent_startup_import_omits_banner_and_preserves_later_output(tmp_path):
    """新进程首次导入真实依赖，避免 pytest 已缓存模块掩盖启动推广输出。"""

    script = """
import sys
import main
assert 'qfluentwidgets' not in sys.modules
print('before-import')
main._load_fluent_widgets()
assert 'qfluentwidgets.common.config' in sys.modules
main._load_fluent_widgets()
print('after-import')
print('stderr-marker', file=sys.stderr)
"""
    environment = dict(
        os.environ, LOCALAPPDATA=str(tmp_path), APPDATA=str(tmp_path),
        XDG_CONFIG_HOME=str(tmp_path), QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", script], env=environment, capture_output=True,
        text=True, encoding="utf-8", timeout=15, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "before-import\nafter-import\n"
    assert result.stderr == "stderr-marker\n"


@pytest.mark.parametrize("without_emoji", [False, True])
@pytest.mark.parametrize("import_fails", [False, True])
def test_fluent_loader_preserves_other_output_and_restores_stream_after_failure(
    monkeypatch, capsys, without_emoji, import_fails,
):
    """只移除完整广告，类似提示、stderr、部分行与导入异常均保留。"""

    alert = "\n\033[1;33m📢 Tips:\033[0m Example promotion\n"
    monkeypatch.setitem(
        sys.modules, "qfluentwidgets.common.config", SimpleNamespace(ALERT=alert),
    )
    error = ImportError("simulated missing GUI dependency")
    stderr_before = sys.stderr
    stdout_before = sys.stdout
    imports = []

    def import_fluent(name):
        imports.append(name)
        assert sys.stderr is stderr_before
        sys.stdout.write("ordinary partial output")
        print(alert.replace("📢", "") if without_emoji else alert)
        sys.stdout.write(" continues\n")
        print("Tips: normal application advice")
        print("import diagnostic", file=sys.stderr)
        if import_fails:
            raise error
        return SimpleNamespace()

    monkeypatch.setattr(main, "__import__", import_fluent, raising=False)
    if import_fails:
        with pytest.raises(ImportError) as raised:
            main._load_fluent_widgets()
        assert raised.value is error
    else:
        main._load_fluent_widgets()

    assert imports == ["qfluentwidgets"]
    assert sys.stdout is stdout_before
    assert sys.stderr is stderr_before
    captured = capsys.readouterr()
    assert captured.out == "ordinary partial output continues\nTips: normal application advice\n"
    assert captured.err == "import diagnostic\n"


def test_fluent_loader_supports_windowed_process_without_stdout(monkeypatch, capsys):
    """无控制台时正常导入，标准错误仍保留且不会制造额外的输出异常。"""

    alert = "\n📢 Tips: Example promotion\n"
    monkeypatch.setitem(
        sys.modules, "qfluentwidgets.common.config", SimpleNamespace(ALERT=alert),
    )

    def import_fluent(name):
        assert name == "qfluentwidgets"
        print(alert)
        print("ordinary stdout without console")
        print("windowed diagnostic", file=sys.stderr)
        return SimpleNamespace()

    monkeypatch.setattr(main, "__import__", import_fluent, raising=False)
    with monkeypatch.context() as context:
        context.setattr(sys, "stdout", None)
        main._load_fluent_widgets()
        assert sys.stdout is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "windowed diagnostic\n"
