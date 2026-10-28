"""图标 helper 构建来源一致性与失败发布保护。"""

import hashlib
import os
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest

from scripts import build_app_icon_helper as helper


def _dex(source: bytes) -> bytes:
    data = bytearray(112)
    data[:8] = b"dex\n035\0"
    data.extend(b"Lcom/adblab/icons/Main;" + source)
    struct.pack_into("<I", data, 32, len(data))
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xFFFFFFFF)
    return bytes(data)


@pytest.fixture
def build_env(tmp_path, monkeypatch):
    source = tmp_path / "source" / "Main.java"
    source.parent.mkdir()
    source.write_bytes(b"original\r\n")
    monkeypatch.setattr(helper, "_SOURCE", source)
    sdk, java_home = tmp_path / "sdk", tmp_path / "jdk"
    suffix = ".exe" if os.name == "nt" else ""
    for tool in (
        java_home / "bin" / f"javac{suffix}",
        java_home / "bin" / f"java{suffix}",
        sdk / "platforms/android-33/android.jar",
        sdk / "build-tools/33.0.2/lib/d8.jar",
    ):
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
    output = tmp_path / "output" / "helper.jar"
    output.parent.mkdir()
    output.write_bytes(b"previous artifact")
    return source, sdk, java_home, output


def _compiler(monkeypatch, source, *, change=False, aba=False, failure=None):
    compiled = b""

    def run(command, *, check, timeout):
        nonlocal compiled
        assert check and timeout == 60
        if "--release" in command and "-d" in command:
            if aba:
                source.write_bytes(b"intermediate\n")
            compiled = Path(command[-1]).read_bytes().replace(b"\r\n", b"\n")
            if change:
                source.write_bytes(b"changed\n")
            if aba:
                source.write_bytes(b"original\r\n")
            if failure == "compile":
                raise subprocess.CalledProcessError(1, command)
            (Path(command[command.index("-d") + 1]) / "Main.class").touch()
        else:
            dex = b"invalid" if failure == "validation" else _dex(compiled)
            (Path(command[command.index("--output") + 1]) / "classes.dex").write_bytes(dex)

    monkeypatch.setattr(helper.subprocess, "run", run)


def test_source_changed_after_compiler_read_rejects_publish(build_env, monkeypatch):
    source, sdk, java_home, output = build_env
    _compiler(monkeypatch, source, change=True)
    with pytest.raises(ValueError):
        helper.build_helper(sdk, java_home, output)
    assert output.read_bytes() == b"previous artifact"
    assert list(output.parent.glob(".adblab-icons-*")) == []


def test_stable_source_publishes_verified_reproducible_archive(build_env, monkeypatch):
    source, sdk, java_home, output = build_env
    _compiler(monkeypatch, source)
    helper.build_helper(sdk, java_home, output)
    helper.verify_helper(output)
    first = output.read_bytes()
    helper.build_helper(sdk, java_home, output)
    assert output.read_bytes() == first
    with zipfile.ZipFile(output) as archive:
        assert archive.read("classes.dex") == _dex(b"original\n")
        assert archive.read(helper._SOURCE_ENTRY) == (
            hashlib.sha256(b"original\n").hexdigest() + "\n"
        ).encode()


def test_source_aba_cannot_change_compiler_snapshot(build_env, monkeypatch):
    source, sdk, java_home, output = build_env
    _compiler(monkeypatch, source, aba=True)
    helper.build_helper(sdk, java_home, output)
    helper.verify_helper(output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("classes.dex") == _dex(b"original\n")


@pytest.mark.parametrize("failure", ["compile", "validation"])
def test_failed_build_keeps_previous_artifact(build_env, monkeypatch, failure):
    source, sdk, java_home, output = build_env
    _compiler(monkeypatch, source, failure=failure)
    error = subprocess.CalledProcessError if failure == "compile" else ValueError
    with pytest.raises(error):
        helper.build_helper(sdk, java_home, output)
    assert output.read_bytes() == b"previous artifact"
    assert list(output.parent.glob(".adblab-icons-*")) == []
