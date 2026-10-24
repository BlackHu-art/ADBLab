"""Windows 原生句柄缓存发布与删除，不用路径检查替代对象身份。"""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生缓存句柄契约")


def file_identity(path):
    metadata = path.stat()
    return metadata.st_dev, metadata.st_ino


def test_native_handle_blocks_write_replace_and_parent_rename_until_published(tmp_path):
    from utils.installer_cache_file import LockedCacheFile

    directory = tmp_path / "中文 空格 😀"
    directory.mkdir()
    part = directory / "installer.part"
    part.write_bytes(b"verified")
    replacement = tmp_path / "other.bin"
    replacement.write_bytes(b"unknown")
    ready = directory / "安装 😀 setup.exe"
    with LockedCacheFile(part, file_identity(part)) as locked:
        with pytest.raises(OSError):
            part.write_bytes(b"corrupted")
        with pytest.raises(OSError):
            replacement.replace(part)
        with pytest.raises(OSError):
            directory.rename(tmp_path / "renamed")
        assert locked.stream.read() == b"verified"
        locked.rename(ready)
        with pytest.raises(OSError):
            ready.write_bytes(b"still locked")
    assert ready.read_bytes() == b"verified"
    assert not part.exists()
    assert replacement.read_bytes() == b"unknown"


def test_native_rename_keeps_unknown_destination_without_overwrite(tmp_path):
    from utils.installer_cache_file import LockedCacheFile

    part, ready = tmp_path / "installer.part", tmp_path / "ready.exe"
    part.write_bytes(b"verified")
    with LockedCacheFile(part, file_identity(part)) as locked:
        ready.write_bytes(b"unknown destination")
        with pytest.raises(OSError):
            locked.rename(ready)
    assert part.read_bytes() == b"verified"
    assert ready.read_bytes() == b"unknown destination"


def test_native_delete_targets_owned_object_and_release_closes_delete_pending_file(tmp_path):
    from utils.installer_cache_file import LockedCacheFile

    part = tmp_path / "installer.part"
    part.write_bytes(b"owned")
    with LockedCacheFile(part, file_identity(part)) as locked:
        locked.delete()
        with pytest.raises(OSError):
            part.write_bytes(b"replacement")
    assert not part.exists()
    part.write_bytes(b"new file after close")
    assert part.read_bytes() == b"new file after close"


def test_native_open_refuses_replaced_identity_and_hardlink(tmp_path):
    from utils.installer_cache_file import LockedCacheFile

    part = tmp_path / "installer.part"
    part.write_bytes(b"owned")
    identity = file_identity(part)
    part.rename(tmp_path / "original.bin")
    part.write_bytes(b"unknown")
    with pytest.raises(ValueError):
        with LockedCacheFile(part, identity):
            pytest.fail("a replacement must never become owned")
    assert part.read_bytes() == b"unknown"
    os.link(part, tmp_path / "alias.bin")
    with pytest.raises(ValueError):
        with LockedCacheFile(part, file_identity(part)):
            pytest.fail("hardlinked cache must not be published or deleted")
