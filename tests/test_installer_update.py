"""安装包缓存的摘要、原子发布及精确清理契约。"""

import hashlib
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_app_update import installer_payload, release_payload


def assert_cancelled_part_state(root):
    """Windows 按句柄删除；不支持原生协议的平台必须保留无法原子证明归属的 part。"""
    parts = list(root.rglob("*.part"))
    assert bool(parts) is (sys.platform != "win32")


def make_asset(body=b"abc"):
    from services.app_update import parse_installer_asset, parse_release

    payload = release_payload(id=5, assets=[installer_payload(
        size=len(body), digest="sha256:" + hashlib.sha256(body).hexdigest(),
    )])
    return parse_installer_asset(payload, parse_release(payload))


def test_chunks_are_published_only_after_full_verification_and_revalidated_for_reuse(tmp_path):
    from services.installer_update import DownloadWriter, find_cached, verify_download

    asset = make_asset()
    writer = DownloadWriter(asset, cache_root=tmp_path)
    writer.write(b"a")
    assert list(tmp_path.rglob(asset.name)) == []
    writer.write(b"bc")
    if sys.platform != "win32":
        with pytest.raises(OSError, match="Windows"):
            writer.finish()
        writer.cancel()
        assert_cancelled_part_state(tmp_path)
        assert list(tmp_path.rglob(asset.name)) == []
        return
    verified = writer.finish()
    assert verified.path.read_bytes() == b"abc"
    assert verified.asset == asset
    assert verified.path.name == asset.name
    assert verified.path.parent.parent == tmp_path
    assert_cancelled_part_state(tmp_path)
    assert verify_download(verified.path, asset) == verified
    assert find_cached(asset, cache_root=tmp_path) == verified
    verified.path.write_bytes(b"abd")
    assert find_cached(asset, cache_root=tmp_path) is None
    with pytest.raises(ValueError):
        verify_download(verified.path, asset)


@pytest.mark.parametrize("body", [b"", b"ab", b"abd"])
def test_truncated_or_corrupt_download_cannot_publish_ready_file(tmp_path, body):
    from services.installer_update import DownloadWriter

    asset = make_asset()
    writer = DownloadWriter(asset, cache_root=tmp_path)
    writer.write(body)
    with pytest.raises(ValueError):
        writer.finish()
    writer.cancel()
    assert list(tmp_path.rglob(asset.name)) == []
    assert_cancelled_part_state(tmp_path)


def test_oversize_and_terminal_writes_are_rejected_without_touching_existing_cache(tmp_path):
    from services.installer_update import DownloadWriter

    asset = make_asset()
    old = tmp_path / "user-export.exe"
    old.write_bytes(b"keep")
    writer = DownloadWriter(asset, cache_root=tmp_path)
    with pytest.raises(ValueError):
        writer.write(b"abcd")
    writer.cancel()
    writer.cancel()
    with pytest.raises(ValueError):
        writer.write(b"abc")
    with pytest.raises(ValueError):
        writer.finish()
    assert old.read_bytes() == b"keep"
    assert_cancelled_part_state(tmp_path)


def test_write_rejects_unbounded_chunks_and_constructor_validates_asset(tmp_path):
    from services.installer_update import DownloadWriter, validate_installer_asset

    asset = make_asset(b"a" * 70_000)
    writer = DownloadWriter(asset, cache_root=tmp_path)
    try:
        with pytest.raises(ValueError):
            writer.write(b"a" * 65_537)
    finally:
        writer.cancel()
    for invalid in (replace(asset, tag="v3.2.13"), replace(asset, size=True),
                    replace(asset, sha256="0"), replace(asset, download_url="https://evil.test/x")):
        with pytest.raises(ValueError):
            validate_installer_asset(invalid)
        with pytest.raises(ValueError):
            DownloadWriter(invalid, cache_root=tmp_path)


def test_default_cache_is_in_user_data_updates(tmp_path, monkeypatch):
    from services import installer_update

    monkeypatch.setattr(installer_update, "user_data_root", lambda: tmp_path)
    writer = installer_update.DownloadWriter(make_asset())
    writer.write(b"abc")
    if sys.platform != "win32":
        with pytest.raises(OSError, match="Windows"):
            writer.finish()
        writer.cancel()
        assert_cancelled_part_state(tmp_path / "updates")
        return
    result = writer.finish()
    assert result.path.parent.parent == tmp_path / "updates"
    writer.cancel()
    assert result.path.read_bytes() == b"abc"


@pytest.mark.parametrize("operation", ["construct", "verify", "cancel"])
def test_reparse_ancestor_is_rejected_and_cancel_never_deletes_through_it(
    tmp_path, monkeypatch, operation,
):
    from services.installer_update import DownloadWriter, verify_download

    asset = make_asset()
    writer = DownloadWriter(asset, cache_root=tmp_path)
    writer.write(b"abc")
    part = next(tmp_path.rglob("*.part"))
    original_lstat = Path.lstat

    def reparse_lstat(path):
        result = original_lstat(path)
        if path == tmp_path:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    if operation == "construct":
        with pytest.raises(ValueError):
            DownloadWriter(asset, cache_root=tmp_path)
    elif operation == "verify":
        with pytest.raises(ValueError):
            verify_download(part, asset)
    writer.cancel()
    assert part.exists()


