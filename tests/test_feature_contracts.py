"""验证可选会话能力的准入与异步关闭屏障。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from gui.features.base import FeatureSessionKey, FeatureSessionRegistry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("name", [
    "activate", "deactivate", "request_dispose", "register_shutdown_tasks",
    "set_device_selected", "set_device_connected",
])
def test_invalid_optional_callback_is_rejected_before_registration(qt_application, name):
    registry = FeatureSessionRegistry()
    page = QWidget()
    setattr(page, name, False)
    key = FeatureSessionKey("test")
    try:
        with pytest.raises(TypeError, match=name):
            registry.get_or_create(key, lambda _: page)
        assert registry.get(key) is None
    finally:
        page.deleteLater()


def test_invalid_disposal_signal_does_not_leave_registered_session(qt_application):
    registry = FeatureSessionRegistry()
    page = QWidget()
    page.dispose_ready = object()
    key = FeatureSessionKey("test")
    try:
        with pytest.raises(TypeError, match="dispose_ready"):
            registry.get_or_create(key, lambda _: page)
        assert registry.get(key) is None
    finally:
        page.deleteLater()


def test_async_disposal_without_signal_retains_closing_barrier(qt_application):
    class Page(QWidget):
        def request_dispose(self, reason):
            return False

    registry = FeatureSessionRegistry()
    key = FeatureSessionKey("test")
    page, _ = registry.get_or_create(key, lambda _: Page())
    try:
        with pytest.raises(RuntimeError, match="dispose_ready"):
            registry.request_dispose(key)
        assert registry.get(key) is page
        assert registry.is_disposing(key)
        with pytest.raises(RuntimeError, match="disposing"):
            registry.get_or_create(key, lambda _: QWidget())
        with pytest.raises(RuntimeError, match="disposing"):
            registry.activate(key)
    finally:
        registry.remove(key)
        page.deleteLater()


def test_plain_widget_and_synchronous_disposal_remain_supported(qt_application):
    class SyncPage(QWidget):
        def request_dispose(self, reason):
            return True

    registry = FeatureSessionRegistry()
    for factory in (QWidget, SyncPage):
        key = FeatureSessionKey(factory.__name__)
        registry.get_or_create(key, lambda _, factory=factory: factory())
        assert registry.request_dispose(key)
        assert registry.get(key) is None


def test_async_disposal_signal_removes_only_its_session(qt_application):
    class AsyncPage(QWidget):
        dispose_ready = Signal()

        def request_dispose(self, reason):
            return False

    registry = FeatureSessionRegistry()
    key = FeatureSessionKey("async")
    other_key = FeatureSessionKey("other")
    page, _ = registry.get_or_create(key, lambda _: AsyncPage())
    other, _ = registry.get_or_create(other_key, lambda _: QWidget())
    assert not registry.request_dispose(key)
    page.dispose_ready.emit()
    assert registry.get(key) is None
    assert registry.get(other_key) is other
    assert registry.request_dispose(other_key)


def test_callback_replacement_is_checked_when_invoked(qt_application):
    registry = FeatureSessionRegistry()
    key = FeatureSessionKey("test")
    page, _ = registry.get_or_create(key, lambda _: QWidget())
    page.activate = False
    try:
        with pytest.raises(TypeError, match="activate"):
            registry.activate(key)
    finally:
        registry.request_dispose(key)


@pytest.mark.parametrize("member", ["connect", "disconnect"])
def test_dispose_signal_requires_both_callable_operations(qt_application, member):
    registry = FeatureSessionRegistry()
    page = QWidget()
    signal = SimpleNamespace(connect=lambda _callback: None, disconnect=lambda _callback: None)
    setattr(signal, member, False)
    page.dispose_ready = signal
    key = FeatureSessionKey("test")
    try:
        with pytest.raises(TypeError, match="dispose_ready"):
            registry.get_or_create(key, lambda _: page)
        assert registry.get(key) is None
    finally:
        page.deleteLater()


def test_dispose_signal_connection_failure_is_not_published(qt_application):
    def failed_connect(_callback):
        raise RuntimeError("connection failed")

    registry = FeatureSessionRegistry()
    published = []
    registry.session_added.connect(lambda key, _page: published.append(key))
    page = QWidget()
    page.dispose_ready = SimpleNamespace(connect=failed_connect, disconnect=lambda _callback: None)
    key = FeatureSessionKey("test")
    try:
        with pytest.raises(RuntimeError, match="connection failed"):
            registry.get_or_create(key, lambda _: page)
        assert registry.get(key) is None
        assert not published
        assert key not in registry._dispose_callbacks
    finally:
        page.deleteLater()
