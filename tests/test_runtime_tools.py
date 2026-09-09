import os
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from utils.app_metadata import APP_VERSION


def test_bundled_tool_path_copies_frozen_runtime_outside_meipass(tmp_path, monkeypatch):
    source = tmp_path / "_MEI123" / "scrcpy-win64"
    source.mkdir(parents=True)
    (source / "adb.exe").write_text("adb", encoding="utf-8")
    (source / "AdbWinApi.dll").write_text("dll", encoding="utf-8")
    local_appdata = tmp_path / "LocalAppData"

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123"), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    from utils.runtime_tools import bundled_tool_path

    path = Path(bundled_tool_path("scrcpy-win64", "adb.exe"))

    expected = (
        local_appdata / "ADBLab" / "runtime" / APP_VERSION / "scrcpy-win64" / "adb.exe"
    )
    assert path == expected
    assert expected.read_text(encoding="utf-8") == "adb"
    assert str(tmp_path / "_MEI123") not in str(path)


def test_bundled_tool_path_uses_project_resource_in_development(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    from utils import runtime_tools

    monkeypatch.setattr(
        runtime_tools,
        "resource_path",
        lambda relative: f"C:/repo/{relative}",
    )

    assert os.path.normpath(
        runtime_tools.bundled_tool_path("scrcpy-win64", "scrcpy.exe")
    ) == os.path.normpath("C:/repo/scrcpy-win64/scrcpy.exe")


def test_bundled_tool_path_uses_onedir_bundle_without_copy(tmp_path, monkeypatch):
    dist = tmp_path / "dist" / "ADBLab"
    source = dist / "_internal" / "scrcpy-win64"
    source.mkdir(parents=True)
    (source / "adb.exe").write_text("adb", encoding="utf-8")
    local_appdata = tmp_path / "LocalAppData"

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(dist / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(dist / "ADBLab.exe"))

    from utils import runtime_tools

    monkeypatch.setattr(
        runtime_tools,
        "resource_path",
        lambda relative: str(dist / "_internal" / relative),
    )

    path = Path(runtime_tools.bundled_tool_path("scrcpy-win64", "adb.exe"))

    assert path == source / "adb.exe"
    assert not (local_appdata / "ADBLab").exists()


def test_resolve_adb_path_prefers_runtime_tool_path(monkeypatch):
    from utils import adb_resolver

    monkeypatch.setattr(adb_resolver, "_adb_path", None)
    monkeypatch.setattr(adb_resolver, "_resolved", False)
    monkeypatch.setattr(
        adb_resolver,
        "bundled_tool_path",
        lambda bundle, name: f"C:/runtime/{bundle}/{name}",
    )
    monkeypatch.setattr(adb_resolver.os.path, "isfile", lambda path: True)

    assert adb_resolver.resolve_adb_path() == "C:/runtime/scrcpy-win64/adb.exe"


def test_resolve_adb_path_uses_path_on_non_windows(monkeypatch):
    from utils import adb_resolver

    monkeypatch.setattr(adb_resolver, "_adb_path", None)
    monkeypatch.setattr(adb_resolver, "_resolved", False)
    monkeypatch.setattr(adb_resolver.sys, "platform", "linux")
    monkeypatch.setattr(
        adb_resolver.shutil, "which", lambda name: "/usr/bin/adb" if name == "adb" else None
    )
    # 非 Windows 下不得回退到仓库内 Windows adb.exe。
    monkeypatch.setattr(
        adb_resolver, "bundled_tool_path", lambda bundle, name: f"/repo/{bundle}/{name}"
    )

    assert adb_resolver.resolve_adb_path() == "/usr/bin/adb"


@pytest.mark.parametrize(
    "relative", ["helper.exe", "_internal/python.dll", "_internal/lib/codec.dll"],
)
def test_verified_runtime_copy_refreshes_same_length_stale_nested_file(tmp_path, relative):
    from utils.runtime_tools import _ensure_runtime_copy

    source, target = tmp_path / "source", tmp_path / "target"
    original = source / "helper" / relative
    original.parent.mkdir(parents=True)
    original.write_bytes(b"NEW")
    shutil.copytree(source, target)
    stale = target / "helper" / relative
    stale.write_bytes(b"OLD")

    _ensure_runtime_copy(source, target, verify_tree=True)

    assert stale.read_bytes() == b"NEW"


def test_verified_runtime_copy_accepts_complete_tree_without_rewriting(tmp_path, monkeypatch):
    from utils import runtime_tools

    source, target = tmp_path / "source", tmp_path / "target"
    source_dependency = source / "helper" / "_internal" / "nested" / "module.dll"
    source_dependency.parent.mkdir(parents=True)
    source_dependency.write_bytes(b"complete")
    shutil.copytree(source, target)
    cached_dependency = target / "helper" / "_internal" / "nested" / "module.dll"
    before = cached_dependency.stat().st_mtime_ns
    copy = Mock(side_effect=AssertionError("valid cache must not be rewritten"))
    monkeypatch.setattr(runtime_tools.shutil, "copytree", copy)

    runtime_tools._ensure_runtime_copy(source, target, verify_tree=True)

    assert cached_dependency.read_bytes() == b"complete"
    assert cached_dependency.stat().st_mtime_ns == before
    copy.assert_not_called()


def test_runtime_copy_default_retains_existing_directory_and_size_contract(tmp_path):
    from utils.runtime_tools import _ensure_runtime_copy

    source, target = tmp_path / "source", tmp_path / "target"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "dependency.dll").write_bytes(b"new dependency")
    (source / "tool.exe").write_bytes(b"NEW")
    (target / "nested").mkdir(parents=True)
    (target / "tool.exe").write_bytes(b"OLD")

    _ensure_runtime_copy(source, target)

    assert (target / "tool.exe").read_bytes() == b"OLD"
    assert not (target / "nested" / "dependency.dll").exists()


def test_frozen_scrcpy_bridge_repairs_empty_nested_cache(tmp_path, monkeypatch):
    from utils import runtime_tools, scrcpy_bridge

    source, target = tmp_path / "resources", tmp_path / "cache"
    package = source / "runtime-helpers" / scrcpy_bridge.BRIDGE_NAME
    (package / "_internal").mkdir(parents=True)
    filename = scrcpy_bridge.BRIDGE_NAME + ".exe"
    (package / filename).write_bytes(b"helper")
    (package / "_internal" / "python.dll").write_bytes(b"runtime")
    cached_package = target / "runtime-helpers" / scrcpy_bridge.BRIDGE_NAME
    cached_package.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(runtime_tools, "resource_path", lambda relative: str(source / relative))
    monkeypatch.setattr(runtime_tools, "_runtime_root", lambda: target)
    monkeypatch.setattr(runtime_tools, "_is_onefile_extraction", lambda: True)

    executable = scrcpy_bridge.resolve_scrcpy_bridge()

    assert executable == str(cached_package / filename)
    assert (cached_package / filename).read_bytes() == b"helper"
    assert (cached_package / "_internal" / "python.dll").read_bytes() == b"runtime"
