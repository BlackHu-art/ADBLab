"""App Manager background worker — QThread for listing, managing, backing up apps."""

import concurrent.futures
import os
import re
import shutil
import tempfile
import zipfile

from PySide6.QtCore import QThread, Signal

from utils.archive import safe_extract_zip

from .base.command_runner import CommandRunner

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")
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
    """Runs app management ADB operations off the UI thread."""

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
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()

    def run(self):
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

    def _load_apps(self):
        self.log_message.emit("Fetching installed apps...")
        try:
            r = self._adb("shell", "pm", "list", "packages", "-f")
            if self._aborted:
                return
            dr = self._adb("shell", "pm", "list", "packages", "-d")
            if self._aborted:
                return
            disabled = {line.replace("package:", "").strip() for line in dr.stdout.splitlines()}
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
            if self._aborted or self.isInterruptionRequested():
                return
            try:
                r = self._adb("shell", f"dumpsys package {pkg}", timeout=5)
                self._emit_package_detail(pkg, r.stdout)
            except Exception:
                self.app_detail_batch.emit(pkg, "", "", "")
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i+1}/{total}")

    def _load_detail_batch_once(self, packages) -> bool:
        safe_packages = [pkg for pkg in packages if _PACKAGE_NAME_RE.match(str(pkg or ""))]
        if len(safe_packages) != len(packages):
            return False
        script_parts = []
        for i, pkg in enumerate(packages):
            script_parts.extend([
                f"echo {_DETAIL_BEGIN.format(i)}",
                f"dumpsys package {pkg}",
                f"echo {_DETAIL_END.format(i)}",
            ])
        result = self._adb("shell", " ; ".join(script_parts), timeout=max(5, len(packages) * 2))
        if not result.success:
            return False
        sections = _split_package_detail_sections(result.stdout, len(packages))
        if len(sections) != len(packages):
            return False
        for i, pkg in enumerate(packages):
            if self._aborted or self.isInterruptionRequested():
                return True
            self._emit_package_detail(pkg, sections.get(i, ""))
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i+1}/{len(packages)}")
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
        r = self._adb("shell", f"dumpsys package {pkg}")
        out = r.stdout
        m_cp = re.search(r"codePath=(.*)", out)
        m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", out)
        m_vn = re.search(r"versionName=([\S]+)", out)
        m_vc = re.search(r"versionCode=(\d+)", out)
        m_ms = re.search(r"minSdk=(\d+)", out)
        m_ts = re.search(r"targetSdk=(\d+)", out)
        label = m_label.group(1).strip() if m_label else pkg.split(".")[-1].capitalize()
        self.app_details_loaded.emit({
            "App Name": label,
            "Package": pkg,
            "Path": m_cp.group(1) if m_cp else "?",
            "Version": f"{m_vn.group(1) if m_vn else '?'} (code {m_vc.group(1) if m_vc else '?'})",
            "Min SDK": m_ms.group(1) if m_ms else "?",
            "Target SDK": m_ts.group(1) if m_ts else "?",
        })

    def _fetch_permissions(self, pkg):
        r = self._adb("shell", f"dumpsys package {pkg}")
        out = r.stdout

        def ps(h, t):
            m = re.search(h + r":\n((?:.+?\n)+?)(?:\n\S|\Z)", t, re.MULTILINE)
            return [line.strip() for line in m.group(1).strip().splitlines() if line.strip()] if m else []

        declared = [p.split(":")[0] for p in ps(r"declared permissions", out)]
        requested = ps(r"requested permissions", out)
        runtime = []
        for line in ps(r"runtime permissions", out):
            m = re.match(r"(.+?): granted=(true|false)", line)
            if m:
                runtime.append((m.group(1).strip(), m.group(2) == "true"))
        self.permissions_loaded.emit(declared, requested, runtime)

    def _modify_app(self, action, pkg):
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
        self.log_message.emit(f"{'OK' if r.returncode==0 else 'FAIL'}: {action} {pkg}")
        if r.returncode == 0:
            self.operation_done.emit(action)

    def _launch_app(self, pkg):
        self._adb("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
        self.log_message.emit(f"Launched {pkg}")

    def _clear_app(self, pkg):
        r = self._adb("shell", "pm", "clear", pkg)
        self.log_message.emit(f"Cleared data: {pkg} — {r.stdout.strip()}")

    def _modify_permission(self, pkg, perm, action):
        r = self._adb("shell", "pm", action, pkg, perm)
        self.log_message.emit(f"Permission {action}: {perm} — {r.stdout.strip() or 'OK'}")
        self.operation_done.emit("permissions_changed")

    def _backup_app(self, pkg, save_dir):
        self.backup_progress.emit(pkg, "Fetching APK paths")
        r = self._adb("shell", f"pm path {pkg}")
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
                ex.map(lambda p: self._adb("pull", p, tmp), paths)
            zp = os.path.join(save_dir, f"backup_{pkg}.zip")
            shutil.make_archive(zp.replace(".zip", ""), "zip", tmp)
            self.log_message.emit(f"Backup: {zp}")

    def _restore_apps(self, files):
        if not files:
            return
        for i, zp in enumerate(files):
            if self._aborted or self.isInterruptionRequested():
                return
            app = os.path.basename(zp).replace("backup_", "").replace(".zip", "")
            try:
                with tempfile.TemporaryDirectory(prefix=f"rs_{app}_") as tmp:
                    with zipfile.ZipFile(zp, "r") as zf:
                        safe_extract_zip(zf, tmp)
                    apks = [
                        os.path.join(r, f) for r, _, fs in os.walk(tmp)
                        for f in fs if f.endswith(".apk")
                    ]
                    if not apks:
                        continue
                    is_split = len(apks) > 1 and any("base.apk" in a.lower() for a in apks)
                    if is_split:
                        self._adb("install-multiple", "-r", *apks, timeout=120)
                    else:
                        for a in apks:
                            self._adb("install", "-r", a, timeout=120)
                self.log_message.emit(f"Restored ({i+1}/{len(files)}): {os.path.basename(zp)}")
            except Exception as e:
                self.log_message.emit(f"Error: {e}")
        self.operation_done.emit("restore")
