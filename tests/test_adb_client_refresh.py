"""ADB 设置重置和候选刷新回归。"""

import platform
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QWidget

from core.exec import CommandResult
from core.settings_manager import DEFAULTS, AppSettings
from gui.pages.fluent_pages import SettingsPage
from gui.widgets import adb_client_card as cards
from services import adb_clients
from services.adb_clients import ClientProbe
from utils.adb_resolver import AdbCandidate

pytestmark = pytest.mark.ui


def _assert_unique_selected_auto(card):
    buttons = card._group.buttons()
    auto_buttons = [button for button in buttons if button.property("adbKey") == "auto"]
    recommended = card.client_button("auto")
    assert auto_buttons == [recommended]
    assert [button for button in buttons if button.isChecked()] == [recommended]
    assert recommended.isEnabled()
    assert card.selection() == "auto"


@pytest.mark.parametrize("system,release,expected", [
    ("Windows", None, "Windows 下自动选择"),
    ("Darwin", None, "macOS 下自动选择"),
    ("Linux", {"ID": "ubuntu"}, "Ubuntu 下自动选择"),
    ("Linux", {"ID": "debian"}, "Linux 下自动选择"),
    ("Linux", {"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, "Linux 下自动选择"),
    ("Linux", {}, "Linux 下自动选择"),
    ("Linux", OSError("unavailable"), "Linux 下自动选择"),
    ("Linux", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"), "Linux 下自动选择"),
])
def test_auto_choice_shows_host_system_in_summary_and_recommended_row(
    monkeypatch, qt_application, system, release, expected,
):
    monkeypatch.setattr(platform, "system", lambda: system)

    def read_release():
        if release is None:
            pytest.fail("Windows 和 macOS 不应读取 Linux 发行版信息")
        if isinstance(release, Exception):
            raise release
        return release

    monkeypatch.setattr(platform, "freedesktop_os_release", read_release)
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    card.resize(750, 600)
    card.show()
    try:
        assert card.card.contentLabel.isVisibleTo(card)
        assert card.card.contentLabel.text() == expected
        card.setExpand(True)
        qt_application.processEvents()
        labels = card.client_button("auto").parentWidget().findChildren(QLabel)
        assert any(
            label.isVisibleTo(card) and label.text() == f"{expected}（推荐）"
            for label in labels
        )
        _assert_unique_selected_auto(card)
    finally:
        card.close()


def test_host_label_preserves_manual_selection_and_busy_status(monkeypatch, qt_application):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "freedesktop_os_release", lambda: {"ID": "ubuntu"})
    candidates = [AdbCandidate("PATH", "C:/fixture/path/adb.exe")]
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: candidates)
    card = cards.AdbClientSettingCard()
    selected = []
    card.client_selected.connect(selected.append)
    try:
        card.apply_probes([ClientProbe("PATH", candidates[0].path, True, True, "1.0.41")])
        card.set_selection("PATH")
        assert card.card.contentLabel.text() == "系统 PATH · 1.0.41"
        assert card.selection() == "PATH"
        assert card.client_button("PATH").isChecked()

        card.set_custom_path("C:/fixture/custom/adb.exe")
        card.set_selection("C:/fixture/custom/adb.exe")
        assert card.card.contentLabel.text() == "自定义 · C:/fixture/custom/adb.exe"
        assert card.client_button("custom").isChecked()

        card.set_busy(True)
        card.set_selection("auto")
        assert card.card.contentLabel.text() == "正在识别本地 ADB 环境…可继续选择"
        assert not card.rescan_button().isEnabled()
        card.set_busy(False)
        assert card.card.contentLabel.text() == "Ubuntu 下自动选择"
        assert card.custom_path() == "C:/fixture/custom/adb.exe"
        assert selected == []
        _assert_unique_selected_auto(card)
    finally:
        card.close()


@pytest.mark.parametrize("sources", [(), ("bundled",), ("bundled", "PATH")])
def test_auto_choice_stays_unique_and_selected_through_repeated_refresh(
    monkeypatch, qt_application, sources,
):
    candidates = [AdbCandidate(source, f"C:/fixture/{source}/adb.exe") for source in sources]
    probes = [ClientProbe(item.source, item.path, True, True, "1.0.41") for item in candidates]
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: candidates)
    card = cards.AdbClientSettingCard()
    try:
        _assert_unique_selected_auto(card)
        recommended = card.client_button("auto")
        for snapshot, results in ((candidates, probes), ([], []), (candidates, probes)):
            card._on_probes(card._generation, snapshot, results)
            _assert_unique_selected_auto(card)
            assert card.client_button("auto") is recommended
    finally:
        card.close()


