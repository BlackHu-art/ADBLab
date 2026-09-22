"""验证 Windows 工具准备的离线、完整性和失败恢复契约。"""

import hashlib
import io
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from scripts import prepare_runtime_tools as prepare
from utils import tool_manifest


def test_windows_bundle_selects_verified_official_zip():
    bundle = tool_manifest.get_tool_bundle("win32", "AMD64")
    assert bundle.directory == "runtime-tools/windows-x86_64"
    assert bundle.archive_format == "zip"
    assert bundle.archive_root == "scrcpy-win64-v4.1"
    assert bundle.sha256 == "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"
    assert bundle.url == (
        "https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-win64-v4.1.zip"
    )


def _windows_archive(tmp_path, *, omitted=(), unsafe=False):
    contents = {
        name: name.encode() for name in (
            "adb.exe", "scrcpy.exe", "scrcpy-server", "AdbWinApi.dll", "AdbWinUsbApi.dll",
            "SDL3.dll", "avcodec-62.dll", "avformat-62.dll", "avutil-60.dll",
            "swresample-6.dll", "libusb-1.0.dll", "LICENSE.txt", "scrcpy.png",
            "disconnected.png", "open_a_terminal_here.bat", "scrcpy-noconsole.vbs",
        ) if name not in omitted
    }
    archive = tmp_path / "offline-package.bin"
    with ZipFile(archive, "w") as package:
        for name, content in contents.items():
            package.writestr("scrcpy-win64-v4.1/" + name, content)
        if unsafe:
            package.writestr("../../outside", b"unsafe")
    bundle = replace(
        tool_manifest.WINDOWS_BUNDLE, directory="runtime-tools/windows-x86_64",
        url="https://example.invalid/pinned.zip", archive_format="zip",
        archive_root="scrcpy-win64-v4.1",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    return bundle, archive, contents


def _forbid_network(*args, **kwargs):
    raise AssertionError("unexpected network")


def _snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_windows_zip_offline_preparation_keeps_complete_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)
    bundle, archive, contents = _windows_archive(tmp_path)
    root = tmp_path / "project with spaces"
    target = prepare.prepare_bundle(bundle, root=root, archive=archive)

    assert target == root / "runtime-tools/windows-x86_64"
    for name, content in contents.items():
        assert (target / name).read_bytes() == content
    receipt = json.loads((target / ".bundle.json").read_text())
    assert set(receipt["files"]) == set(contents)
    assert prepare.prepare_bundle(bundle, root=root, check_only=True) == target
    assert prepare.prepare_bundle(bundle, root=root, archive=root / "absent") == target


def test_download_uses_bundle_url_and_reuses_verified_files(tmp_path, monkeypatch):
    bundle, archive, contents = _windows_archive(tmp_path)
    requests = []

    def download(url, **kwargs):
        requests.append(url)
        return io.BytesIO(archive.read_bytes())

    monkeypatch.setattr(prepare.urllib.request, "urlopen", download)
    target = prepare.prepare_bundle(bundle, root=tmp_path / "project")
    assert (target / "adb.exe").read_bytes() == contents["adb.exe"]
    before = _snapshot(target)
    assert prepare.prepare_bundle(bundle, root=tmp_path / "project") == target
    assert _snapshot(target) == before
    assert requests == ["https://example.invalid/pinned.zip"]


@pytest.mark.parametrize("fault", ["sha", "root", "missing_dll", "unsafe"])
def test_invalid_zip_is_rejected_before_changing_destination(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)
    bundle, archive, _ = _windows_archive(
        tmp_path, omitted=("SDL3.dll",) if fault == "missing_dll" else (),
        unsafe=fault == "unsafe",
    )
    if fault == "sha":
        bundle = replace(bundle, sha256="0" * 64)
    elif fault == "root":
        bundle = replace(bundle, archive_root="wrong-root")
    root = tmp_path / "project"
    target = root / bundle.directory
    target.mkdir(parents=True)
    (target / "adb.exe").write_bytes(b"existing")
    (target / ".bundle.json").write_bytes(b"old receipt")
    before = _snapshot(target)

    with pytest.raises(ValueError):
        prepare.prepare_bundle(bundle, root=root, archive=archive)
    assert _snapshot(target) == before
    assert not (root / "outside").exists()


@pytest.mark.parametrize("fault", ["missing_dll", "server", "receipt", "absent"])
def test_check_only_never_repairs_or_downloads(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(prepare.urllib.request, "urlopen", _forbid_network)
    bundle, archive, _ = _windows_archive(tmp_path)
    root = tmp_path / "project"
    target = root / bundle.directory
    if fault != "absent":
        prepare.prepare_bundle(bundle, root=root, archive=archive)
        if fault == "missing_dll":
            (target / "SDL3.dll").unlink()
        elif fault == "server":
            (target / "scrcpy-server").write_bytes(b"wrong server")
        else:
            (target / ".bundle.json").write_bytes(b"not json")
    before, existed = _snapshot(root), root.exists()

    with pytest.raises(ValueError):
        prepare.prepare_bundle(bundle, root=root, check_only=True)
    assert _snapshot(root) == before
    assert root.exists() == existed


def test_bad_zip_reports_cli_failure_without_creating_target(tmp_path, monkeypatch, capsys):
    bundle, archive, _ = _windows_archive(tmp_path)
    archive.write_bytes(b"not a ZIP archive")
    bundle = replace(bundle, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    root = tmp_path / "project"
    monkeypatch.setattr(prepare, "ROOT", root)
    monkeypatch.setattr(tool_manifest, "get_tool_bundle", lambda: bundle)

    assert prepare.main(["--archive", str(archive)]) == 1
    assert "工具准备失败" in capsys.readouterr().err
    assert not (root / bundle.directory).exists()


def test_copy_failure_does_not_publish_receipt_and_allows_retry(tmp_path, monkeypatch, capsys):
    bundle, archive, _ = _windows_archive(tmp_path)
    root = tmp_path / "project"
    target = prepare.prepare_bundle(bundle, root=root, archive=archive)
    receipt = (target / ".bundle.json").read_bytes()
    (target / "scrcpy-server").write_bytes(b"damaged")
    monkeypatch.setattr(prepare, "ROOT", root)
    monkeypatch.setattr(tool_manifest, "get_tool_bundle", lambda: bundle)
    original_copy = prepare.shutil.copytree

    def partial_copy(source, destination, **kwargs):
        (destination / "adb.exe").write_bytes((source / "adb.exe").read_bytes())
        raise PermissionError("file is in use")

    monkeypatch.setattr(prepare.shutil, "copytree", partial_copy)
    assert prepare.main(["--archive", str(archive)]) == 1
    assert "重试" in capsys.readouterr().err
    assert (target / ".bundle.json").read_bytes() == receipt
    with pytest.raises(ValueError):
        prepare.prepare_bundle(bundle, root=root, check_only=True)

    monkeypatch.setattr(prepare.shutil, "copytree", original_copy)
    assert prepare.main(["--archive", str(archive)]) == 0
    assert prepare.prepare_bundle(bundle, root=root, check_only=True) == target
