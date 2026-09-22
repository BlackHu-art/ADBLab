"""以受控进程和真实归档验证构建产物门禁。"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import psutil
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_build_artifacts.py"
VERSION = "v1.2.3"
ARTIFACTS = ("ADBLab-win-x64", "ADBLab-macos-x64", "ADBLab-macos-arm64", "ADBLab-linux-x64")


def _release_tree(directory: Path, *, mac_fallback: bool = False) -> list[Path]:
    paths = []
    for artifact in ARTIFACTS:
        name = f"{artifact}-{VERSION}"
        target = directory / artifact
        target.mkdir(parents=True)
        if artifact == "ADBLab-linux-x64":
            archive = target / f"{name}.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                entry = tarfile.TarInfo(name)
                entry.mode = 0o755
                entry.size = 3
                bundle.addfile(entry, io.BytesIO(b"exe"))
        else:
            archive = target / f"{name}.zip"
            entry = f"{name}.exe" if artifact == "ADBLab-win-x64" else (
                name if mac_fallback else f"{name}.app/Contents/MacOS/{name}"
            )
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(entry, b"exe")
        paths.append(archive)
    return paths


def _release(directory: Path, version: str = VERSION) -> subprocess.CompletedProcess:
    # -I -S 禁止项目路径与 site-packages 兜底，确保发布检查无需 pip 安装依赖。
    return subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "release", "--directory", str(directory),
         "--version", version],
        capture_output=True, timeout=10,
    )


@pytest.mark.parametrize("mac_fallback", [False, True])
def test_release_accepts_exact_readable_versioned_artifacts_without_site_packages(
    tmp_path, mac_fallback,
):
    _release_tree(tmp_path, mac_fallback=mac_fallback)

    result = _release(tmp_path)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert b"PASS" in result.stdout


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "wrong-version", "empty"])
def test_release_rejects_inexact_artifact_set(tmp_path, mutation):
    paths = _release_tree(tmp_path)
    if mutation == "missing":
        paths[0].unlink()
    elif mutation == "extra":
        (tmp_path / "unrelated.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "duplicate":
        (tmp_path / paths[0].name).write_bytes(paths[0].read_bytes())
    elif mutation == "wrong-version":
        paths[0].rename(paths[0].with_name(paths[0].name.replace(VERSION, "v1.2.4")))
    else:
        paths[0].write_bytes(b"")

    result = _release(tmp_path)

    assert result.returncode != 0
    assert b"FAIL" in result.stderr


@pytest.mark.parametrize("version", ["1.2.3", "v1.2", "v1.2.3-rc1", "v1.2.3/../x", "v１.2.3"])
def test_release_rejects_invalid_version(tmp_path, version):
    _release_tree(tmp_path)
    result = _release(tmp_path, version)
    assert result.returncode != 0
    assert b"version" in result.stderr.lower()


@pytest.mark.parametrize("platform_index", range(4))
def test_release_rejects_archive_without_expected_nonempty_regular_entry(tmp_path, platform_index):
    archive = _release_tree(tmp_path)[platform_index]
    if platform_index == 3:
        with tarfile.open(archive, "w:gz") as bundle:
            entry = tarfile.TarInfo("wrong-name")
            entry.size = 3
            bundle.addfile(entry, io.BytesIO(b"exe"))
    else:
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("wrong-name", b"exe")

    result = _release(tmp_path)

    assert result.returncode != 0
    assert b"entry" in result.stderr.lower()


@pytest.mark.parametrize("corruption", ["not-zip", "zip-crc", "truncated-tar"])
def test_release_rejects_corrupt_archive_payload(tmp_path, corruption):
    paths = _release_tree(tmp_path)
    if corruption == "not-zip":
        paths[0].write_bytes(b"not a zip")
    elif corruption == "zip-crc":
        paths[0].write_bytes(paths[0].read_bytes().replace(b"exe", b"bad", 1))
    else:
        paths[3].write_bytes(paths[3].read_bytes()[:-12])

    result = _release(tmp_path)

    assert result.returncode != 0
    assert b"FAIL" in result.stderr


@pytest.mark.parametrize("entry_kind", ["empty", "directory", "duplicate", "symlink"])
def test_release_rejects_invalid_main_entry(tmp_path, entry_kind):
    archive = _release_tree(tmp_path)[0]
    name = f"ADBLab-win-x64-{VERSION}.exe"
    with zipfile.ZipFile(archive, "w") as bundle:
        if entry_kind == "empty":
            bundle.writestr(name, b"")
        elif entry_kind == "directory":
            bundle.writestr(name + "/", b"")
        elif entry_kind == "symlink":
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            bundle.writestr(entry, b"other")
        else:
            bundle.writestr(name, b"exe")
            with pytest.warns(UserWarning, match="Duplicate"):
                bundle.writestr(name, b"exe")

    result = _release(tmp_path)

    assert result.returncode != 0
    assert b"entry" in result.stderr.lower()


def _checks():
    return importlib.import_module("scripts.check_build_artifacts")


def test_frozen_command_waits_for_exit_and_accepts_silent_packaging():
    checks = _checks()
    checks.run_frozen_check(
        [sys.executable, "-c", "import time; time.sleep(0.05)"],
        timeout=2, expected_returncode=0,
    )


def test_frozen_command_does_not_inherit_interactive_stdin():
    child_code = "import sys; assert sys.stdin.buffer.read(1) == b''"
    launcher = (
        "import sys; from scripts.check_build_artifacts import run_frozen_check; "
        f"run_frozen_check([sys.executable, '-c', {child_code!r}], "
        "timeout=0.5, expected_returncode=0)"
    )
    with subprocess.Popen(
        [sys.executable, "-c", launcher], cwd=SCRIPT.parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as process:
        process.wait(timeout=6)
        _, stderr = process.communicate(timeout=1)

    assert process.returncode == 0, stderr.decode("utf-8", errors="replace")


@pytest.mark.parametrize("code,kwargs", [
    ("raise SystemExit(3)", {}),
    ("print('missing option')", {"stdout_contains": "--config"}),
    ("import sys; sys.stderr.buffer.write(b'\\xff'); sys.exit(2)",
     {"expected_returncode": 2, "stderr_contains": "--编码验证"}),
    ("import sys; sys.stderr.write('other error'); sys.exit(2)",
     {"expected_returncode": 2, "stderr_contains": "--编码验证"}),
])
def test_frozen_command_rejects_exit_and_output_contract_failures(code, kwargs):
    checks = _checks()
    options = {"timeout": 2, "expected_returncode": 0, **kwargs}

    with pytest.raises(checks.CheckError):
        checks.run_frozen_check([sys.executable, "-c", code], **options)


def test_frozen_command_accepts_strict_utf8_chinese_error():
    checks = _checks()
    checks.run_frozen_check(
        [sys.executable, "-c",
         "import sys; sys.stderr.buffer.write('--编码验证'.encode('utf-8')); sys.exit(2)"],
        timeout=2, expected_returncode=2, stderr_contains="--编码验证",
    )


def _process_is_live(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest.mark.parametrize("root_exits", [False, True])
def test_frozen_timeout_is_bounded_and_cleans_descendant(tmp_path, root_exits):
    checks = _checks()
    child_pid_file = tmp_path / "child.pid"
    root_pid_file = tmp_path / "root.pid"
    child_code = "import time; time.sleep(30)"
    code = (
        "import os, pathlib, subprocess, sys, time; "
        f"pathlib.Path({str(root_pid_file)!r}).write_text(str(os.getpid())); "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid)); "
        + ("sys.exit(0)" if root_exits else "time.sleep(30)")
    )
    started = time.monotonic()
    try:
        with pytest.raises(checks.CheckError, match="[Tt]imeout"):
            checks.run_frozen_check(
                [sys.executable, "-c", code], timeout=0.5, expected_returncode=0,
            )
        assert time.monotonic() - started < 6
        root_pid = int(root_pid_file.read_text())
        child_pid = int(child_pid_file.read_text())
        assert not psutil.pid_exists(root_pid)
        # POSIX 独立进程组仍可定位已退出根留下的管道写端；Windows 应有界报告未确认清理。
        if not root_exits or os.name != "nt":
            deadline = time.monotonic() + 2
            while _process_is_live(child_pid) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not _process_is_live(child_pid)
    finally:
        for pid_file in (child_pid_file, root_pid_file):
            if pid_file.exists():
                pid = int(pid_file.read_text())
                if _process_is_live(pid):
                    psutil.Process(pid).kill()


def test_frozen_timeout_reports_unconfirmed_cleanup(monkeypatch):
    checks = _checks()
    from core import process_utils

    real_kill_tree = process_utils.kill_process_tree

    def unconfirmed_cleanup(pid, *, timeout):
        real_kill_tree(pid, timeout=timeout)
        return False, "simulated-unconfirmed-child"

    monkeypatch.setattr(process_utils, "kill_process_tree", unconfirmed_cleanup)

    with pytest.raises(checks.CheckError, match="tree cleanup unconfirmed"):
        checks.run_frozen_check(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1, expected_returncode=0,
        )


@pytest.mark.skipif(os.name == "nt", reason="Windows 不直接执行带 shebang 的 Python 测试程序")
def test_frozen_cli_checks_all_three_contracts(tmp_path):
    executable = tmp_path / "fake app"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if sys.argv[1:] == ['--self-check', 'packaging']:\n"
        "    sys.exit(0)\n"
        "if sys.argv[1:] == ['--mobileperf-worker', '--help']:\n"
        "    print('--config')\n"
        "    sys.exit(0)\n"
        "if sys.argv[1:] == ['--mobileperf-worker', '--编码验证']:\n"
        "    sys.stderr.buffer.write('--编码验证'.encode('utf-8'))\n"
        "    sys.exit(2)\n"
        "sys.exit(99)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "frozen", "--executable", str(executable), "--timeout", "2"],
        capture_output=True, timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout.count(b"PASS") == 3


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_frozen_cli_rejects_nonpositive_or_unbounded_timeout(timeout):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "frozen", "--executable", sys.executable,
         "--timeout", timeout],
        capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert b"timeout" in result.stderr.lower()
