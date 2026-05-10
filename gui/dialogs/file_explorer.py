"""
File Explorer dialog - browse, pull, push, edit, and manage files on a device.

Adapted to use ADBLab's BaseStyles theme system.
"""

import base64
import os
import re
import subprocess
import sys
import tempfile

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# ── Worker Threads ───────────────────────────────────────────────────────


class ADBWorker(QThread):
    """Run a simple adb shell command and return output."""

    finished = Signal(str, bool)

    def __init__(self, device_ip: str, args: list):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()

    def run(self):
        try:
            cmd = ["adb", "-s", self.device_ip] + self.args
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            output = subprocess.check_output(
                cmd, text=True, stderr=subprocess.STDOUT, creationflags=cf, timeout=30,
            )
            if not self._aborted:
                self.finished.emit(output, False)
        except subprocess.CalledProcessError as e:
            if not self._aborted:
                self.finished.emit(e.output or str(e), True)
        except Exception as e:
            if not self._aborted:
                self.finished.emit(str(e), True)


class TransferWorker(QThread):
    """Run pull/push operations with progress lines."""

    progress = Signal(str)
    finished = Signal(str, bool, str)

    def __init__(self, device_ip: str, args: list, cwd: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.args = args
        self.cwd = cwd or os.getcwd()
        self._proc = None
        self._aborted = False

    def abort(self):
        self._aborted = True
        self.requestInterruption()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        try:
            cmd = ["adb", "-s", self.device_ip] + self.args
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                universal_newlines=True,
                bufsize=1,
                creationflags=cf,
            )
            last = ""
            while not self._aborted:
                line = self._proc.stdout.readline()
                if not line and self._proc.poll() is not None:
                    break
                if line:
                    last = line.rstrip("\n")
                    self.progress.emit(last)
            if self._aborted:
                return
            ret = self._proc.wait()
            local = self.args[-1] if len(self.args) >= 2 else ""
            if ret == 0:
                self.finished.emit(last or "OK", False, local)
            else:
                self.finished.emit(last or f"Exit {ret}", True, local)
        except Exception as e:
            self.finished.emit(str(e), True, "")


# ── File Explorer Dialog ─────────────────────────────────────────────────


