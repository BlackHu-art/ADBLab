"""验证平台工具的来源、离线准备及缓存可执行性。"""

import hashlib
import io
import os
import sys
import tarfile
from dataclasses import replace

import pytest


def test_linux_bundled_adb_precedes_path(tmp_path, monkeypatch):
    from utils import adb_resolver

    executable = tmp_path / "adb"
    executable.write_bytes(b"linux adb")
    executable.chmod(0o755)
    monkeypatch.setattr(adb_resolver.sys, "platform", "linux")
    monkeypatch.setattr(adb_resolver, "bundled_tool_path", lambda *args: str(executable))
    monkeypatch.setattr(adb_resolver, "resource_path", lambda name: str(executable))
    monkeypatch.setattr(adb_resolver.shutil, "which", lambda name: "/system/adb")
    adb_resolver.set_client_preference("auto")
    try:
        assert adb_resolver.resolve_adb_path() == str(executable)
    finally:
        adb_resolver.set_client_preference("auto")


@pytest.mark.parametrize(
    "saved,actual", [("bundled", "runtime_cache"), ("runtime_cache", "bundled")],
)
def test_builtin_preference_survives_packaging_mode(saved, actual):
    from utils.adb_resolver import _preferred_candidates

    assert _preferred_candidates([(actual, "/tools/adb"), ("PATH", "/system/adb")], saved) == [
        (actual, "/tools/adb"),
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX 执行权限")
def test_cache_repairs_lost_execute_permission(tmp_path):
    from utils.runtime_tools import _ensure_runtime_copy

    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    (source / "scrcpy").write_bytes(b"binary")
    (source / "scrcpy").chmod(0o755)
    _ensure_runtime_copy(source, target)
    (target / "scrcpy").chmod(0o600)
    _ensure_runtime_copy(source, target)
    assert os.access(target / "scrcpy", os.X_OK)


def _archive(tmp_path, *, unsafe=False):
    path = tmp_path / "tools.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name in ("adb", "scrcpy", "scrcpy-server", "LICENSE"):
            info = tarfile.TarInfo("package/" + name)
            data = name.encode()
            info.size, info.mode = len(data), 0o755 if name in {"adb", "scrcpy"} else 0o644
            archive.addfile(info, io.BytesIO(data))
        if unsafe:
            info = tarfile.TarInfo("package/link")
            info.type, info.linkname = tarfile.SYMTYPE, "../../outside"
            archive.addfile(info)
    return path


@pytest.mark.parametrize("unsafe", [False, True])
def test_prepare_verified_archive_offline(tmp_path, unsafe):
    from scripts.prepare_runtime_tools import prepare_bundle
    from utils.tool_manifest import get_tool_bundle

    archive = _archive(tmp_path, unsafe=unsafe)
    bundle = replace(
        get_tool_bundle("linux", "x86_64"), archive_root="package",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    root = tmp_path / "project with spaces"
    if unsafe:
        with pytest.raises(ValueError, match="archive|归档"):
            prepare_bundle(bundle, root=root, archive=archive)
        assert not (root / bundle.directory).exists()
    else:
        prepared = prepare_bundle(bundle, root=root, archive=archive)
        assert (prepared / "adb").read_bytes() == b"adb"
        assert prepare_bundle(bundle, root=root, check_only=True) == prepared
        (prepared / "scrcpy-server").write_bytes(b"corrupted")
        with pytest.raises(ValueError):
            prepare_bundle(bundle, root=root, check_only=True)


def test_archive_digest_failure_preserves_existing_tools(tmp_path):
    from scripts.prepare_runtime_tools import prepare_bundle
    from utils.tool_manifest import get_tool_bundle

    bundle = get_tool_bundle("linux", "x86_64")
    target = tmp_path / bundle.directory
    target.mkdir(parents=True)
    (target / "adb").write_bytes(b"existing")
    with pytest.raises(ValueError, match="SHA256"):
        prepare_bundle(bundle, root=tmp_path, archive=_archive(tmp_path))
    assert (target / "adb").read_bytes() == b"existing"


def test_unsupported_architecture_does_not_select_x64_tools():
    from utils.tool_manifest import get_tool_bundle

    assert get_tool_bundle("linux", "aarch64") is None
    assert get_tool_bundle("darwin", "arm64") is None


def test_linux_scrcpy_prefers_bundle(tmp_path, monkeypatch):
    from services.remote import scrcpy_service

    executable = tmp_path / "scrcpy"
    executable.write_bytes(b"binary")
    executable.chmod(0o755)
    monkeypatch.setattr(scrcpy_service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scrcpy_service, "bundled_tool_path", lambda *args: str(executable))
    monkeypatch.setattr(scrcpy_service.shutil, "which", lambda name: "/system/scrcpy")
    assert scrcpy_service.ScrcpyService().resolve_executable() == str(executable)


def test_scrcpy_version_failure_can_be_retried():
    from unittest.mock import Mock

    from core.exec import CommandResult
    from services.remote.scrcpy_service import ScrcpyService

    runner = Mock()
    runner.run.side_effect = [CommandResult(False, error="Permission denied"),
                              CommandResult(True, output="scrcpy 4.1")]
    service = ScrcpyService(command_runner=runner)
    with pytest.raises(RuntimeError, match="scrcpy"):
        service.version("/tools/scrcpy")
    assert service.version("/tools/scrcpy") == "4.1"


def test_linux_packaging_includes_only_linux_tools():
    from scripts.packaging_manifest import resource_datas

    resources = resource_datas("linux")
    assert ("runtime-tools/linux-x86_64", "runtime-tools/linux-x86_64") in resources
    assert not any("windows-x86_64" in source for source, _ in resources)


def test_mirror_worker_preserves_tool_error_message():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from gui.panels.remote_panel import ScrcpyLaunchWorker
    from services.remote.types import ScrcpyToolError

    failures, messages = [], []
    worker = ScrcpyLaunchWorker(SimpleNamespace(), service=Mock(
        build_launch_plan=Mock(side_effect=ScrcpyToolError()),
    ))
    worker.plan_failed.connect(lambda config, code: failures.append(code))
    worker.log_message.connect(lambda level, message: messages.append(message))
    worker.run()
    assert failures == ["scrcpy_unavailable"]
    assert any("执行权限" in message for message in messages)


def test_settings_builtin_selection_tracks_cache_source():
    from types import SimpleNamespace

    from gui.widgets.adb_client_card import AdbClientSettingCard

    card = SimpleNamespace(_candidate_sources={"runtime_cache", "PATH"})
    assert AdbClientSettingCard._key_for(card, "bundled") == "runtime_cache"


@pytest.mark.parametrize(
    "platform,names", [("linux", ("adb", "scrcpy")), ("win32", ("adb.exe", "scrcpy.exe"))],
)
def test_packaging_check_does_not_hide_missing_bundle_with_system_tools(
    tmp_path, monkeypatch, platform, names,
):
    from utils import tool_check
    from utils.tool_manifest import get_tool_bundle

    monkeypatch.setattr(tool_check, "get_tool_bundle", lambda: get_tool_bundle(platform, "x86_64"))
    monkeypatch.setattr(tool_check, "resource_path", lambda name: str(tmp_path / name))
    checks = tool_check.check_bundled_tools()
    for executable in names:
        assert any(name == f"resource:{executable}" and not ok for name, ok, _ in checks)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux 正在执行的 ELF 不可覆盖")
@pytest.mark.parametrize("fault", ["permissions", "missing"])
def test_runtime_repair_does_not_overwrite_live_adb(tmp_path, fault):
    import shutil
    import subprocess

    from utils.runtime_tools import _ensure_runtime_copy

    source, target = tmp_path / "source", tmp_path / "cache"
    source.mkdir()
    shutil.copy2("/bin/sleep", source / "adb")
    (source / "scrcpy").write_bytes(b"scrcpy")
    (source / "scrcpy").chmod(0o755)
    _ensure_runtime_copy(source, target)
    process = subprocess.Popen([str(target / "adb"), "30"])
    try:
        if fault == "permissions":
            (target / "scrcpy").chmod(0o600)
        else:
            (target / "scrcpy").unlink()
        _ensure_runtime_copy(source, target)
        assert os.access(target / "scrcpy", os.X_OK)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=2)


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX 可执行脚本模拟打包工具")
def test_self_check_rejects_corrupt_source_despite_valid_cache(tmp_path, monkeypatch):
    from utils import runtime_tools, tool_check
    from utils.tool_manifest import LINUX_BUNDLE

    source = tmp_path / "source"
    bundle_root = source / LINUX_BUNDLE.directory
    bundle_root.mkdir(parents=True)
    for name in LINUX_BUNDLE.required_files:
        (bundle_root / name).write_text("data")
    for name, text in (("adb", "Android Debug Bridge version 1.0.41"), ("scrcpy", "scrcpy 4.1")):
        (bundle_root / name).write_text(f"#!/bin/sh\nprintf '{text}\\n'\n")
        (bundle_root / name).chmod(0o755)
    checked_bundle = replace(LINUX_BUNDLE, server_sha256=hashlib.sha256(b"data").hexdigest())
    monkeypatch.setattr(tool_check, "get_tool_bundle", lambda: checked_bundle)
    for module in (runtime_tools, tool_check):
        monkeypatch.setattr(module, "resource_path", lambda name: str(source / name))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_tools, "_is_onefile_extraction", lambda: True)
    monkeypatch.setattr(runtime_tools, "_runtime_root", lambda: tmp_path / "cache")
    assert all(ok for _, ok, _ in tool_check.check_bundled_tools())
    executable = bundle_root / "scrcpy"
    executable.write_bytes(b"X" * executable.stat().st_size)
    assert any(not ok for _, ok, _ in tool_check.check_bundled_tools())


def test_self_check_rejects_mismatched_server(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from core.exec import CommandResult
    from utils import tool_check
    from utils.tool_manifest import LINUX_BUNDLE

    for name in LINUX_BUNDLE.required_files:
        (tmp_path / name).write_bytes(b"mismatched file")
        (tmp_path / name).chmod(0o755)
    monkeypatch.setattr(tool_check, "get_tool_bundle", lambda: LINUX_BUNDLE)
    monkeypatch.setattr(
        tool_check, "resource_path", lambda name: str(tmp_path / name.rsplit('/', 1)[-1]),
    )
    monkeypatch.setattr(
        tool_check, "bundled_tool_path", lambda bundle, name, **kw: str(tmp_path / name),
    )
    monkeypatch.setattr(tool_check.CommandRunner, "run", Mock(return_value=CommandResult(
        True, output="Android Debug Bridge version 1.0.41\nscrcpy 4.1",
    )))
    checks = tool_check.check_bundled_tools()
    assert any(not ok for _, ok, _ in checks)