@pytest.mark.parametrize("initial_selection", ["auto", "PATH", "C:/fixture/custom/adb.exe"])
def test_clicking_recommended_auto_survives_settings_feedback_and_rescan(
    monkeypatch, qt_application, initial_selection,
):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    values = dict(DEFAULTS, adb_client=initial_selection)
    writes = []

    def save(key, value):
        values[key] = value
        writes.append((key, value))

    monkeypatch.setattr(AppSettings, "instance", classmethod(
        lambda cls: SimpleNamespace(get=values.get, set=save),
    ))
    candidates = [AdbCandidate("PATH", "C:/fixture/path/adb.exe")]
    probes = [ClientProbe("PATH", candidates[0].path, True, True, "1.0.41")]
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: candidates)
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    # 偏好注入是页面对执行层的边界；在此记录真实点击产生的参数，避免污染全局解析状态。
    preferences = []
    monkeypatch.setattr("gui.pages.fluent_pages.set_client_preference", preferences.append)
    frame = Mock()
    frame._always_on_top = False
    page = SettingsPage(frame)
    try:
        card = page.adb_client_card
        card._on_probes(card._generation, candidates, probes)
        card.client_button("auto").click()
        _assert_unique_selected_auto(card)
        assert card.card.contentLabel.text() == "Windows 下自动选择"
        card._on_probes(card._generation, candidates, probes)
        _assert_unique_selected_auto(card)
        assert card.card.contentLabel.text() == "Windows 下自动选择"
        assert values["adb_client"] == "auto"
        assert preferences == ["auto"]
        assert writes == ([] if initial_selection == "auto" else [("adb_client", "auto")])
        frame.recheck_adb_environment.assert_called_once_with()
    finally:
        page.close()


@pytest.mark.parametrize("cancel_after_run", [False, True])
def test_failed_or_cancelled_success_does_not_cache(monkeypatch, tmp_path, cancel_after_run):
    adb_clients.clear_client_probe_cache()
    path = tmp_path / "adb.exe"
    path.write_bytes(b"stub")
    state = {"cancelled": False}
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        state["cancelled"] = cancel_after_run
        return CommandResult(True, output=(
            "Android Debug Bridge version 1.0.41" if cancel_after_run else "invalid"
        ))

    monkeypatch.setattr(adb_clients.CommandRunner, "run", run)
    candidates = [AdbCandidate("PATH", str(path))]
    first = adb_clients.detect_clients(candidates, cancelled=lambda: state["cancelled"])
    assert not first[0].executable
    state["cancelled"] = False
    adb_clients.detect_clients(candidates, cancelled=lambda: state["cancelled"])
    assert len(calls) == 2
    adb_clients.clear_client_probe_cache()


