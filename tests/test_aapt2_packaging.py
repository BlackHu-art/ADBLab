"""验证 AAPT2 的准备、收集和自检，不下载或执行外部工具。"""

import hashlib
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from scripts import prepare_runtime_tools as prepare
from utils import tool_manifest


def _forbid_network(*args, **kwargs):
    raise AssertionError("unexpected network")


def test_cli_check_includes_aapt2_when_other_bundle_is_absent(tmp_path, monkeypatch):
    bundle = tool_manifest.get_aapt2_bundle("win32", "x86_64")
    monkeypatch.setattr(tool_manifest, "get_tool_bundle", lambda: None)
    monkeypatch.setattr(tool_manifest, "get_aapt2_bundle", lambda: bundle, raising=False)
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)

    assert prepare.main(["--check"]) == 1
    assert list(tmp_path.iterdir()) == []


def _archive(tmp_path, platform="win32", *, missing_notice=False):
    bundle = tool_manifest.get_aapt2_bundle(platform, "x86_64")
    archive = tmp_path / f"aapt2-{platform}.jar"
    contents = {bundle.executable: b"synthetic executable", "NOTICE": b"license notice"}
    with ZipFile(archive, "w") as package:
        for name, content in contents.items():
            if name != "NOTICE" or not missing_notice:
                package.writestr(name, content)
    prepared_bundle = replace(bundle, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    return prepared_bundle, archive, contents


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_offline_maven_archive_keeps_executable_and_notice(tmp_path, monkeypatch, platform):
    bundle, archive, contents = _archive(tmp_path, platform)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)
    target = prepare.prepare_bundle(bundle, root=tmp_path / "project", archive=archive)

    for name, content in contents.items():
        assert (target / name).read_bytes() == content
    assert set(json.loads((target / ".bundle.json").read_text())["files"]) == set(contents)
    if platform == "linux" and os.name != "nt":
        assert (target / bundle.executable).stat().st_mode & 0o111
    assert prepare.prepare_bundle(bundle, root=tmp_path / "project", check_only=True) == target


def test_missing_notice_is_rejected_before_publish(tmp_path, monkeypatch):
    bundle, archive, _ = _archive(tmp_path, missing_notice=True)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)
    root = tmp_path / "project"

    with pytest.raises(ValueError, match="NOTICE"):
        prepare.prepare_bundle(bundle, root=root, archive=archive)
    assert not (root / bundle.directory).exists()


def test_posix_aapt2_requires_executable_permission(tmp_path, monkeypatch):
    bundle = tool_manifest.get_aapt2_bundle("linux", "x86_64")
    for name in bundle.required_files:
        (tmp_path / name).write_bytes(b"synthetic tool")
    monkeypatch.setattr(prepare, "os", SimpleNamespace(
        name="posix", X_OK=os.X_OK, access=lambda path, mode: False,
    ))

    with pytest.raises(ValueError, match="aapt2"):
        prepare._check_files(bundle, tmp_path)


def test_cli_routes_each_offline_archive_to_its_own_bundle(tmp_path, monkeypatch):
    from tests.test_prepare_runtime_tools import _windows_archive

    scrcpy, scrcpy_archive, _ = _windows_archive(tmp_path)
    aapt2, aapt2_archive, _ = _archive(tmp_path)
    root = tmp_path / "project"
    monkeypatch.setattr(prepare, "ROOT", root)
    monkeypatch.setattr(tool_manifest, "get_tool_bundle", lambda: scrcpy)
    monkeypatch.setattr(tool_manifest, "get_aapt2_bundle", lambda: aapt2)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)

    assert prepare.main([
        "--archive", str(scrcpy_archive), "--aapt2-archive", str(aapt2_archive),
    ]) == 0
    assert (root / scrcpy.directory / "scrcpy.exe").is_file()
    assert (root / aapt2.directory / "NOTICE").is_file()
    assert prepare.main(["--check"]) == 0
    (root / aapt2.directory / "NOTICE").write_bytes(b"changed")
    assert prepare.main(["--check"]) == 1


@pytest.mark.parametrize("fault", ["", "missing", "notice", "version", "execution", "timeout"])
def test_self_check_validates_bundled_aapt2_without_path_fallback(tmp_path, monkeypatch, fault):
    from core.adb_transport import ExecutionResult
    from utils import tool_check

    bundle = tool_manifest.get_aapt2_bundle("win32", "x86_64")
    directory = tmp_path / bundle.directory
    directory.mkdir(parents=True)
    if fault != "missing":
        (directory / bundle.executable).write_bytes(b"synthetic executable")
    if fault != "notice":
        (directory / "NOTICE").write_bytes(b"license notice")
    monkeypatch.setattr(tool_check, "get_tool_bundle", lambda: None)
    monkeypatch.setattr(tool_check, "get_aapt2_bundle", lambda: bundle, raising=False)
    monkeypatch.setattr(tool_check, "resource_path", lambda name: str(tmp_path / name))
    monkeypatch.setattr(
        tool_check, "bundled_tool_path",
        lambda relative, name, **kw: str(tmp_path / relative / name),
    )

    def version(command, timeout, cancelled):
        assert command == [str(directory / bundle.executable), "version"]
        assert timeout == 10 and not cancelled()
        return ExecutionResult(
            returncode=1 if fault == "execution" else 0,
            kind="timeout" if fault == "timeout" else "completed",
            stderr=("Android Asset Packaging Tool (aapt) " + (
                "0.0-wrong" if fault == "version" else bundle.runtime_version
            ) + "\n").encode(),
        )

    monkeypatch.setattr(tool_check, "native_capture", version)
    checks = {name: ok for name, ok, _ in tool_check.check_bundled_tools()}
    assert checks[f"resource:{bundle.executable}"] is (fault != "missing")
    assert checks["resource:aapt2-NOTICE"] is (fault != "notice")
    if fault != "missing":
        assert checks[f"runtime:{bundle.executable}"] is (
            fault not in {"version", "execution", "timeout"}
        )
    assert all(checks.values()) is (not fault)
