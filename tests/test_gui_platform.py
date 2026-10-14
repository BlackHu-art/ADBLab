"""GUI 与 scrcpy 的显示后端只改变本次启动环境。"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest


def _module():
    return importlib.import_module("utils.gui_platform")


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
@pytest.mark.parametrize("display", ["", ":77"])
@pytest.mark.parametrize("xcb_available", [False, True])
def test_default_gui_backend_requires_linux_display_and_loadable_xcb(
    monkeypatch, platform, display, xcb_available,
):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module, "_xcb_plugin_loadable", lambda: xcb_available)
    environment = {"DISPLAY": display, "WAYLAND_DISPLAY": "wayland-synthetic"}
    expected = dict(environment)
    automatic = bool(platform == "linux" and display and xcb_available)
    if automatic:
        expected["QT_QPA_PLATFORM"] = "xcb;wayland"

    selected_automatically = module.configure_gui_platform(["main.py"], environment)

    assert environment == expected
    assert selected_automatically is automatic


@pytest.mark.parametrize("requested", ["wayland", "offscreen", "xcb", "", "wayland;xcb"])
def test_explicit_qpa_prevents_default_selection(monkeypatch, requested):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    environment = {"DISPLAY": ":77", "QT_QPA_PLATFORM": requested}
    before = dict(environment)

    assert module.configure_gui_platform(["main.py"], environment) is False

    assert environment == before


@pytest.mark.parametrize(
    "arguments, requested",
    [
        (["-platform", "wayland"], "wayland"),
        (["--platform", "xcb"], "xcb"),
        (["-platform", "xcb:synthetic"], "xcb:synthetic"),
        (["-platform", "offscreen", "-platform", "xcb"], "xcb"),
    ],
)
def test_cli_platform_takes_priority_and_propagates_to_children(monkeypatch, arguments, requested):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    environment = {"DISPLAY": ":77", "QT_QPA_PLATFORM": "wayland"}

    assert module.configure_gui_platform(["main.py", *arguments], environment) is False
    child = module.scrcpy_environment(environment)

    assert environment["QT_QPA_PLATFORM"] == requested
    assert child["QT_QPA_PLATFORM"] == requested
    assert child.get("SDL_VIDEO_DRIVER") == ("x11" if requested.startswith("xcb") else None)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_non_linux_explicit_cli_never_changes_environment(monkeypatch, platform):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", platform)
    environment = {"DISPLAY": ":77", "QT_QPA_PLATFORM": "offscreen"}
    before = dict(environment)

    module.configure_gui_platform(["main.py", "-platform", "xcb"], environment)

    assert environment == before
    assert module.scrcpy_environment(environment) == before


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (["-platform", "offscreen"], "offscreen"),
        (["--platform", "offscreen"], "offscreen"),
        (["-platform=offscreen"], "minimal"),
        (["--platform=offscreen"], "minimal"),
    ],
)
def test_inherited_platform_matches_real_qt_cli_semantics(arguments, expected):
    script = """
import os, sys
from PySide6.QtWidgets import QApplication
sys.platform = 'linux'
from utils.gui_platform import configure_gui_platform
configure_gui_platform(sys.argv)
application = QApplication(sys.argv)
assert application.platformName() == os.environ['QT_QPA_PLATFORM']
print(application.platformName())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, *arguments],
        env={**os.environ, "QT_QPA_PLATFORM": "minimal"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "sdl, allowed",
    [
        ({}, True),
        ({"SDL_VIDEO_DRIVER": "x11"}, True),
        ({"SDL_VIDEODRIVER": "x11"}, True),
        ({"SDL_VIDEO_DRIVER": "x11", "SDL_VIDEODRIVER": "x11"}, True),
        ({"SDL_VIDEO_DRIVER": "wayland"}, False),
        ({"SDL_VIDEODRIVER": "wayland"}, False),
        ({"SDL_VIDEO_DRIVER": "x11", "SDL_VIDEODRIVER": "wayland"}, False),
        ({"SDL_VIDEO_DRIVER": "wayland", "SDL_VIDEODRIVER": "x11"}, False),
        ({"SDL_VIDEO_DRIVER": "wayland,x11"}, False),
        ({"SDL_VIDEO_DRIVER": ""}, False),
    ],
)
def test_sdl_explicit_choices_control_defaults_without_overwrites(monkeypatch, sdl, allowed):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "_xcb_plugin_loadable", lambda: True)
    environment = {"DISPLAY": ":77", **sdl}
    before = dict(environment)
    assert module.sdl_allows_x11(environment) is allowed

    module.configure_gui_platform(["main.py"], environment)

    assert environment == ({**before, "QT_QPA_PLATFORM": "xcb;wayland"} if allowed else before)
    environment["QT_QPA_PLATFORM"] = "xcb"
    before_child = dict(environment)
    child = module.scrcpy_environment(environment)
    assert environment == before_child
    expected = dict(before_child)
    if allowed:
        expected.update(SDL_VIDEO_DRIVER="x11", SDL_VIDEODRIVER="x11")
    assert child == expected


@pytest.mark.parametrize("qpa", [None, "wayland", "offscreen", "xcb;wayland", ""])
def test_scrcpy_defaults_require_unambiguous_xcb_environment(monkeypatch, qpa):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    environment = {"DISPLAY": ":77"}
    if qpa is not None:
        environment["QT_QPA_PLATFORM"] = qpa

    assert module.scrcpy_environment(environment) == environment


@pytest.mark.parametrize("loadable", [False, True])
def test_xcb_capability_checks_plugin_dependencies_without_constructing_qt(
    tmp_path, monkeypatch, loadable,
):
    module = _module()
    package = tmp_path / "PySide6"
    plugin = package / "Qt" / "plugins" / "platforms" / "libqxcb.so"
    plugin.parent.mkdir(parents=True)
    plugin.touch()
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda _name: SimpleNamespace(
        origin=str(package / "__init__.py"),
    ))

    def load(path):
        assert str(path) == str(plugin)
        if not loadable:
            raise OSError("synthetic missing xcb dependency")
        return object()

    monkeypatch.setattr(module.ctypes, "CDLL", load)

    assert module._xcb_plugin_loadable() is loadable


def test_platform_helpers_do_not_import_qt_when_preparing_child_environment():
    script = """
import builtins, sys
sys.platform = 'linux'
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'PySide6' or name.startswith('PySide6.'):
        raise AssertionError('child environment imported Qt')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from utils.gui_platform import scrcpy_environment
result = scrcpy_environment({'QT_QPA_PLATFORM': 'xcb', 'DISPLAY': ':77'})
assert result['SDL_VIDEO_DRIVER'] == 'x11'
assert result['SDL_VIDEODRIVER'] == 'x11'
"""
    environment = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
