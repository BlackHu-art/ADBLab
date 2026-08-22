"""在 QThread 中执行应用列表、管理、备份和恢复操作。"""

import concurrent.futures
import os
import re
import shlex
import shutil
import tempfile
import threading
import zipfile

from PySide6.QtCore import QThread, Signal

from core.exec import CommandRunner
from utils.archive import safe_extract_zip

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def _safe_pkg(pkg: str) -> bool:
    """校验包名为安全 token，拒绝 shell 元字符与路径分隔符。"""
    return bool(_PACKAGE_NAME_RE.fullmatch(str(pkg or "")))
_DETAIL_BEGIN = "__ADBLAB_PKG_BEGIN_{}__"
_DETAIL_END = "__ADBLAB_PKG_END_{}__"


def _split_package_detail_sections(output: str, count: int) -> dict[int, str]:
    sections: dict[int, list[str]] = {}
    current: int | None = None
    begin_markers = {_DETAIL_BEGIN.format(i): i for i in range(count)}
    end_markers = {_DETAIL_END.format(i): i for i in range(count)}
    for line in output.splitlines():
        stripped = line.strip()
        if stripped in begin_markers:
            current = begin_markers[stripped]
            sections[current] = []
            continue
        if stripped in end_markers:
            if current == end_markers[stripped]:
                current = None
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {index: "\n".join(lines) for index, lines in sections.items()}


