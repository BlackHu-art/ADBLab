"""验证正式设置键在应用重建后的持久化与旧 JSON 兼容性。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import settings_manager


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """把 AppSettings 单例和文件路径隔离到临时目录。"""

    previous_instance = settings_manager.AppSettings._instance
    settings_file = tmp_path / "config" / "app_settings.json"
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(
        settings_manager,
        "LEGACY_SETTINGS_FILE",
        str(tmp_path / "legacy" / "app_settings.json"),
    )
    settings_manager.AppSettings._instance = None
    try:
        yield settings_file
    finally:
        current = settings_manager.AppSettings._instance
        if current is not None and current is not previous_instance:
            timer = current._save_timer
            if timer is not None:
                timer.cancel()
        settings_manager.AppSettings._instance = previous_instance


def test_scrcpy_settings_round_trip_across_app_settings_rebuild(isolated_settings):
    values = {
        "scrcpy_preset": "Custom",
        "scrcpy_maxsize": "1920",
        "scrcpy_fps": "60",
        "scrcpy_codec": "h265",
        "scrcpy_buffer": "20",
        "scrcpy_bitrate": "12",
        "scrcpy_orientation": "90",
    }
    settings = settings_manager.AppSettings.instance()
    settings.update(values)
    pending_timer = settings._save_timer
    if pending_timer is not None:
        pending_timer.cancel()
    settings._save_atomic()

    settings_manager.AppSettings._instance = None
    reloaded = settings_manager.AppSettings.instance()

    assert {key: reloaded.get(key) for key in values} == values


def test_existing_json_scrcpy_keys_load_without_migration(isolated_settings):
    existing_values = {
        "theme": "Dark",
        "scrcpy_preset": "Custom",
        "scrcpy_maxsize": 1280,
        "scrcpy_fps": 30,
        "scrcpy_codec": "h264",
        "scrcpy_buffer": 50,
        "scrcpy_bitrate": 8,
        "scrcpy_orientation": 270,
        "retired_remote_setting": "must-not-load",
    }
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps(existing_values, ensure_ascii=False),
        encoding="utf-8",
    )

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == "Dark"
    assert settings.get("scrcpy_preset") == "Custom"
    assert settings.get("scrcpy_maxsize") == "1280"
    assert settings.get("scrcpy_fps") == "30"
    assert settings.get("scrcpy_buffer") == "50"
    assert settings.get("scrcpy_bitrate") == "8"
    assert settings.get("scrcpy_orientation") == "270"
    assert settings.get("retired_remote_setting") is None


def test_appearance_settings_are_normalized_when_loaded(isolated_settings):
    existing_values = {
        "theme": "auto",
        "accent_color": "#1a2b3c",
        "mica_enabled": False,
    }
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps(existing_values, ensure_ascii=False),
        encoding="utf-8",
    )

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == "System"
    assert settings.get("accent_color") == "#1A2B3C"
    assert settings.get("mica_enabled") is False


def test_invalid_appearance_settings_fall_back_to_fluent_defaults(isolated_settings):
    existing_values = {
        "theme": "neon",
        "accent_color": "blue",
        "mica_enabled": "yes",
    }
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps(existing_values, ensure_ascii=False),
        encoding="utf-8",
    )

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == settings_manager.DEFAULTS["theme"]
    assert settings.get("accent_color") == settings_manager.DEFAULTS["accent_color"]
    assert settings.get("mica_enabled") is settings_manager.DEFAULTS["mica_enabled"]


def test_saved_file_stamps_current_schema_version(isolated_settings):
    settings = settings_manager.AppSettings.instance()
    settings.update({"theme": "Dark"})
    pending_timer = settings._save_timer
    if pending_timer is not None:
        pending_timer.cancel()
    settings._save_atomic()

    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == settings_manager.CURRENT_SCHEMA_VERSION
    assert stored["theme"] == "Dark"


@pytest.mark.parametrize("value,expected", [
    ("Auto", "Auto"), (" auto ", "Auto"), (1, 1.0), (1.25, 1.25),
    ("1.5", 1.5), (1.75, 1.75), (2, 2.0), (None, "Auto"),
    (True, "Auto"), (0, "Auto"), (1.1, "Auto"), ("150%", "Auto"),
    (float("nan"), "Auto"), (float("inf"), "Auto"), ({}, "Auto"),
])
def test_display_scale_accepts_supported_factors_and_rejects_invalid_values(
    isolated_settings, value, expected,
):
    settings = settings_manager.AppSettings.instance()
    settings.set("ui_scale", value)
    assert settings.get("ui_scale") == expected


def test_current_settings_gain_auto_scale_without_rewriting_existing_fonts(isolated_settings):
    saved = {"schema_version": 3, "font_family": "Arial", "ui_font_size": 17, "log_font_size": 11}
    isolated_settings.parent.mkdir(parents=True)
    source = json.dumps(saved)
    isolated_settings.write_text(source, encoding="utf-8")
    settings = settings_manager.AppSettings.instance()

    assert settings.get("ui_scale") == "Auto"
    assert settings.get("font_family") == "Arial"
    assert settings.get("ui_font_size") == 17
    assert settings.get("log_font_size") == 11
    assert isolated_settings.read_text(encoding="utf-8") == source

    settings.set("ui_scale", 1.75)
    settings._save_timer.cancel()
    settings._save_atomic()
    settings_manager.AppSettings._instance = None
    reloaded = settings_manager.AppSettings.instance()
    assert reloaded.get("ui_scale") == 1.75
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert {key: stored[key] for key in saved} == saved


def test_v1_file_migrates_and_stamps_current_schema_version(isolated_settings):
    legacy = {
        "theme": "Dark",
        "left_panel_width": 300,
        "right_panel_width": 900,
        "monkey_params": {"events": 5000, "package_name": "com.example"},
        "retired_setting": "drop-me",
    }
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == "Dark"
    assert settings.get("panel_split_ratio") == 0.25
    assert settings.get("device_scan_interval_ms") == 15000
    monkey = settings.get("monkey_params")
    assert monkey["events"] == 5000
    assert monkey["throttle"] == 300
    assert "package_name" not in monkey

    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == settings_manager.CURRENT_SCHEMA_VERSION
    assert "retired_setting" not in stored
    # 左右像素宽度仍是活跃设置键（窗口布局在读），迁移只补充比例，不删除像素键。
    assert stored["panel_split_ratio"] == 0.25
    assert stored["left_panel_width"] == 300


def test_unknown_keys_pruned_with_warning(isolated_settings):
    captured = []

    def sink(level, message):
        captured.append((level, message))

    settings_manager.set_error_sink(sink)
    try:
        legacy = {
            "theme": "Dark",
            "retired_setting": "x",
            "monkey_params": {"events": 100, "package_name": "com.example"},
        }
        isolated_settings.parent.mkdir(parents=True)
        isolated_settings.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        settings = settings_manager.AppSettings.instance()

        assert settings.get("theme") == "Dark"
        assert settings.get("retired_setting") is None
        warnings = [message for level, message in captured if level == "WARNING"]
        assert any("retired_setting" in message for message in warnings)
        assert any("package_name" in message for message in warnings)
    finally:
        settings_manager.set_error_sink(None)


def test_future_schema_version_keeps_known_values_and_version(isolated_settings):
    future = {"schema_version": 99, "theme": "Dark", "future_key": "keep-me"}
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(json.dumps(future, ensure_ascii=False), encoding="utf-8")

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == "Dark"
    settings.update({"ui_font_size": 14})
    pending_timer = settings._save_timer
    if pending_timer is not None:
        pending_timer.cancel()
    settings._save_atomic()

    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 99
    assert stored["theme"] == "Dark"
    assert stored["future_key"] == "keep-me"


def test_update_ignores_schema_version(isolated_settings):
    settings = settings_manager.AppSettings.instance()
    settings.update({"schema_version": 99, "theme": "Dark"})

    assert settings.get("theme") == "Dark"
    assert settings.get("schema_version") is None

    pending_timer = settings._save_timer
    if pending_timer is not None:
        pending_timer.cancel()
    settings._save_atomic()
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == settings_manager.CURRENT_SCHEMA_VERSION


@pytest.mark.parametrize("schema_version", [2, 3, 99])
@pytest.mark.parametrize("monkey_params", [[], None, {"events": "invalid"}])
def test_malformed_saved_monkey_settings_are_safe_for_panel_loading(
    isolated_settings, schema_version, monkey_params
):
    from gui.panels.app_panel import AppPanel

    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps({"schema_version": schema_version, "monkey_params": monkey_params}),
        encoding="utf-8",
    )
    settings = settings_manager.AppSettings.instance()
    panel = SimpleNamespace(
        monkey_events=Mock(),
        monkey_throttle=Mock(),
        _format_monkey_throttle=AppPanel._format_monkey_throttle,
        _monkey_pct_combos={},
        monkey_chk_crashes=Mock(),
        monkey_chk_timeouts=Mock(),
        monkey_chk_security=Mock(),
        _update_pct_total=Mock(),
    )

    AppPanel._load_monkey_params(panel)

    assert settings.get("monkey_params")["events"] == 10000
    panel.monkey_events.setText.assert_called_once_with("10000")
    panel.monkey_throttle.setText.assert_called_once_with("300 ms")


@pytest.mark.parametrize("invalid_count", ["invalid", None, [], True, 0, -1])
def test_invalid_saved_log_limit_is_safe_for_log_consumer(isolated_settings, invalid_count):
    from gui.panels.log_panel import LogPanel

    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps({"schema_version": 3, "log_max_lines": invalid_count}), encoding="utf-8"
    )
    settings = settings_manager.AppSettings.instance()

    limit = settings.get("log_max_lines")
    LogPanel._trim_excess(SimpleNamespace(_entries=[], _max_lines=limit))

    assert type(limit) is int
    assert limit == settings_manager.DEFAULTS["log_max_lines"]


@pytest.mark.parametrize("invalid_directory", [[], {}, None, True, 123])
def test_invalid_saved_directory_uses_default_without_type_error(
    isolated_settings, invalid_directory
):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps({"schema_version": 3, "save_directory": invalid_directory}), encoding="utf-8"
    )
    settings = settings_manager.AppSettings.instance()

    assert isinstance(settings.save_directory, str)
    assert settings.get("save_directory") == ""


def test_valid_known_settings_and_future_fields_survive_normalization_and_save(isolated_settings):
    saved_directory = isolated_settings.parent / "saved files "
    saved_directory.mkdir(parents=True)
    original = {
        "schema_version": 99,
        "save_directory": str(saved_directory),
        "log_max_lines": 2500,
        "monkey_params": {
            **settings_manager.DEFAULTS["monkey_params"],
            "events": 12345,
            "throttle": 250,
            "ignore_crashes": False,
            "future_option": "preserved",
        },
        "future_top_level": "preserved",
    }
    isolated_settings.write_text(json.dumps(original), encoding="utf-8")

    settings = settings_manager.AppSettings.instance()
    settings._save_atomic()

    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    for key, value in original.items():
        assert stored[key] == value


def test_runtime_updates_use_the_same_safe_settings_boundary(isolated_settings):
    settings = settings_manager.AppSettings.instance()

    settings.update({"monkey_params": [], "log_max_lines": "invalid", "save_directory": []})
    timer = settings._save_timer
    if timer is not None:
        timer.cancel()

    assert settings.get("monkey_params") == settings_manager.DEFAULTS["monkey_params"]
    assert settings.get("log_max_lines") == settings_manager.DEFAULTS["log_max_lines"]
    assert settings.get("save_directory") == ""


def test_numeric_text_and_legacy_throttle_units_keep_their_values(isolated_settings):
    settings = settings_manager.AppSettings.instance()
    settings.update(
        {
            "log_max_lines": "2500",
            "monkey_params": {
                "events": "12345",
                "throttle": " 60000 ms ",
                "touch": "25",
                "ignore_crashes": False,
            },
        }
    )
    timer = settings._save_timer
    if timer is not None:
        timer.cancel()

    assert settings.get("log_max_lines") == 2500
    monkey = settings.get("monkey_params")
    assert monkey["events"] == 12345
    assert monkey["throttle"] == 60000
    assert monkey["touch"] == 25
    assert monkey["ignore_crashes"] is False
