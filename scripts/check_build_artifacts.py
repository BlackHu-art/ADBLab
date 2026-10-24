"""验证冻结入口和发布产物；发布检查仅依赖标准库且不解压产物。"""

from __future__ import annotations

import argparse
import gzip
import math
import os
import re
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import time
import zipfile
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEANUP_TIMEOUT = 2.0
ARTIFACTS = (
    "ADBLab-win-x64", "ADBLab-macos-x64", "ADBLab-macos-arm64", "ADBLab-linux-x64",
)


class CheckError(Exception):
    """表示已确认的产物契约失败或无法确认的进程清理。"""


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    """关闭已归还的读端，避免 Windows 活跃 reader 的流锁突破清理时限。"""
    for name in ("stdout", "stderr"):
        stream = getattr(process, name)
        reader = getattr(process, name + "_thread", None)
        if stream is not None and (reader is None or not reader.is_alive()):
            stream.close()


def _stop_and_reap(
    process: subprocess.Popen[bytes], kill_tree: Callable[..., tuple[bool, str]],
) -> str:
    """先终止自有进程树，再在共享预算内回收和排空；未确认清理必须报告失败。

    POSIX 独立会话用于定位根退出后仍持有管道的后代。Windows 已失去父子关系时
    不能把根不存在当作树清理成功，也不能同步关闭仍被 reader 占用的读端。
    """
    deadline = time.monotonic() + CLEANUP_TIMEOUT
    root_running = process.poll() is None
    errors = []
    if root_running:
        stopped, detail = kill_tree(process.pid, timeout=CLEANUP_TIMEOUT / 2)
        if not stopped:
            errors.append(f"tree cleanup unconfirmed ({detail})")
    elif os.name == "nt":
        errors.append("tree cleanup unconfirmed: root exited before pipe EOF")
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            errors.append(f"process group cleanup failed ({type(error).__name__})")
    try:
        process.communicate(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        errors.append("process or pipe cleanup timeout")
        # communicate 可能只卡在继承读写端的后代，仍需显式回收已经退出的根。
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            errors.append("root exit unconfirmed")
    return "; ".join(errors)


def run_frozen_check(
    command: Sequence[str],
    *,
    timeout: float,
    expected_returncode: int,
    stdout_contains: str | None = None,
    stderr_contains: str | None = None,
) -> None:
    """等待一次冻结入口探针；超时先清树再回收，输出按严格 UTF-8 验证。

    调用者拥有本次启动的根进程及管道。成功退出后才验证契约；超时、异常退出、
    缺失输出或清理未确认均不能发布通过结果。清理另有最多两秒预算。
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise CheckError("timeout must be a finite positive number")
    # 仅冻结探针需要项目进程清理工具；release 子命令不导入第三方依赖。
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.process_utils import kill_process_tree

    process = subprocess.Popen(
        list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            cleanup_error = _stop_and_reap(process, kill_process_tree)
            detail = f"; {cleanup_error}" if cleanup_error else ""
            raise CheckError(f"Timeout after {timeout:g}s{detail}") from error
        except BaseException:
            _stop_and_reap(process, kill_process_tree)
            raise
    finally:
        _close_pipes(process)
    if process.returncode != expected_returncode:
        raise CheckError(
            f"exit code {process.returncode}, expected {expected_returncode}",
        )
    for name, output, expected in (
        ("stdout", stdout, stdout_contains), ("stderr", stderr, stderr_contains),
    ):
        if expected is None:
            continue
        try:
            decoded = output.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise CheckError(f"{name} is not valid UTF-8") from error
        if expected not in decoded:
            raise CheckError(f"{name} is missing the expected argument token")


def check_frozen(executable: Path, timeout: float) -> None:
    """验证实际 EXE 的退出码与 worker 管道，支持无控制台 Windows 程序。"""
    if not executable.is_file():
        raise CheckError("frozen executable is missing or is not a file")
    target = str(executable.resolve())
    checks = (
        ("packaging", ["--self-check", "packaging"], 0, None, None),
        ("worker help", ["--mobileperf-worker", "--help"], 0, "--config", None),
        ("worker UTF-8", ["--mobileperf-worker", "--编码验证"], 2, None, "--编码验证"),
    )
    for label, arguments, returncode, stdout_token, stderr_token in checks:
        try:
            run_frozen_check(
                [target, *arguments], timeout=timeout, expected_returncode=returncode,
                stdout_contains=stdout_token, stderr_contains=stderr_token,
            )
        except CheckError as error:
            raise CheckError(f"{label}: {error}") from error
        print(f"PASS frozen {label}")


def _zip_entry_valid(entry: zipfile.ZipInfo) -> bool:
    mode = stat.S_IFMT(entry.external_attr >> 16)
    return not entry.is_dir() and entry.file_size > 0 and mode in (0, stat.S_IFREG)


def _check_zip(path: Path, expected_entries: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = [entry for entry in archive.infolist() if entry.filename in expected_entries]
        if len(entries) != 1 or not _zip_entry_valid(entries[0]):
            raise CheckError("expected exactly one nonempty regular main entry")
        if archive.testzip() is not None:
            raise CheckError("archive payload failed CRC validation")


def _check_tar(path: Path, expected_entry: str) -> None:
    found = []
    # 流式读取全部载荷并继续读取 gzip 尾部，防止 TAR 结束块掩盖压缩流截断。
    with gzip.open(path, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as archive:
            for entry in archive:
                if entry.name == expected_entry:
                    found.append(entry)
                if entry.isfile():
                    payload = archive.extractfile(entry)
                    if payload is None:
                        raise CheckError("archive entry payload is unreadable")
                    with payload:
                        while payload.read(1024 * 1024):
                            pass
        while compressed.read(1024 * 1024):
            pass
    if len(found) != 1 or not found[0].isfile() or found[0].size <= 0:
        raise CheckError("expected exactly one nonempty regular main entry")


def check_installer_file(path: Path) -> None:
    """只读核对普通非重解析 PE 文件及头/节边界；不验证压缩载荷或安装成功。

    允许 Inno 的文件尾 overlay；仅有 MZ 或 PE 签名不足以通过。仅按头部声明有界读取，
    不把完整安装 EXE 载入内存；任一 I/O 或结构错误统一抛出 CheckError。
    """
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise CheckError("installer must be a regular non-reparse file")
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size

            def read_at(offset: int, length: int) -> bytes:
                if offset < 0 or length < 0 or offset + length > size:
                    raise CheckError("installer PE header or section exceeds file bounds")
                stream.seek(offset)
                data = stream.read(length)
                if len(data) != length:
                    raise CheckError("installer PE file was truncated while reading")
                return data

            dos = read_at(0, 64)
            if dos[:2] != b"MZ":
                raise CheckError("installer DOS signature is missing")
            pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
            if pe_offset < 64:
                raise CheckError("installer PE header overlaps the DOS header")
            header = read_at(pe_offset, 24)
            if header[:4] != b"PE\0\0":
                raise CheckError("installer PE signature is missing")
            machine, sections, _, _, _, optional_size, characteristics = struct.unpack_from(
                "<HHIIIHH", header, 4,
            )
            if (machine not in (0x14C, 0x8664) or not 1 <= sections <= 96
                    or not characteristics & 2 or characteristics & 0x2000):
                raise CheckError("installer COFF header is not a supported executable image")
            optional_offset = pe_offset + 24
            optional = read_at(optional_offset, optional_size)
            if optional_size < 2:
                raise CheckError("installer optional header is missing")
            magic = struct.unpack_from("<H", optional)[0]
            fixed_size = {0x10B: 96, 0x20B: 112}.get(magic)
            if fixed_size is None or optional_size < fixed_size:
                raise CheckError("installer optional header is invalid or incomplete")
            if (machine == 0x14C) != (magic == 0x10B):
                raise CheckError("installer COFF machine and optional header disagree")
            directories = struct.unpack_from("<I", optional, fixed_size - 4)[0]
            if directories > (optional_size - fixed_size) // 8:
                raise CheckError("installer data directories exceed the optional header")
            entrypoint = struct.unpack_from("<I", optional, 16)[0]
            section_alignment, file_alignment = struct.unpack_from("<II", optional, 32)
            image_size, headers_size = struct.unpack_from("<II", optional, 56)
            if (not file_alignment or file_alignment & (file_alignment - 1)
                    or not section_alignment or section_alignment & (section_alignment - 1)
                    or section_alignment < file_alignment
                    or (section_alignment < 4096 and file_alignment != section_alignment)
                    or (section_alignment >= 4096 and not 512 <= file_alignment <= 65536)):
                raise CheckError("installer PE alignment is invalid")
            section_offset = optional_offset + optional_size
            table = read_at(section_offset, sections * 40)
            if (headers_size < section_offset + len(table) or headers_size > size
                    or headers_size % file_alignment or not image_size
                    or image_size % section_alignment):
                raise CheckError("installer PE image/header size is invalid")
            raw_ranges = []
            virtual_ranges = []
            executable_entry = False
            for index in range(sections):
                offset = index * 40
                virtual_size, address, raw_size, raw_pointer = struct.unpack_from(
                    "<IIII", table, offset + 8,
                )
                flags = struct.unpack_from("<I", table, offset + 36)[0]
                extent = max(virtual_size, raw_size)
                if (not extent or address < headers_size or address % section_alignment
                        or address + extent > image_size):
                    raise CheckError("installer PE section exceeds virtual image bounds")
                virtual_ranges.append((address, address + extent))
                if raw_size:
                    if (raw_pointer < headers_size or raw_pointer % file_alignment
                            or raw_size % file_alignment or raw_pointer + raw_size > size):
                        raise CheckError("installer PE section exceeds raw file bounds")
                    raw_ranges.append((raw_pointer, raw_pointer + raw_size))
                    if address <= entrypoint < address + raw_size and flags & 0x20000000:
                        executable_entry = True
            for ranges in (raw_ranges, virtual_ranges):
                ranges.sort()
                if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
                    raise CheckError("installer PE sections overlap")
            if not executable_entry:
                raise CheckError("installer entry point is not in a backed executable section")
    except (OSError, ValueError, struct.error) as error:
        raise CheckError(f"installer PE file cannot be validated: {error}") from error


def check_release(directory: Path, version: str) -> None:
    """只读验证五份准确版本产物；归档完整校验，setup 只验证 PE 结构。"""
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise CheckError("version must match vX.Y.Z using decimal digits")
    if not directory.is_dir():
        raise CheckError("release directory is missing or is not a directory")
    expected = {}
    for artifact in ARTIFACTS:
        name = f"{artifact}-{version}"
        suffix = ".tar.gz" if artifact == "ADBLab-linux-x64" else ".zip"
        expected[f"{artifact}/{name}{suffix}"] = (artifact, name)
    installer = f"ADBLab-win-x64/ADBLab-win-x64-{version}-setup.exe"
    expected[installer] = ("installer", "")
    actual = {
        path.relative_to(directory).as_posix(): path for path in directory.rglob("*")
        if not path.is_dir() or path.is_symlink()
    }
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    if missing or extra:
        raise CheckError(f"artifact set mismatch: missing={missing}; extra={extra}")
    for relative, (artifact, name) in expected.items():
        path = actual[relative]
        try:
            if artifact == "installer":
                check_installer_file(path)
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise CheckError("expected a nonempty regular archive")
            if artifact == "ADBLab-linux-x64":
                _check_tar(path, name)
            else:
                entries = (f"{name}.exe",) if artifact == "ADBLab-win-x64" else (
                    f"{name}.app/Contents/MacOS/{name}", name,
                )
                _check_zip(path, entries)
        except (
            CheckError, OSError, EOFError, ValueError, RuntimeError,
            zipfile.BadZipFile, tarfile.TarError, zlib.error,
        ) as error:
            raise CheckError(f"{relative}: {error}") from error
    print(f"PASS release {version}: exactly five artifacts (setup PE structure only)")


def _timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be a number") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return seconds


def main(argv: list[str] | None = None) -> int:
    """执行构建门禁；参数错误返回 2，产物或进程契约失败返回 1。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("frozen", help="wait for frozen executable smoke checks")
    frozen.add_argument("--executable", required=True, type=Path)
    frozen.add_argument("--timeout", required=True, type=_timeout)
    release = commands.add_parser("release", help="validate the five downloaded release artifacts")
    release.add_argument("--directory", required=True, type=Path)
    release.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "frozen":
            check_frozen(args.executable, args.timeout)
        else:
            check_release(args.directory, args.version)
    except (CheckError, OSError, ImportError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
