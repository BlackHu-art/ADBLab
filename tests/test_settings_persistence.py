"""验证正式设置键在应用重建后的持久化与旧 JSON 兼容性。"""

from __future__ import annotations

import json
import threading
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
            current.close()
        settings_manager.AppSettings._instance = previous_instance


def test_deferred_migration_loads_values_before_writing_and_flushes_latest_update(
    isolated_settings, monkeypatch,
):
    isolated_settings.parent.mkdir(parents=True)
    source = '{"theme": "Dark", "ui_scale": 1.5}'
    isolated_settings.write_text(source, encoding="utf-8")

    settings = settings_manager.AppSettings.instance(defer_migration_save=True)
    assert settings.get("theme") == "Dark"
    assert settings.get("ui_scale") == 1.5
    assert isolated_settings.read_text(encoding="utf-8") == source

    monkeypatch.setattr(settings, "_schedule_save", lambda: None)
    settings.set("theme", "Light")
    assert settings.flush_deferred_save() is True
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["theme"] == "Light"
    assert stored["ui_scale"] == 1.5
    assert stored["schema_version"] == settings_manager.CURRENT_SCHEMA_VERSION
    assert settings.flush_deferred_save() is True


def test_deferred_legacy_copy_retries_after_save_failure(
    isolated_settings, monkeypatch,
):
    legacy_file = isolated_settings.parent.parent / "legacy" / "app_settings.json"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text('{"theme": "Dark"}', encoding="utf-8")
    settings = settings_manager.AppSettings.instance(defer_migration_save=True)
    assert settings.get("theme") == "Dark"
    assert not isolated_settings.exists()

    errors = Mock()
    with monkeypatch.context() as failure:
        failure.setattr(settings_manager, "_log_error", errors)
        failure.setattr(
            settings_manager.os, "replace", Mock(side_effect=PermissionError("private")),
        )
        assert settings.flush_deferred_save() is False
    errors.assert_called_once_with("ERROR", "Failed to save settings: PermissionError")
    assert not isolated_settings.exists()
    assert settings.flush_deferred_save() is True
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == "Dark"


def test_deferred_load_without_file_does_not_create_settings(isolated_settings):
    settings = settings_manager.AppSettings.instance(defer_migration_save=True)
    assert settings.flush_deferred_save() is True
    assert not isolated_settings.exists()


def test_defer_option_on_existing_instance_does_not_change_default_migration(
    isolated_settings,
):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text('{"theme": "Dark"}', encoding="utf-8")
    settings = settings_manager.AppSettings.instance()
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["schema_version"] == 3
    assert settings_manager.AppSettings.instance(defer_migration_save=True) is settings
    assert settings.flush_deferred_save() is True


def test_regular_save_clears_deferred_migration_without_duplicate_flush(
    isolated_settings, monkeypatch,
):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text('{"theme": "Dark"}', encoding="utf-8")
    settings = settings_manager.AppSettings.instance(defer_migration_save=True)
    monkeypatch.setattr(settings, "_schedule_save", lambda: None)
    settings.set("theme", "Light")
    assert settings._save_atomic() is True
    with monkeypatch.context() as blocked:
        blocked.setattr(
            settings_manager.os, "replace", Mock(side_effect=AssertionError("duplicate write")),
        )
        assert settings.flush_deferred_save() is True
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == "Light"


def test_deferred_flush_reads_latest_snapshot_after_contending_save(
    isolated_settings, monkeypatch,
):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text('{"theme": "Dark"}', encoding="utf-8")
    settings = settings_manager.AppSettings.instance(defer_migration_save=True)
    monkeypatch.setattr(settings, "_schedule_save", lambda: None)
    entered = threading.Event()
    result = []

    def flush():
        entered.set()
        result.append(settings.flush_deferred_save())

    with settings._write_lock:
        worker = threading.Thread(target=flush)
        worker.start()
        assert entered.wait(2)
        settings.set("theme", "Light")
    worker.join(5)
    assert not worker.is_alive()
    assert result == [True]
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == "Light"


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

    settings.close()
    settings_manager.AppSettings._instance = None
    reloaded = settings_manager.AppSettings.instance()

    assert {key: reloaded.get(key) for key in values} == values


