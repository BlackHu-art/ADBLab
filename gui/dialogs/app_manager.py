"""应用管理器对话框 — 列出、筛选、管理、备份/恢复设备上的应用。"""

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from gui.styles.base_styles import BaseStyles
from gui.styles.theme import apply_dark_title_bar
from utils.adb_resolver import CF
from gui.styles.icon_loader import get_themed_icon

# ── 后台工作线程 ──────────────────────────────────────────────────────────


class AppManagerWorker(QThread):
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
        return subprocess.run(
            cmd, capture_output=True, text=True, creationflags=CF, timeout=timeout,
        )

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
        """Fetch app labels and versions for a batch of packages."""
        total = len(packages)
        for i, pkg in enumerate(packages):
            try:
                r = self._adb("shell", f"dumpsys package {pkg}", timeout=5)
                out = r.stdout
                # Parse app label (nonLocalizedLabel = real app name)
                m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", out)
                label = m_label.group(1).strip() if m_label else ""
                # Parse version
                m_vn = re.search(r"versionName=([\S]+)", out)
                m_vc = re.search(r"versionCode=(\d+)", out)
                vn = m_vn.group(1) if m_vn else ""
                vc = m_vc.group(1) if m_vc else ""
                # Parse install time
                m_it = re.search(r"firstInstallTime=(\d{4}-\d{2}-\d{2})", out)
                itime = m_it.group(1) if m_it else ""
                self.app_detail_batch.emit(
                    pkg, label or pkg.split(".")[-1], f"{vn} ({vc})" if vn else "", itime
                )
            except Exception:
                self.app_detail_batch.emit(pkg, "", "", "")
            if i % 10 == 0:
                self.log_message.emit(f"Details: {i+1}/{total}")

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
        self.app_details_loaded.emit(
            {
                "App Name": label,
                "Package": pkg,
                "Path": m_cp.group(1) if m_cp else "?",
                "Version": f"{m_vn.group(1) if m_vn else '?'} (code {m_vc.group(1) if m_vc else '?'})",
                "Min SDK": m_ms.group(1) if m_ms else "?",
                "Target SDK": m_ts.group(1) if m_ts else "?",
            }
        )

    def _fetch_permissions(self, pkg):
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
        cmds = {
            "disable": ["shell", "pm", "disable-user", "--user", "0", pkg],
            "enable": ["shell", "pm", "enable", pkg],
            "uninstall": ["uninstall", "--user", "0", pkg],
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
            app = os.path.basename(zp).replace("backup_", "").replace(".zip", "")
            try:
                with tempfile.TemporaryDirectory(prefix=f"rs_{app}_") as tmp:
                    with zipfile.ZipFile(zp, "r") as zf:
                        zf.extractall(tmp)
                    apks = [
                        os.path.join(r, f)
                        for r, _, fs in os.walk(tmp)
                        for f in fs
                        if f.endswith(".apk")
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


# ── 排序代理模型 ──────────────────────────────────────────────────────────


class AppSortProxy(QSortFilterProxyModel):
    STATUS_ORDER = {"Enabled": 0, "Disabled": 1}
    TYPE_ORDER = {"User": 0, "System": 1, "Vendor": 2, "Other": 3}

    def lessThan(self, left, right):
        col = left.column()
        ld = self.sourceModel().data(left)
        rd = self.sourceModel().data(right)
        if col == 2 and ld in self.STATUS_ORDER:
            return self.STATUS_ORDER[ld] < self.STATUS_ORDER[rd]
        if col == 3 and ld in self.TYPE_ORDER:
            return self.TYPE_ORDER[ld] < self.TYPE_ORDER[rd]
        return super().lessThan(left, right)


# ── 应用详情对话框 ─────────────────────────────────────────────────────────


class AppDetailsDialog(QDialog):
    def __init__(self, parent, device_ip: str, package_name: str):
        super().__init__(parent)
        self.device_ip = device_ip
        self.package_name = package_name
        self._workers = []
        self.setWindowTitle(f"Details: {package_name}")
        self.setWindowIcon(get_themed_icon("info.svg"))
        self.setMinimumSize(750, 560)
        self.setModal(False)
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont("Consolas", 9))
        dl.addWidget(self.detail_text)
        self.tabs.addTab(dw, "App Details")

        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.declared_list = self._ps(pl, "Declared Permissions (Read-Only)")
        self.requested_list = self._ps(pl, "Requested Permissions")
        self.runtime_list = self._ps(pl, "Runtime Permissions (Grant/Revoke)")
        pb = QHBoxLayout()
        self.grant_btn = QPushButton("Grant Selected")
        self.grant_btn.setIcon(get_themed_icon("check-circle.svg"))
        self.grant_btn.setIconSize(QSize(14, 14))
        self.revoke_btn = QPushButton("Revoke Selected")
        self.revoke_btn.setIcon(get_themed_icon("x-circle.svg"))
        self.revoke_btn.setIconSize(QSize(14, 14))
        self.grant_btn.clicked.connect(lambda: self._mp("grant"))
        self.revoke_btn.clicked.connect(lambda: self._mp("revoke"))
        pb.addWidget(self.grant_btn)
        pb.addWidget(self.revoke_btn)
        pl.addLayout(pb)
        self.tabs.addTab(pw, "Permissions")
        layout.addWidget(self.tabs)
        close_btn = QPushButton("Close")
        close_btn.setIcon(get_themed_icon("x.svg"))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _ps(self, parent, title):
        hl = QHBoxLayout()
        hl.addWidget(QLabel(title))
        sb = QPushButton("Select All/None")
        sb.setIcon(get_themed_icon("check-square.svg"))
        sb.setIconSize(QSize(14, 14))
        sb.setFixedSize(130, 28)
        hl.addWidget(sb)
        parent.addLayout(hl)
        lw = QListWidget()
        lw.setMinimumHeight(100)
        lw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        parent.addWidget(lw)
        sb.clicked.connect(lambda: self._ta(lw))
        return lw

    @staticmethod
    def _ta(lw):
        any_u = any(lw.item(i).checkState() != Qt.CheckState.Checked for i in range(lw.count()))
        st = Qt.CheckState.Checked if any_u else Qt.CheckState.Unchecked
        for i in range(lw.count()):
            lw.item(i).setCheckState(st)

    def _load_data(self):
        self._rw("app_details", package_name=self.package_name, app_details_loaded=self._od)
        self._rp()

    def _rp(self):
        self._rw("permissions", package_name=self.package_name, permissions_loaded=self._op)

    def _od(self, d):
        self.detail_text.clear()
        for k, v in d.items():
            self.detail_text.append(f"<b>{k}:</b> {v}")

    def _op(self, declared, requested, runtime):
        def fill(lw, items, fmt=lambda x: x):
            lw.clear()
            for item in items:
                i = QListWidgetItem(fmt(item))
                i.setFlags(i.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                i.setCheckState(Qt.CheckState.Unchecked)
                lw.addItem(i)

        fill(self.declared_list, declared)
        fill(self.requested_list, requested)
        fill(self.runtime_list, runtime, lambda r: f"{r[0]} (Granted: {r[1]})")

    def _mp(self, action):
        rc = [
            self.runtime_list.item(i).text().split(" (")[0]
            for i in range(self.runtime_list.count())
            if self.runtime_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        rq = [
            self.requested_list.item(i).text()
            for i in range(self.requested_list.count())
            if self.requested_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        sel = rc + rq
        if not sel:
            QMessageBox.warning(self, "No Selection", f"No permissions selected to {action}.")
            return
        for perm in sel:
            self._rw(
                "modify_permission",
                package_name=self.package_name,
                permission=perm,
                action=action,
                operation_done=lambda _: self._rp(),
            )

    def _rw(self, op, **kw):
        w = AppManagerWorker(self.device_ip, op, **kw)
        w.setParent(self)
        for s in ["log_message", "app_details_loaded", "permissions_loaded", "operation_done"]:
            if s in kw:
                getattr(w, s).connect(kw[s])
        if hasattr(self.parent(), "log"):
            w.log_message.connect(self.parent().log)
        self._workers.append(w)
        w.start()

    def closeEvent(self, event):
        import threading
        workers = self._workers
        self._workers = []
        for w in workers:
            w.abort()
            w.setParent(None)
        # Background waiter keeps Python refs alive until threads finish
        threading.Thread(
            target=lambda ws=workers: [w.wait(5000) for w in ws],
            daemon=True,
        ).start()
        super().closeEvent(event)


# ── 主应用管理器对话框 ────────────────────────────────────────────────────


class AppManagerDialog(QDialog):
    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self.selected_packages = set()
        self._workers = []
        self._apps_data = []
        self.setWindowTitle(f"App Manager - {device_ip}")
        self.setWindowIcon(get_themed_icon("squares-four.svg"))
        self.setMinimumSize(960, 600)
        self.resize(1000, 660)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._load_apps()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 6)

        # Search + filter + view toggle
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter...")
        self.search_input.textChanged.connect(self._filter)
        top.addWidget(self.search_input, 1)
        top.addWidget(QLabel("Type:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems(["All", "User Apps", "System Apps"])
        self.type_filter.currentIndexChanged.connect(self._filter)
        top.addWidget(self.type_filter)
        self.view_toggle = QPushButton()
        self.view_toggle.setFixedSize(28, 28)
        self.view_toggle.setToolTip("Toggle Icon / List view")
        self.view_toggle.clicked.connect(self._toggle_view)
        self.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self.view_toggle.setIconSize(QSize(16, 16))
        top.addWidget(self.view_toggle)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self.refresh_btn.setIconSize(QSize(14, 14))
        self.refresh_btn.clicked.connect(self._load_apps)
        self.refresh_btn.setFixedHeight(28)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        # Stacked: table view + icon view
        self.stack = QStackedWidget()

        # --- Table view ---
        self.model = QStandardItemModel(0, 6)
        self.model.setHorizontalHeaderLabels(
            ["", "App Name", "Package Name", "Version", "Status", "Type"]
        )
        self.proxy = AppSortProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setSortingEnabled(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.clicked.connect(self._on_row_clicked)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for i in range(1, 6):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 40)
        self.tree.setColumnWidth(1, 160)
        self.tree.setColumnWidth(2, 320)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 70)
        self.tree.setColumnWidth(5, 60)
        self.stack.addWidget(self.tree)

        # --- Icon view ---
        self.icon_list = QListWidget()
        self.icon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.icon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.icon_list.setIconSize(QSize(48, 48))
        self.icon_list.setSpacing(4)
        self.icon_list.setGridSize(QSize(110, 80))
        self.icon_list.setWordWrap(True)
        self.icon_list.setMovement(QListWidget.Movement.Static)
        self.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_list.customContextMenuRequested.connect(self._icon_context_menu)
        self.icon_list.itemDoubleClicked.connect(self._icon_double_click)
        self.icon_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.stack.addWidget(self.icon_list)

        self._view_mode = False  # False = table, True = icon
        layout.addWidget(self.stack, 1)

        # Action buttons — uniform size
        btn_h = 30
        a1 = QHBoxLayout()
        a1.setSpacing(4)
        labels_actions = [
            ("Uninstall Selected", "uninstall", "trash.svg"),
            ("Disable Selected", "disable", "prohibit.svg"),
            ("Enable Selected", "enable", "check-circle.svg"),
            ("Deselect All", None, "square.svg"),
        ]
        for t, a, icon in labels_actions:
            b = QPushButton(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setFixedHeight(btn_h)
            if a:
                b.clicked.connect(lambda _, act=a: self._modify_selected(act))
            else:
                b.clicked.connect(self._deselect_all)
            a1.addWidget(b, 1)
        layout.addLayout(a1)

        a2 = QHBoxLayout()
        a2.setSpacing(4)
        for t, fn, icon in [
            ("Create Preset", self._create_preset, "floppy-disk.svg"),
            ("Load Preset", self._load_preset, "folder-open.svg"),
            ("Backup Selected", self._backup_selected, "archive.svg"),
            ("Restore Backup", self._restore_apps, "cloud-arrow-down.svg"),
            ("App Details", self._show_details, "info.svg"),
        ]:
            b = QPushButton(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setFixedHeight(btn_h)
            b.clicked.connect(fn)
            a2.addWidget(b, 1)
        layout.addLayout(a2)

        # Log (no label)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setPlaceholderText("Operation log...")
        layout.addWidget(self.log_output)

        # Status
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)

    def _apply_theme(self, _name=""):
        apply_dark_title_bar(self)
        bs = BaseStyles
        self.setStyleSheet(bs.PANEL_BASE_STYLE())
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        self.log_output.setStyleSheet(
            f"background-color:{bs.color('LOG_BACKGROUND')}; color:{bs.color('LOG_TEXT_COLOR')}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px;"
        )
        self.tree.setStyleSheet(
            f"QTreeView {{ background-color:{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; alternate-background-color:{bs.color('INPUT_BG_HOVER')}; }} QTreeView::item:selected {{ background-color:{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; }} QHeaderView::section {{ background-color:{bs.color('BUTTON_BG')}; color:{fg}; padding:4px; border:1px solid {border}; }}"
        )
        self.icon_list.setStyleSheet(
            f"QListWidget {{ background-color:{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; }} QListWidget::item:selected {{ background-color:{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; border-radius:4px; }}"
        )
        self.status_bar.setStyleSheet(
            f"QStatusBar {{ color:{fg}; border-top:1px solid {border}; }}"
        )

    def log(self, msg):
        self.log_output.append(msg)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    # ── 加载 / 筛选 ────────────────────────────────────────────────────────

    def _load_apps(self):
        self.model.removeRows(0, self.model.rowCount())
        self.selected_packages.clear()
        w = AppManagerWorker(self.device_ip, "load_apps")
        w.log_message.connect(self.log)
        w.apps_loaded.connect(self._populate)
        self._track_worker(w)
        w.start()

    def _populate(self, apps):
        self._apps_data = apps
        self._app_labels = {}
        self._app_versions = {}
        # Table view (no icons in list)
        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        for name, pkg, st, at in apps:
            cb = QStandardItem()
            cb.setCheckable(True)
            self.model.appendRow(
                [
                    cb,
                    QStandardItem(name),
                    QStandardItem(pkg),
                    QStandardItem(""),
                    QStandardItem(st),
                    QStandardItem(at),
                ]
            )
        self.tree.setSortingEnabled(True)
        # Icon view
        self.icon_list.clear()
        sorted_apps = sorted(apps, key=lambda x: (0 if x[3] == "User" else 1, x[0].lower()))
        for name, pkg, st, at in sorted_apps:
            short_name = name[:18] + (".." if len(name) > 18 else "")
            icon = self._gen_icon(name, at, 48)
            item = QListWidgetItem(icon, short_name)
            item.setData(Qt.UserRole, pkg)
            item.setToolTip(f"{pkg}\nType: {at} | Status: {st}")
            item.setSizeHint(QSize(106, 72))
            if st == "Disabled":
                item.setForeground(QColor("#999999"))
            self.icon_list.addItem(item)
        self._filter()
        self.status_bar.showMessage(f"Loaded {len(apps)} apps — loading details...")
        # Background detail loading
        pkgs = [a[1] for a in apps]
        w = AppManagerWorker(self.device_ip, "load_detail_batch", packages=pkgs)
        w.app_detail_batch.connect(self._on_detail)
        w.log_message.connect(self.log)
        self._track_worker(w)
        w.start()

    def _on_detail(self, pkg, label, version, itime):
        self._app_labels[pkg] = label
        self._app_versions[pkg] = version
        for i in range(self.icon_list.count()):
            item = self.icon_list.item(i)
            if item.data(Qt.UserRole) == pkg:
                item.setToolTip(f"{label}\n{pkg}\n{version}")
                break
        for r in range(self.model.rowCount()):
            if self.model.item(r, 2).text() == pkg:
                if label:
                    self.model.item(r, 1).setText(label)
                if version:
                    self.model.item(r, 3).setText(version)
                break

    @staticmethod
    def _gen_icon(name, atype, size=48):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {"User": "#4CAF50", "System": "#F44336", "Vendor": "#FF9800", "Other": "#9E9E9E"}
        c = QColor(colors.get(atype, "#9E9E9E"))
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        margin = size // 12
        rsize = size - margin * 2
        radius = size // 5
        p.drawRoundedRect(margin, margin, rsize, rsize, radius, radius)
        p.setPen(QColor("#ffffff"))
        abbreviation = name[:2].upper() if len(name) >= 2 else name.upper()
        font = QFont("Segoe UI", size // 3 + 1, QFont.Bold)
        p.setFont(font)
        p.drawText(margin, margin, rsize, rsize, Qt.AlignmentFlag.AlignCenter, abbreviation)
        p.end()
        return QIcon(pix)

    def _toggle_view(self):
        self._view_mode = not self._view_mode
        self.stack.setCurrentIndex(1 if self._view_mode else 0)
        self.view_toggle.setIcon(
            get_themed_icon(
                "list-bullets.svg"
                if self._view_mode
                else "squares-four.svg"
            )
        )
        self.view_toggle.setToolTip(
            "Switch to List view" if self._view_mode else "Switch to Icon view"
        )

    def _icon_context_menu(self, pos):
        item = self.icon_list.itemAt(pos)
        if not item:
            return
        pkg = item.data(Qt.UserRole)
        if not pkg:
            return
        self._icon_selected_pkg = pkg
        menu = QMenu()
        menu.addAction("App Details", lambda: self._show_details_for(pkg))
        menu.addSeparator()
        menu.addAction("Launch App", lambda: self._launch(pkg))
        menu.addAction("Force Stop", lambda: self._modify_one("force_stop", pkg))
        menu.addAction("Clear Data", lambda: self._modify_one("clear", pkg))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self._modify_one("uninstall", pkg))
        menu.addAction("Disable", lambda: self._modify_one("disable", pkg))
        menu.addAction("Enable", lambda: self._modify_one("enable", pkg))
        menu.addSeparator()
        menu.addAction("Backup", lambda: self._backup_one(pkg))
        menu.exec(self.icon_list.mapToGlobal(pos))

    def _icon_double_click(self, item):
        pkg = item.data(Qt.UserRole)
        if pkg:
            self._show_details_for(pkg)

    def _filter(self):
        text = self.search_input.text().strip().lower()
        ft = self.type_filter.currentText()
        if ft == "User Apps":
            self.proxy.setFilterFixedString("User")
            self.proxy.setFilterKeyColumn(5)
            if text:
                self.proxy.setFilterRegularExpression(f"(?=.*{re.escape(text)})(?=.*User)")
        elif ft == "System Apps":
            self.proxy.setFilterFixedString("System")
            self.proxy.setFilterKeyColumn(5)
            if text:
                self.proxy.setFilterRegularExpression(f"(?=.*{re.escape(text)})(?=.*System)")
        else:
            if text:
                self.proxy.setFilterRegularExpression(text)
            else:
                self.proxy.setFilterRegularExpression("")
            self.proxy.setFilterKeyColumn(-1)
        # Also filter icon view
        for i in range(self.icon_list.count()):
            item = self.icon_list.item(i)
            pkg = (item.data(Qt.UserRole) or "").lower()
            name = (item.text().split("\n")[0] or "").lower()
            type_match = (
                ft == "All"
                or (ft == "User Apps" and "User" in (item.toolTip() or ""))
                or (ft == "System Apps" and "System" in (item.toolTip() or ""))
            )
            text_match = not text or text in name or text in pkg
            item.setHidden(not (type_match and text_match))

    # ── 点击 / 右键菜单 ────────────────────────────────────────────────────

    def _on_row_clicked(self, index):
        src = self.proxy.mapToSource(index)
        row = src.row()
        if row < 0:
            return
        cb = self.model.item(row, 0)
        pkg = self.model.item(row, 2).text()
        if index.column() > 0:
            ns = (
                Qt.CheckState.Unchecked
                if cb.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            cb.setCheckState(ns)
        (
            self.selected_packages.add(pkg)
            if cb.checkState() == Qt.CheckState.Checked
            else self.selected_packages.discard(pkg)
        )

    def _context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        src = self.proxy.mapToSource(idx)
        row = src.row()
        pkg = self.model.item(row, 2).text()
        atype = self.model.item(row, 5).text()
        menu = QMenu()
        menu.addAction("App Details", lambda: self._show_details_for(pkg))
        menu.addSeparator()
        menu.addAction("Launch App", lambda: self._launch(pkg))
        menu.addAction("Force Stop", lambda: self._modify_one("force_stop", pkg))
        menu.addAction("Clear Data", lambda: self._modify_one("clear", pkg))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self._modify_one("uninstall", pkg))
        if atype in ("System", "Vendor"):
            menu.addAction("Disable", lambda: self._modify_one("disable", pkg))
            menu.addAction("Enable", lambda: self._modify_one("enable", pkg))
        menu.addSeparator()
        menu.addAction("Backup", lambda: self._backup_one(pkg))
        menu.exec(self.tree.mapToGlobal(pos))

    def _show_details_for(self, pkg):
        dlg = AppDetailsDialog(self, self.device_ip, pkg)
        dlg.show()

    def _launch(self, pkg):
        w = AppManagerWorker(self.device_ip, "launch_app", package_name=pkg)
        w.log_message.connect(self.log)
        self._track_worker(w)
        w.start()

    def _modify_one(self, action, pkg):
        if action == "force_stop":
            w = AppManagerWorker(self.device_ip, "modify_app", action="disable", package_name=pkg)
            w.log_message.connect(self.log)
            self._track_worker(w)
            w.start()
            # Actually force-stop
            subprocess.run(
                ["adb", "-s", self.device_ip, "shell", "am", "force-stop", pkg],
                capture_output=True,
                text=True,
                creationflags=CF,
            )
            self.log(f"Force stopped: {pkg}")
        elif action == "clear":
            w = AppManagerWorker(self.device_ip, "clear_app", package_name=pkg)
            w.log_message.connect(self.log)
            self._track_worker(w)
            w.start()
        else:
            w = AppManagerWorker(self.device_ip, "modify_app", action=action, package_name=pkg)
            w.log_message.connect(self.log)
            w.operation_done.connect(lambda _: self._load_apps())
            self._track_worker(w)
            w.start()

    def _backup_one(self, pkg):
        sd = QFileDialog.getExistingDirectory(self, "Select Backup Directory")
        if not sd:
            return
        w = AppManagerWorker(self.device_ip, "backup_app", package_name=pkg, save_dir=sd)
        w.log_message.connect(self.log)
        w.backup_progress.connect(lambda p, m: self.log(f"[{p}] {m}"))
        self._track_worker(w)
        w.start()

    def _deselect_all(self):
        for r in range(self.model.rowCount()):
            self.model.item(r, 0).setCheckState(Qt.CheckState.Unchecked)
        self.icon_list.clearSelection()
        self.selected_packages.clear()
        self.log("Deselected all.")

    # ── 批量操作 ───────────────────────────────────────────────────────────

    def _get_selected_pkgs(self):
        if self._view_mode:
            return [
                it.data(Qt.UserRole)
                for it in self.icon_list.selectedItems()
                if it.data(Qt.UserRole)
            ]
        return list(self.selected_packages)

    def _modify_selected(self, action):
        pkgs = self._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(self, "None", "No apps selected.")
            return
        for pkg in pkgs:
            w = AppManagerWorker(self.device_ip, "modify_app", action=action, package_name=pkg)
            w.log_message.connect(self.log)
            self._track_worker(w)
            w.start()
        self._load_apps()

    def _backup_selected(self):
        pkgs = self._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(self, "None", "No apps selected.")
            return
        sd = QFileDialog.getExistingDirectory(self, "Backup Directory")
        if not sd:
            return
        for pkg in pkgs:
            w = AppManagerWorker(self.device_ip, "backup_app", package_name=pkg, save_dir=sd)
            w.log_message.connect(self.log)
            w.backup_progress.connect(lambda p, m: self.log(f"[{p}] {m}"))
            self._track_worker(w)
            w.start()

    def _restore_apps(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Backup ZIP(s)", "", "ZIP Files (*.zip)"
        )
        if not files:
            return
        w = AppManagerWorker(self.device_ip, "restore_apps", file_paths=files)
        w.log_message.connect(self.log)
        w.backup_progress.connect(lambda p, m: self.log(f"[{p}] {m}"))
        w.operation_done.connect(lambda _: self._load_apps())
        self._track_worker(w)
        w.start()

    def _show_details(self):
        if self._view_mode:
            items = self.icon_list.selectedItems()
            if not items:
                QMessageBox.warning(self, "None", "No app selected.")
                return
            pkg = items[0].data(Qt.UserRole)
        else:
            idxs = self.tree.selectedIndexes()
            if not idxs:
                QMessageBox.warning(self, "None", "No app selected.")
                return
            src = self.proxy.mapToSource(idxs[0])
            pkg = self.model.item(src.row(), 2).text()
        if pkg:
            AppDetailsDialog(self, self.device_ip, pkg).show()

    # ── 预设操作 ───────────────────────────────────────────────────────────

    def _create_preset(self):
        if not self.selected_packages:
            QMessageBox.warning(self, "None", "Select apps first.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Create Preset")
        dlg.setFixedSize(380, 280)
        lo = QVBoxLayout(dlg)
        lo.addWidget(QLabel("Preset Name:"))
        ni = QLineEdit()
        lo.addWidget(ni)
        lo.addWidget(QLabel("Author (optional):"))
        ai = QLineEdit()
        lo.addWidget(ai)
        lo.addWidget(QLabel("Description (optional):"))
        di = QTextEdit()
        di.setMaximumHeight(60)
        lo.addWidget(di)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lo.addWidget(btns)
        if not dlg.exec():
            return
        name = ni.text().strip() or "New Preset"
        data = {
            "name": name,
            "author": ai.text().strip(),
            "description": di.toPlainText().strip(),
            "selected_packages": sorted(list(self.selected_packages)),
        }
        fp, _ = QFileDialog.getSaveFileName(self, "Save Preset", name + ".json", "JSON (*.json)")
        if fp:
            with open(fp, "w") as f:
                json.dump(data, f, indent=4)
            self.log(f"Preset '{name}' saved ({len(data['selected_packages'])} apps).")

    def _load_preset(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Load Preset", "", "JSON (*.json)")
        if not fp:
            return
        with open(fp) as f:
            data = json.load(f)
        pkgs = set(data.get("selected_packages", []))
        if not pkgs:
            self.log("Preset empty.")
            return
        self._deselect_all()
        for r in range(self.model.rowCount()):
            p = self.model.item(r, 2).text()
            if p in pkgs:
                self.model.item(r, 0).setCheckState(Qt.CheckState.Checked)
                self.selected_packages.add(p)
        self.log(f"Loaded preset '{data.get('name','?')}' ({len(self.selected_packages)} apps).")

    # ── 应用生命周期操作 ───────────────────────────────────────────────────

    def _track_worker(self, w):
        w.setParent(self)
        self._workers.append(w)

    def closeEvent(self, event):
        import threading
        workers = self._workers
        self._workers = []
        for w in workers:
            w.abort()
            w.setParent(None)
        # Background waiter keeps Python refs alive until threads finish
        threading.Thread(
            target=lambda ws=workers: [w.wait(5000) for w in ws],
            daemon=True,
        ).start()
        super().closeEvent(event)