def test_symlink_download_is_not_accepted(tmp_path):
    from services.installer_update import verify_download

    asset = make_asset()
    target = tmp_path / "target.exe"
    target.write_bytes(b"abc")
    link = tmp_path / "linked.exe"
    try:
        link.symlink_to(target)
    except OSError:
        # Windows 默认不授予 symlink 权限；用真实目录 junction 覆盖同一重解析边界。
        import subprocess

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "target.exe").write_bytes(b"abc")
        junction = tmp_path / "junction"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            check=True, capture_output=True,
        )
        with pytest.raises(ValueError):
            verify_download(junction / "target.exe", asset)
    else:
        with pytest.raises(ValueError):
            verify_download(link, asset)


@pytest.mark.parametrize("boundary", ["fsync", "rename"])
def test_disk_failure_cannot_publish_ready_file(tmp_path, monkeypatch, boundary):
    from services import installer_update

    writer = installer_update.DownloadWriter(make_asset(), cache_root=tmp_path)
    writer.write(b"abc")

    def fail(*_args, **_kwargs):
        raise OSError("disk failure")

    if boundary == "fsync":
        monkeypatch.setattr(installer_update.os, boundary, fail)
    elif sys.platform == "win32":
        from utils.installer_cache_file import LockedCacheFile

        monkeypatch.setattr(LockedCacheFile, "rename", fail)
    else:
        with pytest.raises(OSError, match="Windows"):
            writer.finish()
        writer.cancel()
        assert_cancelled_part_state(tmp_path)
        return
    with pytest.raises(OSError, match="disk failure"):
        writer.finish()
    writer.cancel()
    assert_cancelled_part_state(tmp_path)
    assert not list(tmp_path.rglob("*-setup.exe"))


def test_modified_part_is_rejected_and_cancellation_preserves_replacement(tmp_path):
    from services.installer_update import DownloadWriter

    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    writer.write(b"abc")
    part = next(tmp_path.rglob("*.part"))
    # 同句柄重写可模拟下载后、校验前的篡改。
    part.write_bytes(b"xyz")
    with pytest.raises(ValueError):
        writer.finish()
    writer.cancel()

    existing = set(tmp_path.rglob("*.part"))
    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    part = next(iter(set(tmp_path.rglob("*.part")) - existing))
    writer.cancel()
    part.write_bytes(b"replacement")
    writer.cancel()
    assert part.read_bytes() == b"replacement"


def test_hardlinked_file_is_rejected(tmp_path):
    from services.installer_update import verify_download

    original = tmp_path / "original.exe"
    original.write_bytes(b"abc")
    linked = tmp_path / "linked.exe"
    os.link(original, linked)
    with pytest.raises(ValueError):
        verify_download(linked, make_asset())


def test_verification_cancel_does_not_publish_or_reuse_partial_result(tmp_path):
    from services.installer_update import DownloadWriter, find_cached, verify_download

    chunk = b"a" * 65_536
    asset = make_asset(chunk * 3)
    writer = DownloadWriter(asset, cache_root=tmp_path)
    for _ in range(3):
        writer.write(chunk)
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) > 2

    with pytest.raises(InterruptedError):
        writer.finish(cancelled=cancelled)
    writer.cancel()
    assert list(tmp_path.rglob(asset.name)) == []
    assert_cancelled_part_state(tmp_path)

    writer = DownloadWriter(asset, cache_root=tmp_path)
    for _ in range(3):
        writer.write(chunk)
    if sys.platform != "win32":
        with pytest.raises(OSError, match="Windows"):
            writer.finish()
        writer.cancel()
        return
    verified = writer.finish()
    for verify in (
        lambda: verify_download(verified.path, asset, cancelled=lambda: True),
        lambda: find_cached(asset, tmp_path, cancelled=lambda: True),
    ):
        with pytest.raises(InterruptedError):
            verify()
    assert verified.path.read_bytes() == chunk * 3


def test_short_file_write_is_reported_as_io_failure(tmp_path, monkeypatch):
    from services.installer_update import DownloadWriter

    original_open = Path.open

    class ShortWriter:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, block):
            return self.stream.write(block[:-1])

    def short_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return ShortWriter(stream) if args and args[0] == "xb" else stream

    monkeypatch.setattr(Path, "open", short_open)
    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    with pytest.raises(OSError):
        writer.write(b"abc")
    writer.cancel()
    assert_cancelled_part_state(tmp_path)
    assert not list(tmp_path.rglob("*-setup.exe"))


