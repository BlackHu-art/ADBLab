"""验证正式设置键在应用重建后的持久化与旧 JSON 兼容性。"""

from __future__ import annotations

import json

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
