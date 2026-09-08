"""在 QThread 中执行应用列表、管理、备份和恢复操作。"""

import concurrent.futures
import os
import re
import shlex
import shutil
import tempfile
import threading
import zipfile
from time import monotonic

from PySide6.QtCore import QThread, Signal

from core.exec import CommandRunner
from services.app_icons import load_app_icons
from utils.archive import safe_extract_zip

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def _safe_pkg(pkg: str) -> bool:
    """校验包名为安全 token，拒绝 shell 元字符与路径分隔符。"""
    return bool(_PACKAGE_NAME_RE.fullmatch(str(pkg or "")))
_DETAIL_BEGIN = "__ADBLAB_PKG_BEGIN_{}__"
_DETAIL_END = "__ADBLAB_PKG_END_{}__"


def _split_package_detail_sections(output: str, count: int) -> dict[int, str]:
    """只接纳首尾标记完整的详情，截断尾段留给有剩余预算的兼容查询。"""
    sections: dict[int, list[str]] = {}
    complete: dict[int, str] = {}
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
            if current is not None and current == end_markers[stripped]:
                complete[current] = "\n".join(sections[current])
                current = None
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return complete


class AppManagerWorker(QThread):
    """在界面线程外执行应用管理 ADB 操作，并通过信号返回结果。

    只读查询支持执行中取消；写操作保留阶段间中断及必要清理契约。命令失败通过已有日志或
    完成信号传播，禁止后台线程直接访问界面对象。
    """

    log_message = Signal(str)
    apps_loaded = Signal(list)
    app_details_loaded = Signal(dict)
    app_detail_batch = Signal(str, str, str, str)
    app_icon_loaded = Signal(str, bytes, str)
    permissions_loaded = Signal(list, list, list)
    backup_progress = Signal(str, str)
    operation_done = Signal(str)
    operation_feedback = Signal(str, str)

    def __init__(self, device_ip: str, operation: str, **kwargs):
        super().__init__()
        self.device_ip = device_ip
        self.operation = operation
        self.kwargs = kwargs
        self._aborted = threading.Event()
        self.operation_done.connect(self._report_success)

    def _report_success(self, action: str) -> None:
        """保留原完成信号的刷新用途，额外提供明确的用户反馈级别。"""
        self.operation_feedback.emit("success", f"{action}: {self.kwargs.get('package_name', '')}")

    def _report_failure(self, message: str) -> None:
        """保留日志消费者，同时以结构化失败通知界面，禁止解析日志文字判定级别。"""
        self.log_message.emit(message)
        self.operation_feedback.emit("error", message)

    def abort(self):
        """取消在途只读查询；写操作仍在原有阶段边界处理停止意图。"""
        self._aborted.set()
        self.requestInterruption()

    def _cancelled(self) -> bool:
        """统一读取任务和监督器的停止意图，供执行层及结果发布前检查。"""
        return self._aborted.is_set() or self.isInterruptionRequested()

    def run(self):
        """按 operation 分派后台操作；未知操作不执行任何任务。"""
        if self._aborted.is_set() or self.isInterruptionRequested():
            return
        ops = {
            "load_apps": self._load_apps,
            "load_detail_batch": lambda: self._load_detail_batch(self.kwargs.get("packages", [])),
            "load_icon_batch": lambda: load_app_icons(
                self.device_ip,
                self.kwargs.get("packages", []),
                lambda: self._aborted.is_set() or self.isInterruptionRequested(),
                self.app_icon_loaded.emit,
            ),
            "app_details": lambda: self._fetch_app_details(self.kwargs.get("package_name")),
            "app_snapshot": lambda: self._fetch_app_snapshot(self.kwargs.get("package_name")),
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

    def _adb(self, *args, timeout: float = 30, cancellable: bool = False):
        """仅显式只读调用传递取消，避免写操作或必要清理被一并中断。"""
        cmd = ["adb", "-s", self.device_ip] + list(args)
        if cancellable:
            return CommandRunner.run(cmd, timeout=timeout, cancelled=self._cancelled)
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
            r = self._adb("shell", "pm", "list", "packages", "-f", cancellable=True)
            if self._cancelled():
                return
            if not r.success:
                error = str(getattr(r, "error", "") or "").strip()
                self._report_failure(f"Failed to list apps: {error or 'adb command failed'}")
                return
            dr = self._adb("shell", "pm", "list", "packages", "-d", cancellable=True)
            if self._cancelled():
                return
            if not dr.success:
                self._report_failure("Failed to read disabled app states; refresh to retry")
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
            if not self._cancelled():
                self.apps_loaded.emit(apps)
        except Exception as e:
            self._report_failure(f"Error: {e}")

    def _load_detail_batch(self, packages):
        """批量及解析兼容查询共用原批次预算，失败不生成可缓存的空详情。"""
        if not packages or self._cancelled():
            return
        deadline = monotonic() + max(5, len(packages) * 2)
        safe_packages = [pkg for pkg in packages if _safe_pkg(pkg)]
        if len(safe_packages) != len(packages):
            self.log_message.emit("Invalid package names skipped while reading details")
        if not safe_packages:
            return
        remaining_packages = self._load_detail_batch_once(safe_packages, deadline=deadline)
        for pkg in remaining_packages:
            remaining = deadline - monotonic()
            if self._cancelled() or remaining <= 0:
                return
            r = self._adb(
                "shell", f"dumpsys package {pkg}", timeout=min(5, remaining), cancellable=True
            )
            if self._cancelled():
                return
            if not r.success:
                self.log_message.emit("Failed to read app details; refresh to retry")
                return
            if self._has_package_detail(r.stdout):
                self._emit_package_detail(pkg, r.stdout)

    def _load_detail_batch_once(self, packages, *, deadline: float) -> list[str]:
        """成功响应只补查缺失片段；命令失败、取消或预算耗尽不提交兼容查询。"""
        script_parts = []
        for i, pkg in enumerate(packages):
            script_parts.extend(
                [
                    f"echo {_DETAIL_BEGIN.format(i)}",
                    f"dumpsys package {pkg}",
                    f"echo {_DETAIL_END.format(i)}",
                ]
            )
        remaining = deadline - monotonic()
        if self._cancelled() or remaining <= 0:
            return []
        result = self._adb("shell", " ; ".join(script_parts), timeout=remaining, cancellable=True)
        if self._cancelled():
            return []
        if not result.success:
            self.log_message.emit("Failed to read app details; refresh to retry")
            return []
        sections = _split_package_detail_sections(result.stdout, len(packages))
        missing = []
        for i, pkg in enumerate(packages):
            if self._cancelled():
                return []
            out = sections.get(i, "")
            if self._has_package_detail(out):
                self._emit_package_detail(pkg, out)
            elif i not in sections:
                missing.append(pkg)
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i + 1}/{len(packages)}")
        return missing

    @staticmethod
    def _has_package_detail(out: str) -> bool:
        """包不存在或服务诊断也可能返回零退出码，必须包含实际包版本字段。"""
        return re.search(r"\bversionCode=\d+", out) is not None

    def _emit_package_detail(self, pkg: str, out: str):
        if self._cancelled():
            return
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
        out = self._read_package_snapshot(pkg, "details")
        if out is not None:
            self._emit_app_details(pkg, out)

    def _fetch_app_snapshot(self, pkg):
        """详情首载共用同一次设备快照，分别发布既有详情与权限结果。"""
        out = self._read_package_snapshot(pkg, "details")
        if out is not None:
            self._emit_app_details(pkg, out)
            self._emit_permissions(out)

    def _read_package_snapshot(self, pkg, part: str) -> str | None:
        """查询并验证包快照；失败或取消不生成任何详情或权限数据。"""
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
            return None
        r = self._adb("shell", f"dumpsys package {pkg}", cancellable=True)
        if self._cancelled():
            return None
        if not r.success or not self._has_package_detail(r.stdout):
            self._report_failure(f"Failed to read app {part}; retry after checking the device")
            return None
        return r.stdout

    def _emit_app_details(self, pkg, out: str) -> None:
        m_cp = re.search(r"codePath=(.*)", out)
        m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", out)
        m_vn = re.search(r"versionName=([\S]+)", out)
        m_vc = re.search(r"versionCode=(\d+)", out)
        m_ms = re.search(r"minSdk=(\d+)", out)
        m_ts = re.search(r"targetSdk=(\d+)", out)
        label = m_label.group(1).strip() if m_label else pkg.split(".")[-1].capitalize()
        if self._cancelled():
            return
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
        out = self._read_package_snapshot(pkg, "permissions")
        if out is not None:
            self._emit_permissions(out)

    def _emit_permissions(self, out: str) -> None:
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
        if not self._cancelled():
            self.permissions_loaded.emit(declared, requested, runtime)

    def _modify_app(self, action, pkg):
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
            return
        cmds = {
            "disable": ["shell", "pm", "disable-user", "--user", "0", pkg],
            "enable": ["shell", "pm", "enable", pkg],
            "uninstall": ["uninstall", "--user", "0", pkg],
            "force_stop": ["shell", "am", "force-stop", pkg],
        }
        cmd = cmds.get(action)
        if not cmd:
            self._report_failure(f"Invalid app action: {action}")
            return
        r = self._adb(*cmd)
        self.log_message.emit(f"{'OK' if r.success else 'FAIL'}: {action} {pkg}")
        if r.success:
            self.operation_done.emit(action)
        else:
            self.operation_feedback.emit("error", self._command_error(r, f"{action} failed: {pkg}"))

    def _launch_app(self, pkg):
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
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
            self._report_failure(
                f"Failed to launch {pkg}: {self._command_error(result, 'launch command failed')}"
            )
            return
        self.log_message.emit(f"Launched {pkg}")
        self.operation_done.emit("launch")

    def _clear_app(self, pkg):
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
            return
        r = self._adb("shell", "pm", "clear", pkg)
        if not r.success:
            self._report_failure(
                f"Failed to clear data for {pkg}: {self._command_error(r, 'clear command failed')}"
            )
            return
        self.log_message.emit(f"Cleared data: {pkg} — {r.stdout.strip()}")
        self.operation_done.emit("clear")

    def _modify_permission(self, pkg, perm, action):
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
            return
        if action not in {"grant", "revoke"}:
            self._report_failure(f"Invalid permission action: {action}")
            return
        r = self._adb("shell", "pm", action, pkg, shlex.quote(perm))
        if not r.success:
            self._report_failure(
                f"Failed to {action} permission {perm}: "
                f"{self._command_error(r, 'permission command failed')}"
            )
            return
        self.log_message.emit(f"Permission {action}: {perm} — {r.stdout.strip() or 'OK'}")
        self.operation_done.emit("permissions_changed")

    def _backup_app(self, pkg, save_dir):
        if not _safe_pkg(pkg):
            self._report_failure(f"Invalid package: {pkg}")
            return
        self.backup_progress.emit(pkg, "Fetching APK paths")
        r = self._adb("shell", f"pm path {pkg}")
        if not r.success:
            self._report_failure(
                f"Backup failed for {pkg}: {self._command_error(r, 'failed to fetch APK paths')}"
            )
            return
        paths = [
            line.replace("package:", "").strip()
            for line in r.stdout.strip().splitlines()
            if line.strip()
        ]
        if not paths:
            self._report_failure(f"No APK for {pkg}")
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
                self._report_failure(
                    f"Backup failed for {pkg}: {len(failed_pulls)}/{len(paths)} "
                    f"APK pulls failed; {failed_pulls[0]}"
                )
                return
            if self._aborted.is_set() or self.isInterruptionRequested():
                self.log_message.emit(f"Backup aborted for {pkg}")
                self.operation_feedback.emit("info", f"Backup aborted: {pkg}")
                return

            pulled_apks = [
                os.path.join(root, name)
                for root, _, files in os.walk(tmp)
                for name in files
                if name.lower().endswith(".apk")
            ]
            if len(pulled_apks) != len(paths):
                self._report_failure(
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
                self._report_failure(f"Backup failed for {pkg}: {exc}")
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
                self._report_failure(
                    f"Restore failed ({i + 1}/{len(files)}) for {os.path.basename(zp)}: {e}"
                )
        if failed:
            message = f"Restore incomplete: {succeeded} succeeded, {failed} failed"
            self.log_message.emit(message)
            self.operation_feedback.emit("warning" if succeeded else "error", message)
            return
        self.log_message.emit(f"Restore complete: {succeeded}/{len(files)} succeeded")
        self.operation_done.emit("restore")