def test_verification_detects_path_replacement_after_open(tmp_path, monkeypatch):
    from services import installer_update

    asset = make_asset()
    path = tmp_path / "installer.exe"
    path.write_bytes(b"abc")
    original_fstat = os.fstat
    calls = []

    def replace_after_hash(descriptor):
        result = original_fstat(descriptor)
        calls.append(True)
        if len(calls) == 2:
            # 模拟 stat 校验边界观察到不同文件身份；不要求 Windows 允许替换已打开句柄。
            fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
            fields["st_mtime_ns"] += 1
            return SimpleNamespace(**fields)
        return result

    monkeypatch.setattr(installer_update.os, "fstat", replace_after_hash)
    with pytest.raises(ValueError):
        installer_update.verify_download(path, asset)


def test_cancel_never_unlinks_a_replacement_inserted_at_path_deletion(tmp_path, monkeypatch):
    from services.installer_update import DownloadWriter

    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    writer.write(b"abc")
    part = next(tmp_path.rglob("*.part"))
    original_unlink = Path.unlink
    replacements = []

    def replace_then_unlink(path, *args, **kwargs):
        if path == part:
            path.rename(path.with_name("original.part"))
            path.write_bytes(b"unknown replacement")
            replacements.append(path)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", replace_then_unlink)
    writer.cancel()
    for replacement in replacements:
        assert replacement.exists()
        assert replacement.read_bytes() == b"unknown replacement"


@pytest.mark.parametrize("attack", ["source", "destination"])
def test_finish_never_publishes_unverified_replacement_or_overwrites_unknown_file(
    tmp_path, monkeypatch, attack,
):
    from services import installer_update

    asset = make_asset()
    writer = installer_update.DownloadWriter(asset, cache_root=tmp_path)
    writer.write(b"abc")
    original_replace = os.replace
    inserted = []

    def replace_after_validation(source, target):
        if attack == "source":
            Path(source).write_bytes(b"xyz")
        else:
            Path(target).write_bytes(b"unknown destination")
            inserted.append(Path(target))
        return original_replace(source, target)

    monkeypatch.setattr(installer_update.os, "replace", replace_after_validation)
    if sys.platform != "win32":
        with pytest.raises(OSError, match="Windows"):
            writer.finish()
        writer.cancel()
        return
    verified = writer.finish()
    assert verified.path.read_bytes() == b"abc"
    for target in inserted:
        assert target.read_bytes() == b"unknown destination"


@pytest.mark.parametrize("operation", ["finish", "cancel"])
def test_owned_part_replacement_is_preserved_before_native_operation(
    tmp_path, monkeypatch, operation,
):
    from services.installer_update import DownloadWriter

    original_open = Path.open

    class ReplaceOnClose:
        def __init__(self, path, stream):
            self.path, self.stream = path, stream
            self.closed = False

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.stream.close()
            if not self.closed:
                self.closed = True
                self.path.rename(self.path.with_name("owned-original.bin"))
                self.path.write_bytes(b"abc")

    def replaced_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return ReplaceOnClose(path, stream) if args and args[0] == "xb" else stream

    monkeypatch.setattr(Path, "open", replaced_open)
    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    writer.write(b"abc")
    part = next(tmp_path.rglob("*.part"))
    if operation == "finish":
        # 非 Windows 的完整内容仍不能取得发布权限；Windows 则必须识别替换身份。
        expected_error = ValueError if sys.platform == "win32" else OSError
        with pytest.raises(expected_error):
            writer.finish()
    writer.cancel()
    assert part.read_bytes() == b"abc"
    assert part.with_name("owned-original.bin").read_bytes() == b"abc"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生发布事务")
def test_destination_inserted_at_native_publication_is_preserved(tmp_path, monkeypatch):
    from services.installer_update import DownloadWriter
    from utils.installer_cache_file import LockedCacheFile

    writer = DownloadWriter(make_asset(), cache_root=tmp_path)
    writer.write(b"abc")
    original_rename = LockedCacheFile.rename
    destinations = []

    def insert_before_rename(locked, target):
        target.write_bytes(b"unknown destination")
        destinations.append(target)
        original_rename(locked, target)

    monkeypatch.setattr(LockedCacheFile, "rename", insert_before_rename)
    with pytest.raises(OSError):
        writer.finish()
    writer.cancel()
    assert destinations[0].read_bytes() == b"unknown destination"
    assert not list(tmp_path.rglob("*.part"))


def test_non_windows_can_verify_but_never_publish_or_delete_by_path(tmp_path, monkeypatch):
    import errno

    from services import installer_update

    monkeypatch.setattr(installer_update, "sys", SimpleNamespace(platform="linux"))
    asset = make_asset()
    writer = installer_update.DownloadWriter(asset, cache_root=tmp_path)
    writer.write(b"abc")
    part = next(tmp_path.rglob("*.part"))
    assert installer_update.verify_download(part, asset).path == part
    with pytest.raises(OSError) as failure:
        writer.finish()
    assert failure.value.errno == errno.ENOTSUP
    writer.cancel()
    assert part.read_bytes() == b"abc"
    assert not list(tmp_path.rglob(asset.name))