class AppManagerWorker(QThread):
    """在界面线程外执行应用管理 ADB 操作，并通过信号返回结果。

    abort() 只设置中断意图；各阶段需主动检查该状态。命令失败通过已有日志或完成信号
    传播，禁止后台线程直接访问界面对象。
    """

    log_message = Signal(str)
    apps_loaded = Signal(list)
    app_details_loaded = Signal(dict)
    app_detail_batch = Signal(str, str, str, str)
    permissions_loaded = Signal(list, list, list)
    backup_progress = Signal(str, str)
    operation_done = Signal(str)

    def __init__(self, device_ip: str, operation: str, **kwargs):
        super().__init__()
        self.device_ip = device_ip
        self.operation = operation
        self.kwargs = kwargs
        self._aborted = threading.Event()

    def abort(self):
        """请求协作式中止，正在执行的短命令完成后由任务检查状态。"""
        self._aborted.set()
        self.requestInterruption()

    def run(self):
        """按 operation 分派后台操作；未知操作不执行任何任务。"""
        ops = {
            "load_apps": self._load_apps,
            "load_detail_batch": lambda: self._load_detail_batch(self.kwargs.get("packages", [])),
            "app_details": lambda: self._fetch_app_details(self.kwargs.get("package_name")),
            "permissions": lambda: self._fetch_permissions(self.kwargs.get("package_name")),
            "modify_app": lambda: self._modify_app(
                self.kwargs.get("action"), self.kwargs.get("package_name")
            ),
            "backup_app": lambda: self._backup_app(
                self.kwargs.get("package_name"), self.kwargs.get("save_dir")
            ),
            "restore_apps": lambda: self._restore_apps(self.kwargs.get("file_paths", [])),
            "modify_permission": lambda: self._modify_permission(
                self.kwargs.get("package_name"),
                self.kwargs.get("permission"),
                self.kwargs.get("action"),
            ),
            "launch_app": lambda: self._launch_app(self.kwargs.get("package_name")),
            "clear_app": lambda: self._clear_app(self.kwargs.get("package_name")),
        }
        f = ops.get(self.operation)
        if f:
            f()

    def _adb(self, *args, timeout=30):
        cmd = ["adb", "-s", self.device_ip] + list(args)
        return CommandRunner.run(cmd, timeout=timeout)

    @staticmethod
    def _command_error(result, fallback: str) -> str:
        error = str(getattr(result, "error", "") or "").strip()
        if error:
            return error
        output = str(getattr(result, "output", "") or "").strip()
        return output or fallback

    def _load_apps(self):
        self.log_message.emit("Fetching installed apps...")
        try:
            r = self._adb("shell", "pm", "list", "packages", "-f")
            if self._aborted.is_set():
                return
            if not r.success:
                error = str(getattr(r, "error", "") or "").strip()
                self.log_message.emit(f"Failed to list apps: {error or 'adb command failed'}")
                return
            dr = self._adb("shell", "pm", "list", "packages", "-d")
            if self._aborted.is_set():
                return
            disabled = (
                {line.replace("package:", "").strip() for line in dr.stdout.splitlines()}
                if dr.success
                else set()
            )
            apps = []
            for line in r.stdout.splitlines():
                parts = line.split("=")
                pkg = parts[-1].strip()
                fp = "=".join(parts[:-1]).replace("package:", "").strip()
                if not pkg:
                    continue
                if "/data/app/" in fp:
                    atype = "User"
                elif "/system/" in fp:
                    atype = "System"
                elif "/vendor/" in fp:
                    atype = "Vendor"
                else:
                    atype = "Other"
                name = pkg.split(".")[-1].replace("_", " ").capitalize()
                st = "Disabled" if pkg in disabled else "Enabled"
                apps.append((name, pkg, st, atype))
            self.log_message.emit(f"Loaded {len(apps)} apps.")
            self.apps_loaded.emit(apps)
        except Exception as e:
            self.log_message.emit(f"Error: {e}")

    def _load_detail_batch(self, packages):
        total = len(packages)
        if not packages:
            return
        if self._load_detail_batch_once(packages):
            return
        for i, pkg in enumerate(packages):
            if self._aborted.is_set() or self.isInterruptionRequested():
                return
            if not _safe_pkg(pkg):
                self.app_detail_batch.emit(pkg, "", "", "")
                continue
            try:
                r = self._adb("shell", f"dumpsys package {pkg}", timeout=5)
                self._emit_package_detail(pkg, r.stdout)
            except Exception:
                self.app_detail_batch.emit(pkg, "", "", "")
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i + 1}/{total}")

    def _load_detail_batch_once(self, packages) -> bool:
        safe_packages = [pkg for pkg in packages if _PACKAGE_NAME_RE.fullmatch(str(pkg or ""))]
        if len(safe_packages) != len(packages):
            return False
        script_parts = []
        for i, pkg in enumerate(packages):
            script_parts.extend(
                [
                    f"echo {_DETAIL_BEGIN.format(i)}",
                    f"dumpsys package {pkg}",
                    f"echo {_DETAIL_END.format(i)}",
                ]
            )
        result = self._adb("shell", " ; ".join(script_parts), timeout=max(5, len(packages) * 2))
        if not result.success:
            return False
        sections = _split_package_detail_sections(result.stdout, len(packages))
        if len(sections) != len(packages):
            return False
        for i, pkg in enumerate(packages):
            if self._aborted.is_set() or self.isInterruptionRequested():
                return True
            self._emit_package_detail(pkg, sections.get(i, ""))
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i + 1}/{len(packages)}")
        return True

    def _emit_package_detail(self, pkg: str, out: str):
        m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", out)
        label = m_label.group(1).strip() if m_label else ""
        m_vn = re.search(r"versionName=([\S]+)", out)
        m_vc = re.search(r"versionCode=(\d+)", out)
        vn = m_vn.group(1) if m_vn else ""
        vc = m_vc.group(1) if m_vc else ""
        m_it = re.search(r"firstInstallTime=(\d{4}-\d{2}-\d{2})", out)
        itime = m_it.group(1) if m_it else ""
        self.app_detail_batch.emit(
            pkg, label or pkg.split(".")[-1], f"{vn} ({vc})" if vn else "", itime
        )

    def _fetch_app_details(self, pkg):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        r = self._adb("shell", f"dumpsys package {pkg}")
        out = r.stdout
        m_cp = re.search(r"codePath=(.*)", out)
        m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", out)
        m_vn = re.search(r"versionName=([\S]+)", out)
        m_vc = re.search(r"versionCode=(\d+)", out)
        m_ms = re.search(r"minSdk=(\d+)", out)
        m_ts = re.search(r"targetSdk=(\d+)", out)
        label = m_label.group(1).strip() if m_label else pkg.split(".")[-1].capitalize()
        self.app_details_loaded.emit(
            {
                "App Name": label,
                "Package": pkg,
                "Path": m_cp.group(1) if m_cp else "?",
                "Version": (
                    f"{m_vn.group(1) if m_vn else '?'} (code "
                    f"{m_vc.group(1) if m_vc else '?'})"
                ),
                "Min SDK": m_ms.group(1) if m_ms else "?",
                "Target SDK": m_ts.group(1) if m_ts else "?",
            }
        )

    def _fetch_permissions(self, pkg):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        r = self._adb("shell", f"dumpsys package {pkg}")
        out = r.stdout

        def ps(h, t):
            m = re.search(h + r":\n((?:.+?\n)+?)(?:\n\S|\Z)", t, re.MULTILINE)
            return (
                [line.strip() for line in m.group(1).strip().splitlines() if line.strip()]
                if m
                else []
            )

        declared = [p.split(":")[0] for p in ps(r"declared permissions", out)]
        requested = ps(r"requested permissions", out)
        runtime = []
        for line in ps(r"runtime permissions", out):
            m = re.match(r"(.+?): granted=(true|false)", line)
            if m:
                runtime.append((m.group(1).strip(), m.group(2) == "true"))
        self.permissions_loaded.emit(declared, requested, runtime)

    def _modify_app(self, action, pkg):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        cmds = {
            "disable": ["shell", "pm", "disable-user", "--user", "0", pkg],
            "enable": ["shell", "pm", "enable", pkg],
            "uninstall": ["uninstall", "--user", "0", pkg],
            "force_stop": ["shell", "am", "force-stop", pkg],
        }
        cmd = cmds.get(action)
        if not cmd:
            return
        r = self._adb(*cmd)
        self.log_message.emit(f"{'OK' if r.success else 'FAIL'}: {action} {pkg}")
        if r.success:
            self.operation_done.emit(action)

    def _launch_app(self, pkg):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        result = self._adb(
            "shell",
            "monkey",
            "-p",
            pkg,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        if not result.success:
            self.log_message.emit(
                f"Failed to launch {pkg}: {self._command_error(result, 'launch command failed')}"
            )
            return
        self.log_message.emit(f"Launched {pkg}")
        self.operation_done.emit("launch")

    def _clear_app(self, pkg):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        r = self._adb("shell", "pm", "clear", pkg)
        if not r.success:
            self.log_message.emit(
                f"Failed to clear data for {pkg}: {self._command_error(r, 'clear command failed')}"
            )
            return
        self.log_message.emit(f"Cleared data: {pkg} — {r.stdout.strip()}")
        self.operation_done.emit("clear")

    def _modify_permission(self, pkg, perm, action):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        if action not in {"grant", "revoke"}:
            self.log_message.emit(f"Invalid permission action: {action}")
            return
        r = self._adb("shell", "pm", action, pkg, shlex.quote(perm))
        if not r.success:
            self.log_message.emit(
                f"Failed to {action} permission {perm}: "
                f"{self._command_error(r, 'permission command failed')}"
            )
            return
        self.log_message.emit(f"Permission {action}: {perm} — {r.stdout.strip() or 'OK'}")
        self.operation_done.emit("permissions_changed")

    def _backup_app(self, pkg, save_dir):
        if not _safe_pkg(pkg):
            self.log_message.emit(f"Invalid package: {pkg}")
            return
        self.backup_progress.emit(pkg, "Fetching APK paths")
        r = self._adb("shell", f"pm path {pkg}")
        if not r.success:
            self.log_message.emit(
                f"Backup failed for {pkg}: {self._command_error(r, 'failed to fetch APK paths')}"
            )
            return
        paths = [
            line.replace("package:", "").strip()
            for line in r.stdout.strip().splitlines()
            if line.strip()
        ]
        if not paths:
            self.log_message.emit(f"No APK for {pkg}")
            return
        with tempfile.TemporaryDirectory(prefix=f"bk_{pkg}_") as tmp:
            self.backup_progress.emit(pkg, f"Pulling {len(paths)} APKs")
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(paths), 5)) as ex:
                pull_results = list(ex.map(lambda p: self._adb("pull", p, tmp), paths))
            failed_pulls = [
                self._command_error(result, f"pull failed for {path}")
                for path, result in zip(paths, pull_results)
                if not result.success
            ]
            if failed_pulls:
                self.log_message.emit(
                    f"Backup failed for {pkg}: {len(failed_pulls)}/{len(paths)} "
                    f"APK pulls failed; {failed_pulls[0]}"
                )
                return
            if self._aborted.is_set() or self.isInterruptionRequested():
                self.log_message.emit(f"Backup aborted for {pkg}")
                return

            pulled_apks = [
                os.path.join(root, name)
                for root, _, files in os.walk(tmp)
                for name in files
                if name.lower().endswith(".apk")
            ]
            if len(pulled_apks) != len(paths):
                self.log_message.emit(
                    f"Backup failed for {pkg}: expected {len(paths)} APKs, "
                    f"found {len(pulled_apks)} after pull"
                )
                return

            try:
                os.makedirs(save_dir, exist_ok=True)
                final_path = os.path.join(save_dir, f"backup_{pkg}.zip")
                with tempfile.TemporaryDirectory(
                    prefix=".adblab_backup_", dir=save_dir
                ) as archive_tmp:
                    archive_base = os.path.join(archive_tmp, f"backup_{pkg}")
                    staged_path = shutil.make_archive(archive_base, "zip", tmp)
                    os.replace(staged_path, final_path)
            except Exception as exc:
                self.log_message.emit(f"Backup failed for {pkg}: {exc}")
                return
            self.log_message.emit(f"Backup: {final_path}")
            self.operation_done.emit("backup")

    def _restore_apps(self, files):
        if not files:
            return
        succeeded = 0
        failed = 0
        for i, zp in enumerate(files):
            if self._aborted.is_set() or self.isInterruptionRequested():
                return
            app = os.path.basename(zp).replace("backup_", "").replace(".zip", "")
            try:
                with tempfile.TemporaryDirectory(prefix=f"rs_{app}_") as tmp:
                    with zipfile.ZipFile(zp, "r") as zf:
                        safe_extract_zip(zf, tmp)
                    apks = [
                        os.path.join(r, f)
                        for r, _, fs in os.walk(tmp)
                        for f in fs
                        if f.endswith(".apk")
                    ]
                    if not apks:
                        raise RuntimeError("backup contains no APK files")
                    is_split = len(apks) > 1 and any("base.apk" in a.lower() for a in apks)
                    if is_split:
                        install_result = self._adb("install-multiple", "-r", *apks, timeout=120)
                        if not install_result.success:
                            raise RuntimeError(
                                self._command_error(install_result, "install-multiple failed")
                            )
                    else:
                        for a in apks:
                            install_result = self._adb("install", "-r", a, timeout=120)
                            if not install_result.success:
                                raise RuntimeError(
                                    self._command_error(install_result, "install failed")
                                )
                succeeded += 1
                self.log_message.emit(f"Restored ({i + 1}/{len(files)}): {os.path.basename(zp)}")
            except Exception as e:
                failed += 1
                self.log_message.emit(
                    f"Restore failed ({i + 1}/{len(files)}) for {os.path.basename(zp)}: {e}"
                )
        if failed:
            self.log_message.emit(f"Restore incomplete: {succeeded} succeeded, {failed} failed")
            return
        self.log_message.emit(f"Restore complete: {succeeded}/{len(files)} succeeded")
        self.operation_done.emit("restore")
