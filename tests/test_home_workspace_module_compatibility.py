"""首页与工作区归位后保留旧入口身份、设置接缝及页面契约。"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_EXPORTS = ["ActionCard", "ActionCardView", "DeviceContextCard", "HomePage"]
WORKSPACE_EXPORTS = ["GalleryPage", "WorkspaceSectionPage", "WorkspaceAreaPage"]


@pytest.mark.parametrize("first", ["fluent_pages", "home", "workspace_containers"])
def test_page_import_order_preserves_class_identity(first, tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib
import sys

first = sys.argv[1]
paths = ('fluent_pages', 'home', 'workspace_containers')
names = [first] + [name for name in paths if name != first]
modules = {name: importlib.import_module('gui.pages.' + name) for name in names}
old = modules['fluent_pages']
for leaf, names in (
    ('home', ('ActionCard', 'ActionCardView', 'DeviceContextCard', 'HomePage')),
    ('workspace_containers', ('GalleryPage', 'WorkspaceSectionPage', 'WorkspaceAreaPage')),
):
    for name in names:
        cls = getattr(modules[leaf], name)
        assert getattr(old, name) is cls
        assert cls.__module__ == 'gui.pages.' + leaf
assert old.ActionCard.activated is modules['home'].ActionCard.activated
area = modules['workspace_containers'].WorkspaceAreaPage
assert old.WorkspaceAreaPage.routeChanged is area.routeChanged
""", first],
        cwd=ROOT,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "LOCALAPPDATA": str(tmp_path),
            "APPDATA": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path),
            "XDG_CACHE_HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path),
            "MOBILEPERF_LOG_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, f"exit={result.returncode}\n{result.stdout}{result.stderr}"


def test_aggregate_exports_and_settings_globals_remain_compatible():
    from gui import pages
    from gui.pages import fluent_pages, home, workspace_containers

    assert fluent_pages.__all__ == [
        "ActionCard", "ActionCardView", "AccentColorSettingCard", "ComboSettingCard",
        "DeviceContextCard", "GalleryPage", "HomePage", "SettingsPage",
        "WorkspaceAreaPage", "WorkspaceSectionPage",
    ]
    assert home.__all__ == HOME_EXPORTS
    assert workspace_containers.__all__ == WORKSPACE_EXPORTS
    assert pages.__all__ == ["TaskCenterPage"]
    for name in ("__init__", "_apply_adb_client", "prepare_shutdown"):
        assert getattr(fluent_pages.SettingsPage, name).__globals__ is vars(fluent_pages)
    for name in (
        "_SettingsPathLabel", "_SettingsContentLayout", "SettingsPage",
        "_LocalizedSwitchSettingCard", "ComboSettingCard", "AccentColorSettingCard",
    ):
        assert getattr(fluent_pages, name).__module__ == "gui.pages.fluent_pages"
    for name in (
        "set_client_preference", "invalidate_adb_path_cache", "reset_adb_program_cache",
        "clear_client_probe_cache", "is_mica_supported",
    ):
        assert callable(getattr(fluent_pages, name))


@pytest.mark.ui
@pytest.mark.parametrize("scroll", [False, True])
def test_gallery_reparents_hidden_content_without_replacing_owner(qt_application, scroll):
    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import SmoothScrollArea

    from gui.pages.workspace_containers import GalleryPage

    old_parent = QWidget()
    content = QWidget(old_parent)
    content.hide()
    supplied_scroll = SmoothScrollArea() if scroll else None
    page = GalleryPage(
        "galleryCompatibility", "Gallery", "Content ownership", content,
        scroll=scroll, scroll_area=supplied_scroll,
    )
    page.resize(640, 480)
    page.show()
    qt_application.processEvents()

    # 原实现仅滚动分支主动显示旧宿主隐藏的内容；目录归位保留该行为。
    assert content.isVisibleTo(page) is scroll
    if scroll:
        assert page.body is supplied_scroll
        assert page.body.parentWidget() is page
        assert content.parentWidget() is page.body.widget()
    else:
        assert content.parentWidget() is page.body
    assert content.parentWidget() is not old_parent


@pytest.mark.ui
def test_new_page_paths_keep_application_translation_context(qt_application):
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
    from PySide6.QtWidgets import QWidget

    from gui.i18n import install_translators, tr
    from gui.pages.home import HomePage
    from gui.pages.workspace_containers import WorkspaceAreaPage
    from gui.pages.workspace_features import WorkspaceRoute

    class Host(QObject):
        route_changed = Signal(object)
        section_key = "apps"
        current_feature = "overview"
        current_device_id = ""

        def deactivate(self, reason):
            pass

        def is_overview_feature(self, feature):
            return True

        def feature_label(self, feature):
            return "Manager"

        def feature_requires_device(self, feature):
            return False

    frame = SimpleNamespace(
        _on_nav_requested=lambda _route: None,
        _request_device_refresh=lambda: None,
        _open_workspace_feature=lambda _section, _feature: None,
        _open_cmd=lambda: None,
        _on_save_path_clicked=lambda: None,
    )
    translators = install_translators(qt_application, "en_US")
    home = area = None
    host = Host()
    try:
        home = HomePage(frame)
        assert home.accessibleName() == "Home"
        assert home.tool_cards["app_mgr"].title_label.text() == tr("应用管理")
        assert tr("应用管理") != "应用管理"
        content = QWidget()
        area = WorkspaceAreaPage(
            "appsCompatibility", "apps", "Apps", "Overview", content, feature_host=host,
        )
        assert area.body is content
        assert content.parentWidget() is area
        area._set_route_presentation(WorkspaceRoute("apps", "manager"))
        assert area.accessibleDescription() == "Manager · " + tr("使用顶部设备栏中勾选的操作目标")
        assert tr("使用顶部设备栏中勾选的操作目标") != "使用顶部设备栏中勾选的操作目标"
    finally:
        for page in (home, area):
            if page is not None:
                page.close()
                page.deleteLater()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_application.processEvents()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_application.processEvents()
