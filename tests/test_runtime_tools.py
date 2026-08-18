import os
import sys
from pathlib import Path

from utils.app_metadata import APP_VERSION


def test_bundled_tool_path_copies_frozen_runtime_outside_meipass(tmp_path, monkeypatch):
    source = tmp_path / "_MEI123" / "scrcpy-win64-v3.3.1"
    source.mkdir(parents=True)
    (source / "adb.exe").write_text("adb", encoding="utf-8")
    (source / "AdbWinApi.dll").write_text("dll", encoding="utf-8")
    local_appdata = tmp_path / "LocalAppData"

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123"), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    from utils.runtime_tools import bundled_tool_path

    path = Path(bundled_tool_path("scrcpy-win64-v3.3.1", "adb.exe"))

    expected = (
        local_appdata / "ADBLab" / "runtime" / APP_VERSION / "scrcpy-win64-v3.3.1" / "adb.exe"
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
        runtime_tools.bundled_tool_path("scrcpy-win64-v3.3.1", "scrcpy.exe")
    ) == os.path.normpath("C:/repo/scrcpy-win64-v3.3.1/scrcpy.exe")


def test_bundled_tool_path_uses_onedir_bundle_without_copy(tmp_path, monkeypatch):
    dist = tmp_path / "dist" / "ADBLab"
    source = dist / "_internal" / "scrcpy-win64-v3.3.1"
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

    path = Path(runtime_tools.bundled_tool_path("scrcpy-win64-v3.3.1", "adb.exe"))

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

    assert adb_resolver.resolve_adb_path() == "C:/runtime/scrcpy-win64-v3.3.1/adb.exe"
