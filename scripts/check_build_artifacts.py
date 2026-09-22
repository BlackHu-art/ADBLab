"""验证冻结入口和发布归档；发布检查仅依赖标准库且不解压产物。"""

from __future__ import annotations

import argparse
import gzip
import math
import os
import re
import signal
import stat
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


def check_release(directory: Path, version: str) -> None:
    """只读验证四份准确版本的非空归档及主程序条目，不展开到文件系统。"""
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise CheckError("version must match vX.Y.Z using decimal digits")
    if not directory.is_dir():
        raise CheckError("release directory is missing or is not a directory")
    expected = {}
    for artifact in ARTIFACTS:
        name = f"{artifact}-{version}"
        suffix = ".tar.gz" if artifact == "ADBLab-linux-x64" else ".zip"
        expected[f"{artifact}/{name}{suffix}"] = (artifact, name)
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
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise CheckError(f"{relative}: expected a nonempty regular archive")
        try:
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
    print(f"PASS release {version}: exactly four readable artifacts")


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
    release = commands.add_parser("release", help="validate the four downloaded release archives")
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
