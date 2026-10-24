"""只验证安装 EXE 的静态结构，不把合成 PE 当作可运行安装器。"""

from __future__ import annotations

import stat
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_build_artifacts as checks


def minimal_pe(*, pe64: bool = False) -> bytes:
    """构造具有完整头、一个代码节和 overlay 的受控结构夹具。"""
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    optional_size = 240 if pe64 else 224
    struct.pack_into("<HHIIIHH", data, 0x84,
                     0x8664 if pe64 else 0x14C, 1, 0, 0, 0, optional_size, 0x102)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B if pe64 else 0x10B)
    struct.pack_into("<I", data, optional + 16, 0x1000)
    struct.pack_into("<II", data, optional + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, optional + 56, 0x2000, 0x200)
    struct.pack_into("<H", data, optional + 68, 2)
    struct.pack_into("<I", data, optional + (108 if pe64 else 92), 16)
    section = optional + optional_size
    data[section:section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x100, 0x1000, 0x200, 0x200)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    data[512] = 0xC3
    return bytes(data) + b"unvalidated installer overlay"


@pytest.mark.parametrize("pe64", [False, True])
def test_installer_accepts_bounded_pe_headers_and_sections(tmp_path, pe64):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(minimal_pe(pe64=pe64))
    checks.check_installer_file(installer)


@pytest.mark.parametrize("offset,format_,value", [
    (0, "2s", b"NO"),
    (0x3C, "I", 8),
    (0x3C, "I", 0xFFFFFFF0),
    (0x80, "4s", b"PE??"),
    (0x84, "H", 0),
    (0x86, "H", 0),
    (0x86, "H", 97),
    (0x94, "H", 1),
    (0x94, "H", 0xFFFF),
    (0x96, "H", 0),
    (0x96, "H", 0x2002),
    (0x98, "H", 0x107),
    (0x98 + 16, "I", 0x3000),
    (0x98 + 32, "I", 0),
    (0x98 + 36, "I", 0),
    (0x98 + 56, "I", 0x1000),
    (0x98 + 60, "I", 0x100),
    (0x98 + 60, "I", 0x10000),
    (0x98 + 92, "I", 17),
    (0x178 + 8, "I", 0x10000),
    (0x178 + 12, "I", 0x200),
    (0x178 + 16, "I", 0x10000),
    (0x178 + 20, "I", 0),
    (0x178 + 20, "I", 0x400),
    (0x178 + 36, "I", 0x40000040),
])
def test_installer_rejects_invalid_pe_structure(tmp_path, offset, format_, value):
    installer = tmp_path / "setup.exe"
    data = bytearray(minimal_pe())
    struct.pack_into("<" + format_, data, offset, value)
    installer.write_bytes(data)
    with pytest.raises(checks.CheckError):
        checks.check_installer_file(installer)


@pytest.mark.parametrize("size", [0, 2, 63, 0x84, 0x98, 0x190, 1023])
def test_installer_rejects_truncated_pe(tmp_path, size):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(minimal_pe()[:size])
    with pytest.raises(checks.CheckError):
        checks.check_installer_file(installer)


def test_installer_rejects_overlapping_raw_sections(tmp_path):
    data = bytearray(minimal_pe())
    struct.pack_into("<H", data, 0x86, 2)
    data[0x1A0:0x1C8] = data[0x178:0x1A0]
    struct.pack_into("<I", data, 0x1A0 + 12, 0x2000)
    struct.pack_into("<I", data, 0x98 + 56, 0x3000)
    installer = tmp_path / "setup.exe"
    installer.write_bytes(data)
    with pytest.raises(checks.CheckError):
        checks.check_installer_file(installer)


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "reparse"])
def test_installer_requires_regular_non_reparse_file(tmp_path, monkeypatch, kind):
    installer = tmp_path / "setup.exe"
    if kind == "directory":
        installer.mkdir()
    elif kind in {"symlink", "reparse"}:
        installer.write_bytes(minimal_pe())
        real_lstat = Path.lstat

        def marked_lstat(path):
            if path == installer:
                return SimpleNamespace(st_mode=stat.S_IFLNK if kind == "symlink" else stat.S_IFREG,
                                       st_file_attributes=0x400 if kind == "reparse" else 0)
            return real_lstat(path)

        monkeypatch.setattr(Path, "lstat", marked_lstat)
    with pytest.raises(checks.CheckError):
        checks.check_installer_file(installer)