@pytest.mark.parametrize("failure_boundary", ["replace", "write"])
def test_failed_atomic_save_preserves_disk_and_retry_saves_latest_state(
    isolated_settings, monkeypatch, failure_boundary,
):
    settings = settings_manager.AppSettings.instance()
    monkeypatch.setattr(settings, "_schedule_save", lambda: None)
    errors = Mock()
    monkeypatch.setattr(settings_manager, "_log_error", errors)
    settings.set("theme", "Light")
    settings._save_atomic()
    original = isolated_settings.read_bytes()
    settings.set("theme", "Dark")
    with monkeypatch.context() as failure:
        if failure_boundary == "replace":
            failure.setattr(
                settings_manager.os, "replace", Mock(side_effect=PermissionError("private")),
            )
        else:
            import errno

            failure.setattr(
                settings_manager.json, "dump", Mock(side_effect=OSError(errno.ENOSPC, "disk full")),
            )
        assert settings._save_atomic() is False
    assert isolated_settings.read_bytes() == original
    assert settings.get("theme") == "Dark"
    assert list(isolated_settings.parent.glob("adblab_settings_*.json")) == []
    errors.assert_called_once()
    settings.set("theme", "System")
    assert settings._save_atomic() is True
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == "System"


@pytest.mark.parametrize("source", ["sdk_home", "sdk_macos", "homebrew_arm64", "homebrew_x64"])
def test_adb_client_preference_round_trips_and_rejects_invalid_values(isolated_settings, source):
    """客户端选择接受自动、命名来源或绝对路径；其它输入回退自动。"""

    settings = settings_manager.AppSettings.instance()
    settings.update({"adb_client": source})
    pending_timer = settings._save_timer
    if pending_timer is not None:
        pending_timer.cancel()
    settings._save_atomic()

    settings.close()
    settings_manager.AppSettings._instance = None
    reloaded = settings_manager.AppSettings.instance()
    assert reloaded.get("adb_client") == source

    custom = str(isolated_settings.parent / "tools/adb")
    reloaded.update({"adb_client": f"  {custom}  "})
    assert reloaded.get("adb_client") == custom

    reloaded.update({"adb_client": "not-a-source"})
    assert reloaded.get("adb_client") == "auto"
    reloaded.update({"adb_client": 7})
    assert reloaded.get("adb_client") == "auto"


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
    settings.close()
    settings_manager.AppSettings._instance = None
    reloaded = settings_manager.AppSettings.instance()
    assert reloaded.get("ui_scale") == 1.75
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert {key: stored[key] for key in saved} == saved


@pytest.mark.parametrize("language", settings_manager.LANGUAGE_OPTIONS)
def test_language_round_trip_keeps_the_current_schema(isolated_settings, language):
    settings = settings_manager.AppSettings.instance()
    settings.set("language", language)
    settings._save_timer.cancel()
    settings._save_atomic()
    settings.close()
    settings_manager.AppSettings._instance = None

    assert settings_manager.AppSettings.instance().get("language") == language
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 3


@pytest.mark.parametrize("language", [None, True, 42, [], {}, "zh_TW", "unsupported"])
def test_invalid_language_uses_auto_on_load_and_update(isolated_settings, language):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        json.dumps({"schema_version": 3, "language": language}), encoding="utf-8",
    )
    settings = settings_manager.AppSettings.instance()
    assert settings.get("language") == "Auto"
    settings.set("language", "en_US")
    settings.set("language", language)
    assert settings.get("language") == "Auto"


def test_current_settings_gain_auto_language_without_rewriting_the_file(isolated_settings):
    saved = '{"schema_version": 3, "theme": "Dark", "font_family": "Arial"}'
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(saved, encoding="utf-8")

    settings = settings_manager.AppSettings.instance()

    assert settings.get("language") == "Auto"
    assert settings.get("theme") == "Dark"
    assert settings.get("font_family") == "Arial"
    assert isolated_settings.read_text(encoding="utf-8") == saved


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

    isolated_settings.parent.mkdir(parents=True, exist_ok=True)
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
    from gui.dialogs.performance_launcher_log import PerformanceLauncherLog

    isolated_settings.parent.mkdir(parents=True, exist_ok=True)
    isolated_settings.write_text(
        json.dumps({"schema_version": 3, "log_max_lines": invalid_count}), encoding="utf-8"
    )
    settings = settings_manager.AppSettings.instance()

    limit = settings.get("log_max_lines")
    assert PerformanceLauncherLog._configured_log_max_lines() == limit

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


@pytest.mark.parametrize("defer", [False, True])
def test_future_legacy_copy_keeps_unknown_fields_and_seen_version(
    isolated_settings, monkeypatch, defer,
):
    legacy = isolated_settings.parent.parent / "legacy" / "app_settings.json"
    legacy.parent.mkdir(parents=True)
    source = {
        "schema_version": 99, "log_max_lines": "2500", "theme": "dark",
        "future": {"items": [1, 2]},
        "monkey_params": {"events": "12345", "future_monkey": {"enabled": True}},
    }
    legacy.write_text(json.dumps(source), encoding="utf-8")
    reports = []
    monkeypatch.setattr(settings_manager, "_log_error", lambda *message: reports.append(message))

    settings = settings_manager.AppSettings.instance(defer_migration_save=defer)
    assert isolated_settings.exists() is (not defer)
    assert settings.get("log_max_lines") == 2500
    assert settings.get("theme") == "Dark"
    assert settings.get("monkey_params")["events"] == 12345
    assert settings.get("monkey_params")["future_monkey"] == {"enabled": True}
    if defer:
        assert settings.flush_deferred_save() is True
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 99
    assert stored["future"] == {"items": [1, 2]}
    assert stored["log_max_lines"] == 2500
    assert stored["monkey_params"]["future_monkey"] == {"enabled": True}
    assert reports == [(
        "WARNING", "Settings schema v99 is newer than supported v3; "
        "known keys loaded, file left untouched",
    )]
    assert legacy.read_text(encoding="utf-8") == json.dumps(source)


