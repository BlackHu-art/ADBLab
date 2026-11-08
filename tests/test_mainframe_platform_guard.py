"""公共 MainFrame 构造入口须在接触原生窗口前诊断平台前提。"""

from types import SimpleNamespace

import pytest

from tests import test_main_window_layout as layout_tests

pytestmark = pytest.mark.ui


class _ConstructorReached(Exception):
    pass


@pytest.fixture
def constructor_calls(monkeypatch):
    """即使入口检查缺失，也只进入哨兵，绝不构造真实原生窗口。"""
    calls = []

    class FakeMainFrame:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            raise _ConstructorReached

        def _bootstrap_adb_async(self):
            pass

    monkeypatch.setattr(layout_tests, "MainFrame", FakeMainFrame)
    return calls


@pytest.mark.parametrize("platform_name", ["offscreen", "minimal"])
def test_macos_wrong_qt_platform_fails_before_constructor(
    monkeypatch, constructor_calls, platform_name,
):
    monkeypatch.setattr(layout_tests, "sys", SimpleNamespace(platform="darwin"))
    application = SimpleNamespace(platformName=lambda: platform_name)
    monkeypatch.setattr(
        layout_tests, "QApplication", SimpleNamespace(instance=lambda: application), raising=False,
    )

    with pytest.raises(RuntimeError, match="QT_QPA_PLATFORM=cocoa"):
        layout_tests.build_main_frame()

    assert constructor_calls == []


def test_missing_qapplication_fails_before_constructor(monkeypatch, constructor_calls):
    monkeypatch.setattr(
        layout_tests, "QApplication", SimpleNamespace(instance=lambda: None), raising=False,
    )

    with pytest.raises(RuntimeError, match="qt_application"):
        layout_tests.build_main_frame()

    assert constructor_calls == []


@pytest.mark.parametrize(
    "platform,platform_name",
    [("darwin", "cocoa"), ("win32", "offscreen"), ("linux", "offscreen")],
)
def test_supported_platform_reaches_constructor(
    monkeypatch, constructor_calls, platform, platform_name,
):
    monkeypatch.setattr(layout_tests, "sys", SimpleNamespace(platform=platform))
    application = SimpleNamespace(platformName=lambda: platform_name)
    monkeypatch.setattr(
        layout_tests, "QApplication", SimpleNamespace(instance=lambda: application), raising=False,
    )

    with pytest.raises(_ConstructorReached):
        layout_tests.build_main_frame()

    assert len(constructor_calls) == 1
