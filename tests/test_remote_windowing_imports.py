from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

_PACKAGE = "services.remote.windowing"
_STAGE_MODULES = {
    _PACKAGE,
    f"{_PACKAGE}.contracts",
    f"{_PACKAGE}.win32",
    f"{_PACKAGE}.x11",
    f"{_PACKAGE}.events",
    "services.remote.window_tracking",
    "services.remote.x11_window_tracking",
    "services.remote.window_events",
}


def _run_fresh(script):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("new_first", [False, True])
@pytest.mark.parametrize(
    ("legacy", "leaf", "names"),
    [
        (
            "window_tracking", "contracts",
            (
                "PhysicalRect", "NativeWindowSnapshot", "_WindowApi",
                "_WindowSubscription", "_EventWindowApi",
            ),
        ),
        ("window_tracking", "win32", ("_Win32WindowApi",)),
        ("x11_window_tracking", "x11", ("X11WindowApi",)),
        ("window_events", "events", ("WinEventSubscription", "_RETAINED_SUBSCRIPTIONS")),
    ],
)
def test_legacy_exports_share_identity_in_either_import_order(legacy, leaf, names, new_first):
    _run_fresh(f"""
        import importlib
        old_name = "services.remote.{legacy}"
        new_name = "{_PACKAGE}.{leaf}"
        order = (new_name, old_name) if {new_first!r} else (old_name, new_name)
        for name in order:
            importlib.import_module(name)
        old = importlib.import_module(old_name)
        new = importlib.import_module(new_name)
        for name in {names!r}:
            assert getattr(old, name) is getattr(new, name), name
        tracking = importlib.import_module("services.remote.window_tracking")
        assert tracking.WindowsWindowTracker.__module__ == "services.remote.window_tracking"
        assert tracking.create_window_tracker.__module__ == "services.remote.window_tracking"
    """)


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        (_PACKAGE, {_PACKAGE}),
        (f"{_PACKAGE}.contracts", {_PACKAGE, f"{_PACKAGE}.contracts"}),
        (f"{_PACKAGE}.win32", {_PACKAGE, f"{_PACKAGE}.contracts", f"{_PACKAGE}.win32"}),
        (f"{_PACKAGE}.x11", {_PACKAGE, f"{_PACKAGE}.contracts", f"{_PACKAGE}.x11"}),
        (f"{_PACKAGE}.events", {_PACKAGE, f"{_PACKAGE}.events"}),
    ],
)
def test_windowing_leaf_imports_keep_unrelated_backends_unloaded(module, expected):
    _run_fresh(f"""
        import importlib
        import sys
        importlib.import_module({module!r})
        loaded = set(sys.modules) & {_STAGE_MODULES!r}
        assert loaded == {expected!r}, loaded
    """)


@pytest.mark.parametrize("module", sorted(_STAGE_MODULES))
def test_windowing_imports_do_not_open_native_resources(module):
    _run_fresh(f"""
        import ctypes
        import ctypes.util
        import importlib

        def forbidden(*args, **kwargs):
            raise AssertionError("导入窗口模块不得打开原生资源")

        ctypes.WinDLL = forbidden
        ctypes.WINFUNCTYPE = forbidden
        ctypes.CDLL = forbidden
        ctypes.util.find_library = forbidden
        importlib.import_module({module!r})
    """)


def test_contract_defaults_and_optional_event_protocol_are_preserved():
    contracts = importlib.import_module(f"{_PACKAGE}.contracts")
    from services.remote import window_tracking
    from tests.test_remote_window_tracking import EventWindowApi, FakeWindowApi

    snapshot = contracts.NativeWindowSnapshot(
        21, 200, (0, 0, 700, 900), (0, 0, 1920, 1040), True, False, True, False,
    )
    assert snapshot.dpi == 96
    assert snapshot.foreground_hwnd == 0
    with pytest.raises(FrozenInstanceError):
        snapshot.dpi = 144
    assert contracts._EventWindowApi is window_tracking._EventWindowApi
    assert not isinstance(FakeWindowApi(), contracts._EventWindowApi)
    assert isinstance(EventWindowApi(), contracts._EventWindowApi)