class FileExplorerDialog(QDialog):

    TEXT_EXTS = {
        "txt",
        "log",
        "json",
        "xml",
        "html",
        "csv",
        "md",
        "ini",
        "conf",
        "prop",
        "sh",
        "bat",
        "py",
        "js",
        "css",
        "cpp",
        "h",
        "hpp",
        "c",
        "rc",
        "",
    }
    IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp"}

    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self.current_path = "/storage/emulated/0"
        self.history = []
        self.forward_stack = []
        self.clipboard = []
        self.copy_mode = False
        self.symlink_targets = {}
        self._workers = []
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.setWindowTitle(f"File Explorer - {device_ip}")
        self.setMinimumSize(950, 620)
        self.resize(1000, 650)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        self._refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # Path bar
        self.path_layout = QHBoxLayout()
        self.path_layout.setSpacing(4)
        self.path_layout.addWidget(QLabel("Path:"))
        self.path_field = QLineEdit(self.current_path)
        self.path_field.returnPressed.connect(
            lambda: self._navigate(self.path_field.text().strip())
        )
        self.path_field.setFont(QFont("Consolas", 9))
        self.path_layout.addWidget(self.path_field, 1)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search...")
        self.search_field.textChanged.connect(self._filter)
        self.path_layout.addWidget(self.search_field)
        layout.addLayout(self.path_layout)

        # Toolbar row
        tb = QHBoxLayout()
        tb.setSpacing(3)
        self.back_btn = QPushButton("<")
        self.back_btn.setToolTip("Back")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        self.fwd_btn = QPushButton(">")
        self.fwd_btn.setToolTip("Forward")
        self.fwd_btn.clicked.connect(self._go_forward)
        self.fwd_btn.setEnabled(False)
        self.up_btn = QPushButton("..")
        self.up_btn.setToolTip("Parent")
        self.up_btn.clicked.connect(self._go_parent)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh)
        self.mkdir_btn = QPushButton("New Folder")
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.touch_btn = QPushButton("New File")
        self.touch_btn.clicked.connect(self._touch)
        self.pull_btn = QPushButton("Pull")
        self.pull_btn.clicked.connect(self._pull_selected)
        self.push_btn = QPushButton("Push")
        self.push_btn.clicked.connect(self._push_file)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_selected)
        for b in (
            self.back_btn,
            self.fwd_btn,
            self.up_btn,
            self.refresh_btn,
            self.mkdir_btn,
            self.touch_btn,
            self.pull_btn,
            self.push_btn,
            self.delete_btn,
        ):
            b.setFont(QFont("Segoe UI", 9))
            tb.addWidget(b)
        tb.addStretch()
        self.root_cb = QCheckBox("Root")
        self.root_cb.setToolTip("Use root access (su)")
        tb.addWidget(self.root_cb)
        layout.addLayout(tb)

        # File table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Modified"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.Interactive
            )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 120)
        layout.addWidget(self.table, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_theme(self, _name: str = ""):
        from gui.styles.base_styles import BaseStyles

        bs = BaseStyles
        self.setStyleSheet(bs.PANEL_BASE_STYLE())
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        sel_bg = bs.color("SELECTION_BG")
        sel_fg = bs.color("SELECTION_TEXT")
        btn_bg = bs.color("BUTTON_BG")
        self.table.setStyleSheet(f"""
            QTableWidget {{ background-color: {bg}; color: {fg};
                border: 1px solid {border}; border-radius: {bs.RADIUS_MD}px;
                gridline-color: {border}; }}
            QTableWidget::item:selected {{ background-color: {sel_bg}; color: {sel_fg}; }}
            QHeaderView::section {{ background-color: {btn_bg}; color: {fg};
                padding: 4px; border: 1px solid {border}; }}
        """)
        self.status_bar.setStyleSheet(
            f"QStatusBar {{ color: {fg}; border-top: 1px solid {border}; }}"
        )
        self.path_field.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: {bs.RADIUS_SM}px; padding: 2px 4px;"
        )
        self.search_field.setStyleSheet(self.path_field.styleSheet())

        from gui.styles.base_styles import BaseStyles as BS

        BS.theme_changed.connect(self._apply_theme)

    # ── ADB helpers ──────────────────────────────────────────────────────

    def _root(self, cmd: str) -> str:
        return f'su -c "{cmd}"' if self.root_cb.isChecked() else cmd

    def _dpath(self, *parts) -> str:
        return os.path.join(*parts).replace("\\", "/")

    def _run_adb(self, *args):
        worker = ADBWorker(self.device_ip, list(args))
        self._workers.append(worker)
        worker.setParent(self)
        return worker

    def _run_transfer(self, *args):
        worker = TransferWorker(self.device_ip, list(args))
        self._workers.append(worker)
        worker.setParent(self)
        return worker

    # ── Navigation ───────────────────────────────────────────────────────

    def _navigate(self, path: str, push: bool = True):
        if not path or path == self.current_path:
            return
        if push:
            self.history.append(self.current_path)
            self.forward_stack.clear()
            self.fwd_btn.setEnabled(False)
        self.current_path = path
        self.path_field.setText(path)
        self.back_btn.setEnabled(bool(self.history))
        self._refresh()

    def _go_back(self):
        if not self.history:
            return
        self.forward_stack.append(self.current_path)
        self.fwd_btn.setEnabled(True)
        self._navigate(self.history.pop(), push=False)

    def _go_forward(self):
        if not self.forward_stack:
            return
        self.history.append(self.current_path)
        self.back_btn.setEnabled(True)
        self._navigate(self.forward_stack.pop(), push=False)

    def _go_parent(self):
        self._navigate(os.path.dirname(self.current_path))

    # ── Directory listing ────────────────────────────────────────────────

    def _refresh(self):
        self.search_field.clear()
        self.status_bar.showMessage("Loading...")
        self.table.setRowCount(0)
        self.symlink_targets.clear()

        cmd = f'ls -la "{self.current_path}" 2>&1'
        shell_cmd = self._root(cmd)
        worker = self._run_adb("shell", shell_cmd)
        worker.finished.connect(self._on_ls_result)
        worker.start()

    def _on_ls_result(self, output, error):
        if error and not output.strip():
            self.status_bar.showMessage("Error loading directory")
            return
        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)
        rows = []
        for line in output.splitlines():
            if not line.strip() or line.startswith("total"):
                continue
            if "Permission denied" in line or line.startswith("ls:"):
                continue
            entry = self._parse_ls(line)
            if not entry:
                continue
            name_part = entry["name"]
            is_symlink = "->" in name_part
            if is_symlink:
                name, target = name_part.split("->", 1)
                name = name.strip()
                self.symlink_targets[name] = target.strip()
            else:
                name = name_part
            if not name or name in (".", ".."):
                continue
            is_dir = entry["perms"].startswith(("d", "l"))
            ftype = "Folder" if is_dir else self._ext(name)
            size_str = "-" if is_dir else self._fmt_size(entry["size"])
            rows.append(
                (name, ftype, size_str, entry["modified"], self._safe_int(entry["size"]), is_dir)
            )

        rows.sort(key=lambda x: (not x[5], x[0].lower()))
        for name, ftype, size_str, date_str, _, is_dir in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(ftype))
            self.table.setItem(r, 2, QTableWidgetItem(size_str))
            self.table.setItem(r, 3, QTableWidgetItem(date_str))

        # Insert ".." row at top
        if self.current_path != "/":
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem(".."))
            self.table.setItem(0, 1, QTableWidgetItem("Folder"))
            self.table.setItem(0, 2, QTableWidgetItem("-"))
            self.table.setItem(0, 3, QTableWidgetItem("-"))

        self.table.setSortingEnabled(True)
        folders = sum(1 for r in rows if r[5])
        files = len(rows) - folders
        self.status_bar.showMessage(f"{self.current_path}  |  {folders} folders, {files} files")

    def _parse_ls(self, line: str) -> dict | None:
        parts = line.strip().split(maxsplit=7)
        if len(parts) < 8:
            return None
        return {
            "perms": parts[0],
            "owner": parts[2],
            "group": parts[3],
            "size": parts[4],
            "modified": f"{parts[5]} {parts[6]}",
            "name": parts[7],
        }

    def _ext(self, name: str) -> str:
        return name.rsplit(".", 1)[-1].upper() if "." in name else "File"

    def _safe_int(self, s: str) -> int:
        try:
            return int(s.replace(",", ""))
        except (ValueError, AttributeError):
            return 0

    def _fmt_size(self, s: str) -> str:
        try:
            size = int(s)
            for u in ["B", "KB", "MB", "GB"]:
                if size < 1024:
                    return f"{size:.1f} {u}"
                size /= 1024
            return f"{size:.1f} TB"
        except ValueError:
            return "-"

    # ── Double click ─────────────────────────────────────────────────────

    def _on_double_click(self, row, col):
        name = self.table.item(row, 0).text()
        ftype = self.table.item(row, 1).text()
        if name == "..":
            self._go_parent()
        elif ftype == "Folder":
            target = self.symlink_targets.get(name)
            new_path = (
                target
                if target and target.startswith("/")
                else self._dpath(self.current_path, name)
            )
            self._navigate(new_path)
        else:
            self._view_or_pull(name)

    def _view_or_pull(self, name: str):
        menu = QMenu()
        pull = menu.addAction("Pull File")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        viewable = ext in self.TEXT_EXTS or ext in self.IMAGE_EXTS
        view = menu.addAction("View") if viewable else None
        act = menu.exec(
            self.table.mapToGlobal(
                self.table.visualItemRect(self.table.item(self.table.currentRow(), 0)).center()
            )
        )
        if act == pull:
            self._pull_file(name)
        elif view and act == view:
            self._view_file(name, ext in self.IMAGE_EXTS)

    # ── View / Edit file ─────────────────────────────────────────────────

    def _view_file(self, name: str, is_image: bool = False):
        full = self._dpath(self.current_path, name)
        if is_image:
            self._view_image(name, full)
        else:
            shell = self._root(f'cat "{full}"')
            w = self._run_adb("shell", shell)
            w.finished.connect(lambda o, e: self._show_text_viewer(name, o, e, full))
            w.start()

    def _view_image(self, name: str, full_path: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(name)
        dlg.setMinimumSize(750, 550)
        dlg.setModal(True)
        QVBoxLayout(dlg)

        tmp_dir = os.path.join(tempfile.gettempdir(), "adblab_explorer")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, name)

        if self.root_cb.isChecked():
            dev_tmp = f"/data/local/tmp/{name}"
            w1 = self._run_adb(
                "shell", self._root(f'dd if="{full_path}" of="{dev_tmp}" && chmod 644 "{dev_tmp}"')
            )

            def _on_copy(o, e):
                if e:
                    QMessageBox.critical(dlg, "Error", o)
                    return
                w2 = self._run_transfer("pull", dev_tmp, tmp_path)
                w2.finished.connect(
                    lambda o2, e2, d: self._show_image(dlg, name, tmp_path, dev_tmp)
                )
                w2.start()

            w1.finished.connect(_on_copy)
            w1.start()
        else:
            w = self._run_transfer("pull", full_path, tmp_path)
            w.finished.connect(lambda o2, e2, d: self._show_image(dlg, name, tmp_path, ""))
            w.start()

        dlg.exec()
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    def _show_image(self, dlg, name, tmp_path, dev_tmp):
        if dev_tmp:
            self._run_adb("shell", f'rm "{dev_tmp}"').start()
        lbl = QLabel()
        pm = QPixmap(tmp_path)
        if pm.width() > 730 or pm.height() > 530:
            pm = pm.scaled(
                730,
                530,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        lbl.setPixmap(pm)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dlg.layout().addWidget(lbl)
        info = QLabel(f"{pm.width()}x{pm.height()}  |  {name}")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dlg.layout().addWidget(info)
        cb = QPushButton("Close")
        cb.clicked.connect(dlg.accept)
        dlg.layout().addWidget(cb, alignment=Qt.AlignmentFlag.AlignCenter)

    def _show_text_viewer(self, name: str, content: str, error: bool, full_path: str):
        if error:
            QMessageBox.critical(self, "Error", content)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(name)
        dlg.setMinimumSize(750, 550)
        dlg.setModal(True)
        lo = QVBoxLayout(dlg)
        editor = QPlainTextEdit()
        editor.setPlainText(content)
        editor.setFont(QFont("Consolas", 10))
        lo.addWidget(editor)
        btns = QHBoxLayout()
        save_as = QPushButton("Save As...")
        save_as.clicked.connect(lambda: self._save_as(name, editor.toPlainText()))
        save_dev = QPushButton("Save to Device")
        save_dev.clicked.connect(
            lambda: self._save_to_device(name, editor.toPlainText(), full_path)
        )
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        for b in (save_as, save_dev, close):
            btns.addWidget(b)
        lo.addLayout(btns)
        dlg.exec()

    def _save_as(self, name, content):
        fp, _ = QFileDialog.getSaveFileName(self, "Save As", name)
        if fp:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)

    def _save_to_device(self, name, content, full_path):
        if (
            QMessageBox.question(self, "Confirm", f"Save to {full_path}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = self._root(f"echo '{b64}' | base64 -d > \"{full_path}\"")
        w = self._run_adb("shell", cmd)
        w.finished.connect(lambda o, e: self._on_save_result(o, e, name))
        w.start()

    def _on_save_result(self, output, error, name):
        if error:
            QMessageBox.critical(self, "Error", f"Save failed: {output}")
        else:
            self.status_bar.showMessage(f"Saved {name}")
            self._refresh()

    # ── Pull / Push ──────────────────────────────────────────────────────

    def _pull_file(self, name: str):
        full = self._dpath(self.current_path, name)
        save_path, _ = QFileDialog.getSaveFileName(self, "Save As", name)
        if not save_path:
            return
        if self.root_cb.isChecked():
            dt = f"/data/local/tmp/{name}"
            w = self._run_adb("shell", self._root(f'dd if="{full}" of="{dt}" && chmod 644 "{dt}"'))
            w.finished.connect(lambda o, e: self._finish_root_pull(o, e, name, dt, save_path))
            w.start()
        else:
            w = self._run_transfer("pull", full, save_path)
            w.progress.connect(lambda msg: self.status_bar.showMessage(msg))
            w.finished.connect(lambda o, e, d: self._on_transfer_done(o, e, f"Pulled {name}"))
            w.start()

    def _finish_root_pull(self, o, e, name, dev_tmp, save_path):
        if e:
            QMessageBox.critical(self, "Error", o)
            return
        w = self._run_transfer("pull", dev_tmp, save_path)
        w.progress.connect(lambda msg: self.status_bar.showMessage(msg))
        w.finished.connect(
            lambda o2, e2, d: (
                self._run_adb("shell", f'rm "{dev_tmp}"').start(),
                self._on_transfer_done(o2, e2, f"Pulled {name}"),
            )
        )
        w.start()

    def _pull_selected(self):
        rows = set(i.row() for i in self.table.selectedIndexes())
        if not rows:
            return
        dest = QFileDialog.getExistingDirectory(self, "Destination")
        if not dest:
            return
        for row in rows:
            name = self.table.item(row, 0).text()
            if name == "..":
                continue
            src = self._dpath(self.current_path, name)
            dst = os.path.join(dest, name)
            w = self._run_transfer("pull", src, dst)
            w.progress.connect(lambda msg: self.status_bar.showMessage(msg))
            w.finished.connect(lambda o, e, d, n=name: self._on_transfer_done(o, e, f"Pulled {n}"))
            w.start()

    def _push_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files to Push")
        if not files:
            return
        for fp in files:
            dst = self._dpath(self.current_path, os.path.basename(fp))
            w = self._run_transfer("push", fp, dst)
            w.progress.connect(lambda msg: self.status_bar.showMessage(msg))
            bn = os.path.basename(fp)
            w.finished.connect(
                lambda o, e, d, n=bn: self._on_transfer_done(o, e, f"Pushed {n}")
            )
            w.start()

    def _on_transfer_done(self, o, e, msg):
        if e:
            QMessageBox.critical(self, "Error", o)
        self.status_bar.showMessage(msg)
        self._refresh()

    # ── File operations ──────────────────────────────────────────────────

    def _mkdir(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Name:")
        if not ok or not name or "/" in name:
            return
        full = self._dpath(self.current_path, name)
        w = self._run_adb("shell", self._root(f'mkdir -p "{full}"'))
        w.finished.connect(
            lambda o, e: (self._refresh(), self.status_bar.showMessage(f"Created {name}"))
        )
        w.start()

    def _touch(self):
        name, ok = QInputDialog.getText(self, "New File", "Name:")
        if not ok or not name or "/" in name:
            return
        full = self._dpath(self.current_path, name)
        w = self._run_adb("shell", self._root(f'touch "{full}"'))
        w.finished.connect(
            lambda o, e: (self._refresh(), self.status_bar.showMessage(f"Created {name}"))
        )
        w.start()

    def _rename_item(self, name: str):
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
        if not ok or not new or new == name:
            return
        old = self._dpath(self.current_path, name)
        new_p = self._dpath(self.current_path, new)
        w = self._run_adb("shell", self._root(f'mv "{old}" "{new_p}"'))
        w.finished.connect(
            lambda o, e: (self._refresh(), self.status_bar.showMessage(f"Renamed {name} -> {new}"))
        )
        w.start()

    def _delete_item(self, name: str):
        full = self._dpath(self.current_path, name)
        w = self._run_adb("shell", self._root(f'rm -rf "{full}"'))
        w.finished.connect(
            lambda o, e: (self._refresh(), self.status_bar.showMessage(f"Deleted {name}"))
        )
        w.start()

    def _delete_selected(self):
        rows = set(i.row() for i in self.table.selectedIndexes())
        items = [
            self.table.item(r, 0).text()
            for r in rows
            if self.table.item(r, 0) and self.table.item(r, 0).text() != ".."
        ]
        if not items:
            return
        if (
            QMessageBox.question(self, "Delete", f"Delete {len(items)} item(s)?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        for name in items:
            self._delete_item(name)

    # ── Copy / Cut / Paste ───────────────────────────────────────────────

    def _copy_items(self, copy_mode: bool):
        rows = set(i.row() for i in self.table.selectedIndexes())
        self.clipboard = [
            self._dpath(self.current_path, self.table.item(r, 0).text())
            for r in rows
            if self.table.item(r, 0) and self.table.item(r, 0).text() != ".."
        ]
        self.copy_mode = copy_mode
        self.status_bar.showMessage(
            f"{'Copied' if copy_mode else 'Cut'} {len(self.clipboard)} item(s)"
        )

    def _paste_items(self):
        if not self.clipboard:
            return
        for src in self.clipboard:
            dst = self._dpath(self.current_path, os.path.basename(src))
            if src == dst:
                continue
            if self.copy_mode:
                w = self._run_adb("shell", self._root(f'cp -R "{src}" "{dst}"'))
                w.finished.connect(lambda o, e: None)
                w.start()
            else:
                w = self._run_adb("shell", self._root(f'mv "{src}" "{dst}"'))
                w.finished.connect(lambda o, e: None)
                w.start()
        self.status_bar.showMessage("Paste done")
        self._refresh()
        self.clipboard = []

    # ── chmod ────────────────────────────────────────────────────────────

    def _show_chmod(self, name: str, is_dir: bool):
        full = self._dpath(self.current_path, name)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Permissions - {name}")
        dlg.setModal(True)
        lo = QVBoxLayout(dlg)

        grid = QGridLayout()
        grid.addWidget(QLabel(""), 0, 0)
        for c, col in enumerate(["Owner", "Group", "Other"], 1):
            grid.addWidget(QLabel(col), 0, c, alignment=Qt.AlignmentFlag.AlignCenter)
        cbs = {}
        for r, (label, key) in enumerate([("Read", "r"), ("Write", "w"), ("Execute", "x")], 1):
            grid.addWidget(QLabel(label), r, 0)
            for c, col in enumerate(["owner", "group", "other"], 1):
                cb = QCheckBox()
                grid.addWidget(cb, r, c, alignment=Qt.AlignmentFlag.AlignCenter)
                cbs[(col, key)] = cb
        lo.addLayout(grid)

        preview = QLabel("chmod: ")
        lo.addWidget(preview)
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        revert_btn = QPushButton("Revert")
        close_btn = QPushButton("Close")
        btn_row.addStretch()
        for b in (revert_btn, apply_btn, close_btn):
            btn_row.addWidget(b)
        lo.addLayout(btn_row)
        close_btn.clicked.connect(dlg.reject)

        def to_mode():
            o = (
                (4 if cbs[("owner", "r")].isChecked() else 0)
                + (2 if cbs[("owner", "w")].isChecked() else 0)
                + (1 if cbs[("owner", "x")].isChecked() else 0)
            )
            g = (
                (4 if cbs[("group", "r")].isChecked() else 0)
                + (2 if cbs[("group", "w")].isChecked() else 0)
                + (1 if cbs[("group", "x")].isChecked() else 0)
            )
            ot = (
                (4 if cbs[("other", "r")].isChecked() else 0)
                + (2 if cbs[("other", "w")].isChecked() else 0)
                + (1 if cbs[("other", "x")].isChecked() else 0)
            )
            return f"{o}{g}{ot}"

        def set_from_mode(m):
            try:
                for i, col in enumerate(["owner", "group", "other"]):
                    v = int(m[i])
                    cbs[(col, "r")].setChecked(bool(v & 4))
                    cbs[(col, "w")].setChecked(bool(v & 2))
                    cbs[(col, "x")].setChecked(bool(v & 1))
            except Exception:
                pass

        orig = [""]
        w = self._run_adb("shell", f'stat -c %a "{full}"')

        def _on_stat(o, e):
            m = (o or "").strip()
            if re.match(r"^[0-7]{3,4}$", m):
                orig[0] = m.lstrip("0")[-3:]
            else:
                orig[0] = "644" if not is_dir else "755"
            set_from_mode(orig[0])
            preview.setText(f"chmod {to_mode()}  {full}")

        w.finished.connect(_on_stat)
        w.start()

        for cb in cbs.values():
            cb.stateChanged.connect(lambda: preview.setText(f"chmod {to_mode()}  {full}"))
        revert_btn.clicked.connect(
            lambda: (set_from_mode(orig[0]), preview.setText(f"chmod {to_mode()}  {full}"))
        )
        apply_btn.clicked.connect(
            lambda: (
                self._run_adb("shell", self._root(f'chmod {to_mode()} "{full}"')).start(),
                dlg.accept(),
                self._refresh(),
            )
        )
        dlg.resize(420, 240)
        dlg.exec()

    # ── Context menu ─────────────────────────────────────────────────────

    def _context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        name = self.table.item(row, 0).text()
        if name == "..":
            return
        is_dir = self.table.item(row, 1).text() == "Folder"
        menu = QMenu()
        if is_dir:
            menu.addAction("Open", lambda: self._on_double_click(row, 0))
        else:
            menu.addAction("View", lambda: self._view_file(name))
        menu.addSeparator()
        menu.addAction("Pull", lambda: self._pull_file(name))
        if not is_dir:
            menu.addAction("Push Here", self._push_file)
        if not is_dir and name.endswith(".apk"):
            menu.addAction("Install APK", lambda: self._install_apk(name))
        if not is_dir and name.endswith(".sh"):
            menu.addAction("Execute Script", lambda: self._exec_script(name))
        menu.addAction("Permissions", lambda: self._show_chmod(name, is_dir))
        menu.addSeparator()
        menu.addAction("Rename", lambda: self._rename_item(name))
        menu.addAction("Delete", lambda: self._delete_item(name))
        menu.addSeparator()
        menu.addAction("Copy", lambda: self._copy_items(True))
        menu.addAction("Cut", lambda: self._copy_items(False))
        if self.clipboard:
            menu.addAction("Paste", self._paste_items)
        menu.addSeparator()
        menu.addAction("Properties", lambda: self._show_props(name, is_dir))
        menu.exec(self.table.mapToGlobal(pos))

    def _install_apk(self, name: str):
        full = self._dpath(self.current_path, name)
        cmd = self._root(f'pm install -r "{full}"')
        w = self._run_adb("shell", cmd)
        w.finished.connect(
            lambda o, e: self.status_bar.showMessage(
                f"APK {name} installed" if not e else f"APK install failed: {o}"
            )
        )
        w.start()

    def _exec_script(self, name: str):
        full = self._dpath(self.current_path, name)
        if self.root_cb.isChecked():
            w = self._run_adb("shell", self._root(f'chmod +x "{full}" && sh "{full}"'))
        else:
            w = self._run_adb("shell", f'sh "{full}"')
        w.finished.connect(lambda o, e: self._show_script_output(name, o, e))
        w.start()

    def _show_script_output(self, name, output, error):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Output: {name}")
        dlg.setMinimumSize(700, 400)
        dlg.setModal(False)
        lo = QVBoxLayout(dlg)
        v = QPlainTextEdit()
        v.setReadOnly(True)
        v.setPlainText(output)
        v.setFont(QFont("Consolas", 9))
        lo.addWidget(v)
        cb = QPushButton("Close")
        cb.clicked.connect(dlg.accept)
        lo.addWidget(cb)
        dlg.show()

    def _show_props(self, name: str, is_dir: bool):
        full = self._dpath(self.current_path, name)
        if is_dir:
            w = self._run_adb("shell", f'du -sh "{full}"')
            w.finished.connect(
                lambda o, e: self._show_props_done(
                    name, full, "Folder", o.strip().split()[0] if o.strip() else "?", e
                )
            )
            w.start()
        else:
            w = self._run_adb("shell", f'ls -la "{full}"')
            w.finished.connect(lambda o, e: self._show_props_file(name, full, o, e))
            w.start()

    def _show_props_file(self, name, full, output, error):
        entry = self._parse_ls(output.splitlines()[0] if output.strip() else "")
        if entry:
            info = (
                f"Name: {name}\nType: {self._ext(name)}\n"
                f"Size: {self._fmt_size(entry['size'])}\nPath: {full}\n"
                f"Permissions: {entry['perms']}\n"
                f"Owner: {entry['owner']}:{entry['group']}\n"
                f"Modified: {entry['modified']}"
            )
        else:
            info = f"Name: {name}\nPath: {full}"
        QMessageBox.information(self, f"Properties: {name}", info)

    def _show_props_done(self, name, full, ftype, size, error):
        info = f"Name: {name}\nType: {ftype}\nSize: {size}\nPath: {full}"
        QMessageBox.information(self, f"Properties: {name}", info)

    # ── Sorting / Filtering ──────────────────────────────────────────────

    def _filter(self, text):
        t = text.strip().lower()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.text() != "..":
                self.table.setRowHidden(r, t not in item.text().lower())

    def _header_clicked(self, col):
        if col == self._sort_col:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_col = col
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.table.sortByColumn(col, self._sort_order)

    # ── Cleanup ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        workers = self._workers
        self._workers = []
        for w in workers:
            if w.isRunning():
                w.abort()
                w.setParent(None)
        import threading
        threading.Thread(
            target=lambda ws=workers: [w.wait(5000) for w in ws if w.isRunning()],
            daemon=True,
        ).start()
        super().closeEvent(event)
