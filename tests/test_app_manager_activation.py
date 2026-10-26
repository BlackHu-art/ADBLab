"""应用管理在设备准入延后满足时必须补加载，不能留下空白列表。"""

import pytest

from gui.features.app_manager.page import AppManagerPage

pytestmark = pytest.mark.ui


def _page(device_selected: bool, device_connected: bool):
    page = AppManagerPage(device_ip="activation-demo")
    page._device_selected = device_selected
    page._device_connected = device_connected
    page.load_state = "idle"
    page._apps_data = []
    page._load_in_progress = False
    page._load_refresh_pending = False
    loads = []

    def load_apps():
        if not page._can_operate():
            page._load_waiting_for_target = True
            return False
        page._load_waiting_for_target = False
        loads.append(True)
        return True

    page._load_apps = load_apps
    return page, loads


def test_selection_retries_load_after_activation_was_rejected(qt_application):
    page, loads = _page(device_selected=False, device_connected=True)
    try:
        page.activate()
        assert page._activated_once is True
        assert page._load_waiting_for_target is True
        assert loads == []

        page.set_device_selected(True)

        assert loads == [True]
        assert page._load_waiting_for_target is False
    finally:
        page.close()


def test_reconnect_retries_load_after_activation_was_rejected(qt_application):
    page, loads = _page(device_selected=True, device_connected=False)
    try:
        page.activate()
        assert page._activated_once is True
        assert loads == []

        page.set_device_connected(True)

        assert loads == [True]
    finally:
        page.close()


def test_activation_consumes_refresh_queued_while_inactive(qt_application):
    page, loads = _page(device_selected=True, device_connected=True)
    page._activated_once = True
    page._load_refresh_pending = True
    try:
        page.activate()

        assert loads == [True]
        assert page._load_refresh_pending is False
    finally:
        page.close()


def test_reactivation_retries_load_after_target_became_available_while_inactive(
    qt_application,
):
    page, loads = _page(device_selected=False, device_connected=True)
    try:
        page.activate()
        page.deactivate()
        page.set_device_selected(True)
        assert loads == []

        page.activate()

        assert loads == [True]
        page.set_device_selected(True)
        page.set_device_selected(True)
        page.set_device_connected(True)
        assert loads == [True]
    finally:
        page.close()
