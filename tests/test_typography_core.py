"""验证字体核心层、独立信号和设置批量持久化。"""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtGui import QFont

from core import settings_manager
from gui.styles import BaseStyles
from gui.styles.fonts import _font
from gui.styles.typography import (
    LOG_FONT_SIZE_MAX,
    UI_FONT_SIZE_MAX,
    FontConfig,
    TypographyManager,
    font_config_from_mapping,
    system_ui_font_family,
    typography_manager,
)


def test_font_config_validates_sizes_and_falls_back_to_system_family():
    config = font_config_from_mapping(
        {
            "font_family": "ADBLab Missing Font 9F3E",
            "ui_font_size": 999,
            "log_font_size": "invalid",
        }
    )

    assert config.ui_family == system_ui_font_family()
    assert config.ui_size == UI_FONT_SIZE_MAX
    assert config.log_size == 9
    assert config.mono_family


def test_typography_manager_emits_only_changed_role_and_sets_application_font(
    qt_application,
):
    previous_application_font = QFont(qt_application.font())
    manager = TypographyManager()
    initial = manager.config
    ui_events = []
    log_events = []
    all_events = []
    manager.ui_font_changed.connect(ui_events.append)
    manager.log_font_changed.connect(log_events.append)
    manager.fonts_changed.connect(all_events.append)

    ui_size = 13 if initial.ui_size != 13 else 14
    ui_config = replace(initial, ui_size=ui_size)
    manager.apply(ui_config)

    assert ui_events == [ui_config]
    assert log_events == []
    assert all_events == [ui_config]
    assert qt_application.font().pointSize() == ui_size

    log_size = LOG_FONT_SIZE_MAX if ui_config.log_size != LOG_FONT_SIZE_MAX else 8
    log_config = replace(ui_config, log_size=log_size)
    manager.apply(log_config)

    assert ui_events == [ui_config]
    assert log_events == [log_config]
    assert all_events == [ui_config, log_config]
    qt_application.setFont(previous_application_font)


def test_reload_updates_legacy_projection_before_signal_and_does_not_emit_theme(
    qt_application,
):
    previous_config = typography_manager.config
    previous_application_font = QFont(qt_application.font())
    next_ui_size = 15 if previous_config.ui_size != 15 else 16
    next_log_size = 11 if previous_config.log_size != 11 else 12
    fake_settings = SimpleNamespace(
        get=lambda key, default=None: {
            "font_family": "",
            "ui_font_size": next_ui_size,
            "log_font_size": next_log_size,
        }.get(key, default)
    )
    font_events = []
    theme_events = []

    def capture_font_event(config: FontConfig) -> None:
        font_events.append(
            (
                config,
                BaseStyles.DEFAULT_FONT_FAMILY,
                BaseStyles.DEFAULT_FONT_SIZE,
                BaseStyles.LOG_FONT_SIZE_VAR,
                dict(_font),
            )
        )

    BaseStyles.fonts_changed.connect(capture_font_event)
    BaseStyles.theme_changed.connect(theme_events.append)
    try:
        with patch.object(settings_manager.AppSettings, "instance", return_value=fake_settings):
            config = BaseStyles.reload_from_settings()

        assert len(font_events) == 1
        event_config, family, ui_size, log_size, qss_projection = font_events[0]
        assert event_config == config
        assert family == config.ui_family
        assert ui_size == config.ui_size
        assert log_size == config.log_size
        assert qss_projection == {
            "FAMILY": config.ui_family,
            "UI": config.ui_size,
            "LOG": config.log_size,
        }
        assert theme_events == []
        assert qt_application.font().pointSize() == config.ui_size
    finally:
        BaseStyles.fonts_changed.disconnect(capture_font_event)
        BaseStyles.theme_changed.disconnect(theme_events.append)
        BaseStyles._sync_legacy_values(previous_config)
        typography_manager.apply(previous_config)
        qt_application.setFont(previous_application_font)


