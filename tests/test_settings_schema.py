"""设置纯规则保持现有值域、复制语义和无设置 I/O 的导入边界。"""

from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.mark.parametrize(("key", "value", "expected"), [
    ("ui_scale", True, "Auto"), ("ui_scale", 1.5, 1.5),
    ("ui_scale", "150%", "Auto"), ("language", "zh_HK", "zh_HK"),
    ("language", "zh_TW", "Auto"), ("save_directory", " path ", " path "),
    ("log_max_lines", True, 2000), ("log_max_lines", "2500", 2500),
    ("log_max_lines", 0, 2000), ("console_log_level", " error ", "ERROR"),
    ("console_log_level", None, "DEBUG"), ("theme", "auto", "System"),
    ("accent_color", "#1a2b3c", "#1A2B3C"), ("ui_font_size", 2, 8),
    ("ui_font_size", 40, 22), ("log_font_size", 1, 7),
    ("log_font_size", 99, 16), ("ui_font_size", True, 12),
    ("panel_split_ratio", -1, 0.2), ("device_log_split_ratio", 1.0, 0.7),
    ("panel_split_ratio", True, 0.5), ("font_family", " x ", "x"),
    ("font_family", "System Default", ""), ("font_family", "x" * 140, "x" * 128),
    ("scrcpy_fps", None, "30"), ("scrcpy_fps", False, "30"),
    ("scrcpy_fps", "x" * 140, "x" * 128), ("scrcpy_fps", " 60 ", "60"),
])
def test_schema_preserves_normalization_contract(key, value, expected):
    from core.settings.schema import normalise_setting

    assert normalise_setting(key, value) == expected


def test_schema_unknown_key_preserves_object_identity():
    from core.settings.schema import normalise_setting

    value = object()
    assert normalise_setting("future", value) is value


def test_schema_monkey_copy_preserves_future_fields_and_defaults():
    from core.settings.schema import DEFAULTS, normalise_setting

    source = {
        "events": "12345", "throttle": " 60000 ms ", "ignore_crashes": "false",
        "future": {"items": [1, 2]},
    }
    original = deepcopy(source)
    defaults = deepcopy(DEFAULTS)
    result = normalise_setting("monkey_params", source)
    assert result["events"] == 12345
    assert result["throttle"] == 60000
    assert result["ignore_crashes"] is True
    assert result["future"] == {"items": [1, 2]}
    assert result["future"] is not source["future"]
    assert result["future"]["items"] is not source["future"]["items"]
    assert source == original
    assert DEFAULTS == defaults
    first = normalise_setting("monkey_params", None)
    second = normalise_setting("monkey_params", False)
    assert first == second == DEFAULTS["monkey_params"]
    assert first is not second and first is not DEFAULTS["monkey_params"]


def test_schema_adb_preference_uses_shape_without_filesystem_lookup(tmp_path):
    from core.settings.schema import normalise_setting
    from utils.adb_resolver import CLIENT_SOURCE_TOKENS

    missing = tmp_path / "missing" / "adb"
    assert not missing.exists()
    assert normalise_setting("adb_client", f"  {missing}  ") == str(missing)
    long_path = str(tmp_path / ("a" * 600))
    assert normalise_setting("adb_client", long_path) == long_path[:512]
    for token in CLIENT_SOURCE_TOKENS:
        assert normalise_setting("adb_client", token) == token
    assert normalise_setting("adb_client", object()) == "auto"
    assert normalise_setting("adb_client", "relative/adb") == "auto"


def test_pure_schema_import_has_no_settings_or_qt_side_effects(tmp_path):
    script = r'''
import importlib.abc
import os
import sys
from pathlib import Path
import utils.user_data as user_data
import utils.resource_path as resource

root = Path(os.environ["XDG_CONFIG_HOME"])
sentinel = root / "sentinel"
sentinel.write_text("unchanged", encoding="utf-8")
def forbidden_path(*args, **kwargs):
    raise AssertionError("path resolver called")
user_data.user_config_path = forbidden_path
resource.resource_path = forbidden_path
blocked = ("core.settings_manager", "core.log_service", "PySide6", "qfluentwidgets")
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
from core.settings.schema import normalise_language, normalise_ui_scale, normalise_setting
assert normalise_language("zh_HK") == "zh_HK"
assert normalise_ui_scale(1.5) == 1.5
assert normalise_setting("log_max_lines", "2500") == 2500
assert not any(
    name == item or name.startswith(item + ".")
    for name in sys.modules for item in blocked
)
assert sentinel.read_text(encoding="utf-8") == "unchanged"
assert not list(root.rglob("app_settings.json"))
'''
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                 "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR", "TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
