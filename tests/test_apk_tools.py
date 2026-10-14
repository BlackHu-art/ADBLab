"""APK 工具选择不依赖宿主 SDK，冻结运行保留独立缓存与平台边界。"""

import sys
from pathlib import Path

import pytest


def test_bundled_apk_analysis_works_without_path_tools(tmp_path, monkeypatch):
    from utils import apk_tools
    from utils.tool_manifest import get_aapt2_bundle

    bundle = get_aapt2_bundle("win32", "AMD64")
    assert bundle is not None
    executable = tmp_path / "aapt2.exe"
    executable.write_bytes(b"tool")
    executable.chmod(0o755)
    (tmp_path / "NOTICE").write_text("license", encoding="utf-8")
    monkeypatch.setattr(apk_tools, "get_aapt2_bundle", lambda: bundle)
    monkeypatch.setattr(apk_tools, "resource_path", lambda path: str(tmp_path))
    monkeypatch.setattr(apk_tools, "bundled_tool_path", lambda *args, **kwargs: str(executable))
    monkeypatch.setattr(apk_tools.shutil, "which", lambda name: None)
    assert apk_tools.resolve_apk_tool() == str(executable)


@pytest.mark.parametrize("available", [{"aapt": "/tools/aapt"}, {"aapt2": "/tools/aapt2"}, {}])
def test_existing_environment_tools_remain_available(monkeypatch, available):
    from utils import apk_tools

    monkeypatch.setattr(apk_tools, "get_aapt2_bundle", lambda: None)
    monkeypatch.setattr(apk_tools.shutil, "which", available.get)
    assert apk_tools.resolve_apk_tool() == next(iter(available.values()), None)


def test_incomplete_bundle_does_not_shadow_existing_aapt(tmp_path, monkeypatch):
    from utils import apk_tools
    from utils.tool_manifest import get_aapt2_bundle

    executable = tmp_path / "aapt2.exe"
    executable.write_bytes(b"tool")
    executable.chmod(0o755)
    monkeypatch.setattr(apk_tools, "get_aapt2_bundle", lambda: get_aapt2_bundle("win32", "AMD64"))
    monkeypatch.setattr(apk_tools, "resource_path", lambda path: str(tmp_path))
    monkeypatch.setattr(apk_tools, "bundled_tool_path", lambda *args, **kwargs: str(executable))
    monkeypatch.setattr(
        apk_tools.shutil, "which", lambda name: "/existing/aapt" if name == "aapt" else None,
    )
    assert apk_tools.resolve_apk_tool() == "/existing/aapt"


@pytest.mark.parametrize("mode", ["source", "onedir", "onefile"])
def test_apk_tool_uses_resource_root_and_preserves_notice(tmp_path, monkeypatch, mode):
    from utils import apk_tools
    from utils.app_metadata import APP_VERSION
    from utils.tool_manifest import get_aapt2_bundle

    bundle = get_aapt2_bundle("win32", "AMD64")
    assert bundle is not None
    root = tmp_path / ("_MEI123" if mode == "onefile" else "dist/_internal")
    target = root / bundle.directory
    target.mkdir(parents=True)
    (target / bundle.executable).write_bytes(b"tool")
    (target / bundle.executable).chmod(0o755)
    (target / "NOTICE").write_text("license", encoding="utf-8")
    monkeypatch.setattr(apk_tools, "get_aapt2_bundle", lambda: bundle)
    monkeypatch.setattr("utils.runtime_tools.resource_path", lambda relative: str(root / relative))
    monkeypatch.setattr(apk_tools, "resource_path", lambda relative: str(root / relative))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", mode != "source", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist/ADBLab.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    monkeypatch.setattr(apk_tools.shutil, "which", lambda name: None)
    selected = Path(apk_tools.resolve_apk_tool())
    expected = (tmp_path / "cache/ADBLab/runtime" / APP_VERSION / bundle.directory
                if mode == "onefile" else target)
    assert selected == expected / bundle.executable
    assert selected.read_bytes() == b"tool"
    assert (selected.parent / "NOTICE").read_text(encoding="utf-8") == "license"


@pytest.mark.parametrize("platform,machine", [
    ("win32", "ARM64"), ("linux", "aarch64"), ("darwin", "arm64"),
])
def test_bundle_does_not_select_another_platform_or_architecture(platform, machine):
    from utils.tool_manifest import get_aapt2_bundle

    assert get_aapt2_bundle(platform, machine) is None


@pytest.mark.parametrize("missing", ["aapt2.exe", "NOTICE"])
def test_onefile_incomplete_source_cannot_reuse_old_complete_cache(tmp_path, monkeypatch, missing):
    from utils import apk_tools
    from utils.app_metadata import APP_VERSION
    from utils.tool_manifest import get_aapt2_bundle

    bundle = get_aapt2_bundle("win32", "AMD64")
    assert bundle is not None
    resource_root = tmp_path / "_MEI123"
    source = resource_root / bundle.directory
    cache = tmp_path / "cache/ADBLab/runtime" / APP_VERSION / bundle.directory
    source.mkdir(parents=True)
    cache.mkdir(parents=True)
    for name in bundle.required_files:
        (cache / name).write_bytes(b"old complete bundle")
        (cache / name).chmod(0o755)
        if name != missing:
            (source / name).write_bytes(b"current partial bundle")
            (source / name).chmod(0o755)
    monkeypatch.setattr(apk_tools, "get_aapt2_bundle", lambda: bundle)
    monkeypatch.setattr("utils.runtime_tools.resource_path", lambda path: str(resource_root / path))
    monkeypatch.setattr(apk_tools, "resource_path", lambda path: str(resource_root / path))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resource_root), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist/ADBLab.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    monkeypatch.setattr(
        apk_tools.shutil, "which", lambda name: "/tools/aapt" if name == "aapt" else None,
    )
    assert apk_tools.resolve_apk_tool() == "/tools/aapt"
