"""应用备份与恢复完整事务；保留阶段取消、原子发布及逐写用户核验。"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from services.apps.actions import command_error
from services.apps.package_details import is_safe_package
from utils.archive import safe_extract_zip

if TYPE_CHECKING:
    from services.apps.queries import QueryExecutor


def backup_app(
    package: str,
    save_dir: str,
    user_id: int,
    *,
    execute: QueryExecutor,
    cancelled: Callable[[], bool],
    progress: Callable[[str, str], None],
    log: Callable[[str], None],
    feedback: Callable[[str, str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
) -> None:
    """串行拉取后在目标目录暂存压缩；仅在发布前未取消时原子替换旧归档。"""
    if not is_safe_package(package):
        failure(f"Invalid package: {package}")
        return
    progress(package, "Fetching APK paths")
    r = execute("shell", f"pm path --user {user_id} {package}")
    if not r.success:
        failure(f"Backup failed for {package}: {command_error(r, 'failed to fetch APK paths')}")
        return
    paths = [
        line.replace("package:", "").strip()
        for line in r.stdout.strip().splitlines()
        if line.strip()
    ]
    if not paths:
        failure(f"No APK for {package}")
        return
    with tempfile.TemporaryDirectory(prefix=f"bk_{package}_") as tmp:
        progress(package, f"Pulling {len(paths)} APKs")
        # 页面按设备串行调度，备份内部也串行，避免嵌套并发放大进程预算。
        pull_results = []
        for path in paths:
            if cancelled():
                return
            pull_results.append(execute("pull", path, tmp))
        failed_pulls = [
            command_error(result, f"pull failed for {path}")
            for path, result in zip(paths, pull_results)
            if not result.success
        ]
        if failed_pulls:
            failure(
                f"Backup failed for {package}: {len(failed_pulls)}/{len(paths)} "
                f"APK pulls failed; {failed_pulls[0]}"
            )
            return
        if cancelled():
            log(f"Backup aborted for {package}")
            feedback("info", f"Backup aborted: {package}")
            return

        pulled_apks = [
            os.path.join(root, name)
            for root, _, files in os.walk(tmp)
            for name in files
            if name.lower().endswith(".apk")
        ]
        if len(pulled_apks) != len(paths):
            failure(
                f"Backup failed for {package}: expected {len(paths)} APKs, "
                f"found {len(pulled_apks)} after pull"
            )
            return

        try:
            os.makedirs(save_dir, exist_ok=True)
            final_path = os.path.join(save_dir, f"backup_{package}.zip")
            with tempfile.TemporaryDirectory(prefix=".adblab_backup_", dir=save_dir) as archive_tmp:
                archive_base = os.path.join(archive_tmp, f"backup_{package}")
                staged_path = shutil.make_archive(archive_base, "zip", tmp)
                # 压缩可能耗时较长；发布前再次核对取消，不能覆盖用户保留的旧备份。
                if cancelled():
                    log(f"Backup aborted for {package}")
                    feedback("info", f"Backup aborted: {package}")
                    return
                os.replace(staged_path, final_path)
        except Exception as exc:
            failure(f"Backup failed for {package}: {exc}")
            return
        log(f"Backup: {final_path}")
        completed("backup")


def restore_apps(
    files: Sequence[str],
    *,
    execute: QueryExecutor,
    cancelled: Callable[[], bool],
    confirm_user: Callable[[], int | None],
    log: Callable[[str], None],
    feedback: Callable[[str, str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
) -> None:
    """安全解压并在每次安装前复核固定用户；取消和失败保留已完成安装与原计数时点。"""
    if not files:
        return
    succeeded = 0
    failed = 0
    installed = 0

    def report_cancelled() -> bool:
        # 安装不可回滚；停止后续写入并保留已完成数量，不能发布完整成功。
        if not cancelled():
            return False
        message = f"Restore cancelled: {installed} APKs installed, {succeeded} archives completed"
        log(message)
        feedback("warning", message)
        return True

    for i, zp in enumerate(files):
        if report_cancelled():
            return
        app = os.path.basename(zp).replace("backup_", "").replace(".zip", "")
        try:
            with tempfile.TemporaryDirectory(prefix=f"rs_{app}_") as tmp:
                with zipfile.ZipFile(zp, "r") as zf:
                    safe_extract_zip(zf, tmp)
                if report_cancelled():
                    return
                apks = [
                    os.path.join(r, f)
                    for r, _, fs in os.walk(tmp)
                    for f in fs
                    if f.endswith(".apk")
                ]
                if not apks:
                    raise RuntimeError("backup contains no APK files")
                is_split = len(apks) > 1 and any(
                    os.path.basename(a).lower() == "base.apk" for a in apks
                )
                if report_cancelled():
                    return
                if is_split:
                    user_id = confirm_user()
                    if user_id is None:
                        return
                    install_result = execute(
                        "install-multiple", "--user", str(user_id), "-r", *apks, timeout=120
                    )
                    if not install_result.success:
                        raise RuntimeError(command_error(install_result, "install-multiple failed"))
                    installed += len(apks)
                else:
                    for a in apks:
                        if report_cancelled():
                            return
                        user_id = confirm_user()
                        if user_id is None:
                            return
                        install_result = execute(
                            "install", "--user", str(user_id), "-r", a, timeout=120
                        )
                        if not install_result.success:
                            raise RuntimeError(command_error(install_result, "install failed"))
                        installed += 1
            succeeded += 1
            log(f"Restored ({i + 1}/{len(files)}): {os.path.basename(zp)}")
        except Exception as e:
            failed += 1
            failure(f"Restore failed ({i + 1}/{len(files)}) for {os.path.basename(zp)}: {e}")
    if report_cancelled():
        return
    if failed:
        message = f"Restore incomplete: {succeeded} succeeded, {failed} failed"
        log(message)
        feedback("warning" if succeeded else "error", message)
        return
    log(f"Restore complete: {succeeded}/{len(files)} succeeded")
    completed("restore")