def test_settings_update_validates_fonts_and_schedules_one_save(tmp_path, monkeypatch):
    settings_file = tmp_path / "config" / "app_settings.json"
    legacy_file = tmp_path / "legacy" / "app_settings.json"
    old_instance = settings_manager.AppSettings._instance
    created_timers = []

    class FakeTimer:
        def __init__(self, interval, callback):
            self.interval = interval
            self.callback = callback
            self.daemon = False
            self.started = False
            self.cancelled = False
            created_timers.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(legacy_file))
    monkeypatch.setattr(settings_manager.threading, "Timer", FakeTimer)
    settings_manager.AppSettings._instance = None
    try:
        settings = settings_manager.AppSettings.instance()
        settings.update(
            {
                "font_family": "  System Default  ",
                "ui_font_size": 100,
                "log_font_size": "invalid",
            }
        )

        assert settings.get("font_family") == ""
        assert settings.get("ui_font_size") == 22
        assert settings.get("log_font_size") == 9
        assert len(created_timers) == 1
        assert created_timers[0].interval == 0.5
        assert created_timers[0].daemon is True
        assert created_timers[0].started is True

        created_timers[0].callback()
        stored = json.loads(settings_file.read_text(encoding="utf-8"))
        assert stored["font_family"] == ""
        assert stored["ui_font_size"] == 22

        settings.set_many({"log_font_size": 100})
        assert settings.get("log_font_size") == 16
        assert len(created_timers) == 2
        assert created_timers[0].cancelled is True
    finally:
        if settings_manager.AppSettings._instance is not None:
            timer = settings_manager.AppSettings._instance._save_timer
            if timer is not None:
                timer.cancel()
        settings_manager.AppSettings._instance = old_instance


def test_settings_atomic_writes_cannot_overwrite_newer_snapshot(tmp_path, monkeypatch):
    """并发保存必须在取得写锁后取快照，最终文件保留最新设置。"""

    settings_file = tmp_path / "app_settings.json"
    old_instance = settings_manager.AppSettings._instance
    first_dump_started = threading.Event()
    release_first_dump = threading.Event()
    dump_lock = threading.Lock()
    dump_count = 0
    original_dump = json.dump

    def controlled_dump(value, file, *args, **kwargs):
        nonlocal dump_count
        with dump_lock:
            dump_count += 1
            current = dump_count
        if current == 1:
            first_dump_started.set()
            assert release_first_dump.wait(2)
        return original_dump(value, file, *args, **kwargs)

    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(settings_manager.json, "dump", controlled_dump)
    settings_manager.AppSettings._instance = None
    try:
        settings = settings_manager.AppSettings.instance()
        with settings._lock:
            settings._data["theme"] = "Light"

        first = threading.Thread(target=settings._save_atomic)
        first.start()
        assert first_dump_started.wait(2)

        with settings._lock:
            settings._data["theme"] = "Dark"
        second = threading.Thread(target=settings._save_atomic)
        second.start()
        release_first_dump.set()
        first.join(2)
        second.join(2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert json.loads(settings_file.read_text(encoding="utf-8"))["theme"] == "Dark"
    finally:
        release_first_dump.set()
        settings_manager.AppSettings._instance = old_instance


def test_settings_load_migrates_legacy_panel_widths_to_ratio(tmp_path, monkeypatch):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(
        json.dumps({"left_panel_width": 300, "right_panel_width": 900}),
        encoding="utf-8",
    )
    old_instance = settings_manager.AppSettings._instance
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    settings_manager.AppSettings._instance = None
    try:
        settings = settings_manager.AppSettings.instance()

        assert settings.get("panel_split_ratio") == 0.25
        stored = json.loads(settings_file.read_text(encoding="utf-8"))
        assert stored["panel_split_ratio"] == 0.25
    finally:
        settings_manager.AppSettings._instance = old_instance
