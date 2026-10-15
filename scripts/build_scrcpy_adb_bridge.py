"""使用现有 PyInstaller 构建独立 CLI，产物保持 onedir 以减少重复解压开销。"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

SELF_CHECK_TIMEOUT = 15


@contextmanager
def _build_lock(path: Path) -> Iterator[None]:
    """跨进程拒绝并发构建；锁文件保持原位，进程退出由操作系统释放锁。"""
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("无法取得 helper 构建锁，请等待已有构建结束后重试。") from error
        yield


def _self_check(executable: Path, log: Path, *, check: bool) -> int:
    """所有自检均限时执行并保存原始输出，失败时不会修改已发布的 helper。"""
    with log.open("wb") as stream:
        result = subprocess.run(
            [str(executable), "--self-check"], check=check, timeout=SELF_CHECK_TIMEOUT,
            stdout=stream, stderr=subprocess.STDOUT,
        )
    return result.returncode


def _publish(candidate: Path, output: Path, previous: Path) -> None:
    """同文件系统重命名发布；占用或第二步失败时恢复旧目录，无法回滚则保留备份。"""
    if candidate.stat().st_dev != output.parent.stat().st_dev:
        raise OSError(errno.EXDEV, "helper 候选与正式目录必须位于同一文件系统。")
    try:
        if output.exists():
            output.rename(previous)
        candidate.rename(output)
    except BaseException:
        # 非空目录无法跨平台一次替换；中断也尝试恢复，绝不递归删除原有正式目录。
        if previous.exists() and not output.exists():
            try:
                previous.rename(output)
            except OSError as error:
                raise RuntimeError(f"无法恢复旧 helper，请保留并检查备份：{previous}") from error
        raise


def main() -> int:
    """只在 build 内构建、自检并发布；候选和诊断不进入正式打包收集目录。"""
    from utils.scrcpy_bridge import BRIDGE_NAME, bridge_source_digest

    build = ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)
    with _build_lock(build / "adb-bridge-build.lock"):
        output = build / "runtime-helpers" / BRIDGE_NAME
        filename = BRIDGE_NAME + (".exe" if sys.platform == "win32" else "")
        executable = output / filename
        stamp = output / "source.sha256"
        expected = bridge_source_digest(ROOT)
        if (
            executable.is_file() and stamp.is_file()
            and stamp.read_text(encoding="ascii").strip() == expected
        ):
            log = build / "adb-bridge-self-check.log"
            print(f"helper 自检日志：{log}")
            return _self_check(executable, log, check=False)
        staging_root = build / "adb-bridge-staging"
        staging_root.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=staging_root))
        candidate = stage / "dist" / BRIDGE_NAME
        print(f"helper 构建和自检日志：{stage}")
        with (stage / "build.log").open("wb") as stream:
            subprocess.run([
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--onedir", "--console", "--noupx", "--name", BRIDGE_NAME,
                "--paths", str(ROOT), "--distpath", str(stage / "dist"),
                "--workpath", str(stage / "work"), "--specpath", str(stage),
                str(ROOT / "scripts" / "scrcpy_adb_bridge.py"),
            ], cwd=ROOT, check=True, stdout=stream, stderr=subprocess.STDOUT)
        _self_check(candidate / filename, stage / "self-check.log", check=True)
        if bridge_source_digest(ROOT) != expected:
            raise RuntimeError("helper 构建期间源码已变化，请重新构建；旧产物保持不变。")
        (candidate / "source.sha256").write_text(expected + "\n", encoding="ascii")
        output.parent.mkdir(parents=True, exist_ok=True)
        _publish(candidate, output, stage / "previous")
        # 仅删除本次 mkdtemp 创建的直接子目录；占用的备份保留在正式收集范围之外。
        if stage.resolve().parent != staging_root.resolve():
            raise RuntimeError("helper 候选清理路径不在本次构建目录内。")
        try:
            shutil.rmtree(stage)
        except OSError as error:
            print(f"helper 已发布，构建目录暂未清理（{type(error).__name__}）：{stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