def test_reset_rechecks_runtime_once(monkeypatch, qt_application):
    values = dict(DEFAULTS, adb_client="C:/custom/adb.exe")
    settings = SimpleNamespace(
        get=values.get, set=lambda k, v: values.update({k: v}),
        reset=lambda: (values.clear(), values.update(DEFAULTS)),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    frame = Mock()
    frame._always_on_top = False
    page = SettingsPage(frame)
    page.adb_check_card.set_mode("native")
    page.adb_client_card.set_custom_path("C:/custom/adb.exe")
    page.adb_client_card.set_selection("C:/custom/adb.exe")
    frame.recheck_adb_environment.reset_mock()
    page._reset_settings()
    assert values["adb_client"] == "auto"
    assert page.adb_client_card.selection() == "auto"
    assert page.adb_check_card.mode() == "auto"
    frame.recheck_adb_environment.assert_called_once_with()
    page.close()


def test_scan_adds_and_removes_candidates_from_one_snapshot(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    card = cards.AdbClientSettingCard()
    snapshot = [AdbCandidate("PATH", "C:/new/adb.exe")]
    calls = []
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: snapshot)

    def detect(candidates=None, on_probe=None, **kwargs):
        calls.append(candidates)
        probe = ClientProbe("PATH", snapshot[0].path, True, True, "1.0.41")
        on_probe(probe)
        return [probe]

    monkeypatch.setattr(cards, "detect_clients", detect)
    task = cards._ProbeTask(card._generation, lambda: False)
    task.signals.finished.connect(card._on_probes)
    task.run()
    assert calls == [snapshot]
    assert card.client_button("PATH") is not None
    assert card.client_button("PATH").isEnabled()
    card.close()


def test_progress_updates_first_candidate_without_finishing_detection(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    candidates = [
        AdbCandidate("bundled", "C:/bundle/adb.exe"),
        AdbCandidate("PATH", "C:/path/adb.exe"),
    ]
    try:
        card.set_busy(True)
        card._on_candidates_ready(card._generation, candidates)
        first = ClientProbe("bundled", candidates[0].path, True, True, "1.0.41")
        card._on_probe_progress(card._generation, first)

        assert card.client_button("bundled").isEnabled()
        assert "1.0.41" in card.detail_text("bundled")
        assert not card.client_button("PATH").isEnabled()
        assert card._busy
        assert not card.rescan_button().isEnabled()
    finally:
        card.close()


@pytest.mark.parametrize("late_candidates", [False, True])
def test_watchdog_progress_keeps_timeout_terminal_but_late_finish_fills_rows(
    monkeypatch, qt_application, late_candidates,
):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    generation = card._generation
    candidates = [AdbCandidate("PATH", "C:/path/adb.exe")]
    try:
        card.set_busy(True)
        if not late_candidates:
            card._on_candidates_ready(generation, candidates)
        card._on_detection_timeout()
        timeout_text = card.card.contentLabel.text()
        if late_candidates:
            card._on_candidates_ready(generation, candidates)
        probe = ClientProbe("PATH", candidates[0].path, True, True, "1.0.41")

        card._on_probe_progress(generation, probe)
        assert not card._busy
        assert not card._detection_timer.isActive()
        assert card.card.contentLabel.text() == timeout_text

        card._on_probes(generation, candidates, [probe])
        assert card.client_button("PATH").isEnabled()
        assert card.card.contentLabel.text() == timeout_text
    finally:
        card.close()


@pytest.mark.parametrize("candidate_count, expected_ms", [(2, 25000), (3, 35000)])
def test_candidate_snapshot_extends_watchdog_per_probe(
    monkeypatch, qt_application, candidate_count, expected_ms,
):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    starts = []
    monkeypatch.setattr(card._detection_timer, "start", starts.append)
    try:
        card.set_busy(True)
        card._on_candidates_ready(card._generation, [
            AdbCandidate(f"source-{index}", f"C:/adb{index}.exe")
            for index in range(candidate_count)
        ])
        assert starts == [expected_ms]
    finally:
        card.close()


def test_refresh_preserves_rows_selection_and_releases_removed_widgets(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    card = cards.AdbClientSettingCard()
    card.set_custom_path("C:/custom/adb.exe")
    card.set_selection("C:/custom/adb.exe")
    auto = card.client_button("auto")
    custom = card.client_button("custom")
    card.set_candidates([AdbCandidate("PATH", "C:/adb.exe")])
    card.set_candidates([])
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    base_count = len(card.findChildren(QWidget))
    for _ in range(8):
        card.set_candidates([AdbCandidate("PATH", "C:/adb.exe")])
        card.set_candidates([])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert card.client_button("auto") is auto
    assert card.client_button("custom") is custom
    assert custom.isChecked()
    assert card.custom_path() == "C:/custom/adb.exe"
    assert len(card.findChildren(QWidget)) == base_count
    card.close()


def test_timeout_allows_same_generation_but_retry_rejects_old_snapshot(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    card = cards.AdbClientSettingCard()
    tasks = []
    monkeypatch.setattr(
        cards.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=tasks.append)
    )
    card.start_detection()
    first = card._generation
    card._on_detection_timeout()
    card._on_probes(first, [AdbCandidate("PATH", "C:/adb.exe")],
                    [ClientProbe("PATH", "C:/adb.exe", True, True, "1.0.41")])
    assert card.client_button("PATH").isEnabled()
    card.start_detection()
    card._on_detection_timeout()
    card.start_detection()
    current = card._generation
    old_probe = ClientProbe("env", "C:/old.exe", True, True, "1.0.39")
    card._on_probe_progress(current - 1, old_probe)
    card._on_probes(current - 1, [AdbCandidate("env", "C:/old.exe")], [])
    assert card.client_button("env") is None
    assert not card.rescan_button().isEnabled()
    card._on_probes(current, [], [])
    assert card.client_button("PATH") is None
    assert card.rescan_button().isEnabled()
    card.close()
    card._on_probe_progress(current, ClientProbe("env", "C:/late.exe", True, True, "1.0.41"))
    card._on_probes(current, [AdbCandidate("env", "C:/late.exe")], [])
    assert card.client_button("env") is None


def test_candidate_path_change_clears_old_version_before_new_probe(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    generation = card._generation
    try:
        old = AdbCandidate("PATH", "C:/old/adb.exe")
        card._on_candidates_ready(generation, [old])
        card._on_probe_progress(
            generation, ClientProbe("PATH", old.path, True, True, "1.0.39"),
        )
        assert "1.0.39" in card.detail_text("PATH")

        card._on_candidates_ready(
            generation, [AdbCandidate("PATH", "C:/new/adb.exe")],
        )

        assert "1.0.39" not in card.detail_text("PATH")
        assert not card.client_button("PATH").isEnabled()
    finally:
        card.close()


def test_refresh_preserves_focus_and_moves_it_from_removed_row(monkeypatch, qt_application):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    monkeypatch.setattr(cards.AdbClientSettingCard, "start_detection", lambda self: None)
    card = cards.AdbClientSettingCard()
    card.resize(750, 600)
    card.show()
    card.setExpand(True)
    card.set_candidates([AdbCandidate("PATH", "C:/adb.exe")])
    card.apply_probes([ClientProbe("PATH", "C:/adb.exe", True, True, "1.0.41")])
    card.choose_button().setFocus()
    qt_application.processEvents()
    card.set_candidates([AdbCandidate("PATH", "C:/adb.exe"), AdbCandidate("env", "C:/env.exe")])
    assert card.choose_button().hasFocus()
    card.client_button("PATH").setFocus()
    assert card.client_button("PATH").hasFocus()
    card.set_candidates([])
    assert card.rescan_button().hasFocus()
    card.close()


@pytest.mark.parametrize("source", ["PATH", "sdk_home"])
def test_selected_missing_source_remains_disabled(monkeypatch, qt_application, source):
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    card = cards.AdbClientSettingCard()
    card.set_candidates([AdbCandidate(source, "C:/adb.exe")])
    card.set_selection(source)
    selected = card.client_button(source)
    card.set_candidates([])
    assert card.client_button(source) is selected
    assert selected.isChecked()
    assert not selected.isEnabled()
    assert "不存在" in card.detail_text(source)
    card.close()


def test_settings_destroyed_before_deferred_detection_never_starts_probe(
    monkeypatch, qt_application,
):
    import shiboken6

    values = dict(DEFAULTS)
    settings = SimpleNamespace(get=values.get, set=lambda key, value: values.update({key: value}))
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    starts = Mock()
    monkeypatch.setattr(
        cards.QThreadPool, "globalInstance", lambda: SimpleNamespace(start=starts)
    )
    frame = Mock()
    frame._always_on_top = False
    page = SettingsPage(frame)
    shiboken6.delete(page)

    QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
    qt_application.processEvents()

    starts.assert_not_called()