def test_current_schema_normalization_does_not_rewrite_source_on_load(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    source = b'{"schema_version": 3, "log_max_lines": false, "theme": "dark", "future": 1}'
    isolated_settings.write_bytes(source)

    settings = settings_manager.AppSettings.instance()

    assert settings.get("log_max_lines") == 2000
    assert settings.get("theme") == "Dark"
    assert settings.get("future") is None
    assert isolated_settings.read_bytes() == source


def test_runtime_unknown_keys_and_reset_preserve_future_metadata(isolated_settings, monkeypatch):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text(
        '{"schema_version": 99, "future": {"items": [1]}, "theme": "Dark"}',
        encoding="utf-8",
    )
    settings = settings_manager.AppSettings.instance()
    with monkeypatch.context() as updates:
        updates.setattr(settings, "_schedule_save", lambda: None)
        settings.update({"runtime_unknown": {"value": 2}})
        assert settings.get("runtime_unknown") == {"value": 2}
        settings.reset()
        assert settings.get("runtime_unknown") is None
        assert settings.get("theme") == "System"
        assert settings.close() is True
    stored = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 99
    assert stored["future"] == {"items": [1]}
    assert stored["theme"] == "System"


def test_corrupt_settings_are_backed_up_before_defaults(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    original = '{"theme": "Dark", "ui_font_size": '
    isolated_settings.write_text(original, encoding="utf-8")

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == settings_manager.DEFAULTS["theme"]
    backups = list(isolated_settings.parent.glob("app_settings.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert settings.close() is True
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == (
        settings_manager.DEFAULTS["theme"]
    )


def test_deeply_nested_settings_fall_back_without_recursion_error(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    # 构造真正超过 json 解码递归上限的对象，而不是多个平铺空数组。
    isolated_settings.write_text(
        '{"theme":' + "[" * 1500 + "]" * 1500 + "}",
        encoding="utf-8",
    )

    settings = settings_manager.AppSettings.instance()

    assert settings.get("theme") == settings_manager.DEFAULTS["theme"]
    assert list(isolated_settings.parent.glob("app_settings.json.corrupt-*"))


def test_unbacked_corrupt_settings_are_never_overwritten(isolated_settings, monkeypatch):
    isolated_settings.parent.mkdir(parents=True)
    original = '{"theme": "Dark", '
    isolated_settings.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        settings_manager.os,
        "replace",
        Mock(side_effect=PermissionError("locked")),
    )

    settings = settings_manager.AppSettings.instance()
    settings.set("theme", "Light")

    assert settings._unreadable_settings is True
    assert settings.close() is False
    assert isolated_settings.read_text(encoding="utf-8") == original


def test_transient_settings_io_error_is_not_renamed_as_corrupt(
    isolated_settings, monkeypatch,
):
    isolated_settings.parent.mkdir(parents=True)
    original = '{"theme": "Dark"}'
    isolated_settings.write_text(original, encoding="utf-8")
    real_open = open

    def failing_open(path, *args, **kwargs):
        if str(path) == str(isolated_settings):
            raise PermissionError("locked")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)
    settings = settings_manager.AppSettings.instance()

    assert settings._unreadable_settings is True
    assert isolated_settings.read_text(encoding="utf-8") == original
    assert not list(isolated_settings.parent.glob("app_settings.json.corrupt-*"))
    assert settings.close() is False
    assert isolated_settings.read_text(encoding="utf-8") == original


def test_unreadable_legacy_settings_still_creates_main_file(
    isolated_settings, monkeypatch,
):
    legacy = isolated_settings.parent.parent / "legacy" / "app_settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"theme": "Dark"}', encoding="utf-8")
    real_open = open

    def failing_open(path, *args, **kwargs):
        if str(path) == str(legacy):
            raise PermissionError("locked")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)
    settings = settings_manager.AppSettings.instance()
    settings.set("theme", "Light")
    settings._save_timer.cancel()

    assert settings.close() is True
    assert json.loads(isolated_settings.read_text(encoding="utf-8"))["theme"] == "Light"
