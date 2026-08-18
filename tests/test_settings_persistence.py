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
