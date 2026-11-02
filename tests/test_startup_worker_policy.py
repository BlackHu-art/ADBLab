"""启动显示进程的 macOS 身份配置必须早于 Qt，且不影响其它显示后端。"""

import os
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("platform,qpa", [
    ("win32", None), ("linux", None), ("darwin", "offscreen"), ("darwin", "minimal"),
    ("darwin", "offscreen;minimal"),
])
def test_other_platforms_do_not_load_appkit_or_change_process_policy(monkeypatch, platform, qpa):
    from gui import startup_worker

    monkeypatch.setattr(startup_worker, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setitem(sys.modules, "AppKit", None)
    monkeypatch.setenv("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "unchanged")
    if qpa is None:
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    else:
        monkeypatch.setenv("QT_QPA_PLATFORM", qpa)
    startup_worker._configure_macos_splash_application()
    assert os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] == "unchanged"


@pytest.mark.parametrize("qpa", [
    None, "", "cocoa", "cocoa:darkmode=1", "missing;cocoa", "offscreen;cocoa",
])
def test_accessory_policy_and_qt_transform_guard_precede_qapplication(monkeypatch, qpa):
    from gui import startup_worker

    calls = []

    def set_policy(policy):
        assert policy == 1
        assert os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] == "1"
        calls.append("accessory")
        return True

    def create_application(_arguments):
        assert calls == ["accessory"]
        return SimpleNamespace(setQuitOnLastWindowClosed=lambda _value: None, exec=lambda: 0)

    monkeypatch.setattr(startup_worker, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: SimpleNamespace(
            setActivationPolicy_=set_policy,
        )), NSApplicationActivationPolicyAccessory=1,
    ))
    monkeypatch.setattr(startup_worker, "QApplication", create_application)
    monkeypatch.setattr(
        startup_worker, "_SplashSession", lambda *_: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setenv("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "")
    if qpa is None:
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    else:
        monkeypatch.setenv("QT_QPA_PLATFORM", qpa)
    assert startup_worker.run_startup_splash("synthetic") == 0
    assert os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] == "1"


def test_policy_refusal_stops_before_creating_qt_application(monkeypatch):
    from gui import startup_worker

    monkeypatch.setattr(startup_worker, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: SimpleNamespace(
            setActivationPolicy_=lambda _policy: False,
        )), NSApplicationActivationPolicyAccessory=1,
    ))
    monkeypatch.setenv("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "")
    monkeypatch.setenv("QT_QPA_PLATFORM", "cocoa")
    monkeypatch.setattr(
        startup_worker, "QApplication", lambda *_: pytest.fail("策略失败后不能创建 Qt"),
    )
    with pytest.raises(OSError, match="启动显示进程"):
        startup_worker.run_startup_splash("synthetic")
