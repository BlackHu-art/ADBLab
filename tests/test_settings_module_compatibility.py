"""旧设置入口维持共享规则与调用时诊断替换协议。"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_legacy_exports_share_schema_objects():
    from core import settings_manager as manager
    from core.settings import schema

    for name in ("DEFAULTS", "SCRCPY_SETTING_DEFAULTS", "UI_SCALE_OPTIONS",
                 "LANGUAGE_OPTIONS", "normalise_language", "normalise_ui_scale"):
        assert getattr(manager, name) is getattr(schema, name)
    assert manager._normalise_setting("console_log_level", " error ") == "ERROR"
    result = manager._normalise_setting("monkey_params", {"events": "12345"})
    assert result["events"] == 12345
    assert result is not manager.DEFAULTS["monkey_params"]


def test_legacy_migration_table_and_helper_contracts():
    from core import settings_manager as manager
    from core.settings import migrations

    assert manager._MIGRATIONS is migrations._MIGRATIONS
    assert manager.CURRENT_SCHEMA_VERSION == migrations.CURRENT_SCHEMA_VERSION == 3
    assert manager._legacy_panel_ratio is migrations.legacy_panel_ratio
    assert manager._stored_schema_version is migrations.stored_schema_version
    for name in ("_migrate_1_to_2", "_migrate_2_to_3", "_prune_unknown_keys"):
        assert list(inspect.signature(getattr(manager, name)).parameters) == ["stored"]
    assert list(inspect.signature(manager._run_migrations).parameters) == [
        "stored", "from_version",
    ]
    stored = {"left_panel_width": 300, "right_panel_width": 900}
    assert manager._migrate_1_to_2(stored) is None
    assert stored["panel_split_ratio"] == 0.25


@pytest.mark.parametrize("name", ["_migrate_2_to_3", "_run_migrations", "_prune_unknown_keys"])
def test_legacy_migration_wrappers_resolve_reporter_at_call_time(monkeypatch, name):
    from core import settings_manager as manager

    first, second = [], []
    for reports in (first, second):
        monkeypatch.setattr(manager, "_log_error", lambda *message: reports.append(message))
        stored = {"future": 1}
        arguments = (stored, 2) if name == "_run_migrations" else (stored,)
        assert getattr(manager, name)(*arguments) is None
        assert "future" not in stored
    expected = [("WARNING", "Ignored 1 unknown settings key(s): future")]
    assert first == expected
    assert second == expected


def test_error_sink_replacement_stays_in_manager(monkeypatch):
    from core import settings_manager as manager

    monkeypatch.setattr(manager, "_error_sink", manager._error_sink)
    first, second = [], []
    manager.set_error_sink(lambda *message: first.append(message))
    manager._prune_unknown_keys({"future": 1})
    manager.set_error_sink(lambda *message: second.append(message))
    manager._prune_unknown_keys({"future": 1})
    expected = [("WARNING", "Ignored 1 unknown settings key(s): future")]
    assert first == expected
    assert second == expected


def test_i18n_language_resolution_does_not_import_settings_owner(tmp_path):
    script = r'''
import importlib.abc
import os
import sys
from pathlib import Path

blocked = ("core.settings_manager", "core.log_service")
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
from gui.i18n import resolve_language
from PySide6.QtCore import QLocale
assert resolve_language("zh_HK") == "zh_HK"
assert resolve_language("Auto", QLocale("en_US")) == "en_US"
assert not any(
    name == item or name.startswith(item + ".")
    for name in sys.modules for item in blocked
)
assert not list(Path(os.environ["XDG_CONFIG_HOME"]).rglob("app_settings.json"))
'''
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "QT_QPA_PLATFORM": "offscreen"}
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                 "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR", "TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
