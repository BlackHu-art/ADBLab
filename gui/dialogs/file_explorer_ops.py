"""提供文件浏览器对话框的文件操作与传输控制器。"""

import base64
import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from gui.dialogs.lifecycle import fit_secondary_window_to_owner_screen
from gui.styles.icon_loader import get_themed_icon
from services import file_explorer as explorer_service


class FileExplorerOps:
    """组合进 FileExplorerDialog 的文件操作控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    # ── 查看与编辑文件 ──────────────────────────────────────────────────

    @staticmethod
    def _global_save_dir() -> str:
        from core.settings_manager import AppSettings

        return AppSettings.instance().save_directory

    def _save_as(self, name, content):
        fp, _ = QFileDialog.getSaveFileName(
            self._frame, "Save As", os.path.join(self._global_save_dir(), name)
        )
        if fp:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)

    def _save_to_device(self, name, content, full_path):
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = self._frame._root(explorer_service.save_text_command(b64, full_path))
        w = self._frame._run_adb("shell", cmd)
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self._on_save_result(o, e, name),
        )
        w.start()

    def _on_save_result(self, output, error, name):
        if error:
            QMessageBox.critical(
                self._frame,
                "Error",
                f"Save failed: {output}",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
        else:
            self._frame.status_bar.showMessage(f"Saved {name}")
            self._frame._refresh()

    # ── 拉取与推送 ──────────────────────────────────────────────────────

    def _pull_file(self, name: str):
        full = self._frame._dpath(self._frame.current_path, name)
        save_path, _ = QFileDialog.getSaveFileName(
            self._frame, "Save As", os.path.join(self._global_save_dir(), name)
        )
        if not save_path:
            return
        self._frame.status_bar.showMessage(f"Pulling {name}...")
        if self._frame.root_cb.isChecked():
            dt = f"/data/local/tmp/{name}"
            w = self._frame._run_adb(
                "shell",
                self._frame._root(explorer_service.copy_for_root_pull_command(full, dt)),
                timeout=120,
            )
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._finish_root_pull(o, e, name, dt, save_path),
            )
            w.start()
        else:
            w = self._frame._run_transfer("pull", full, save_path)
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.showMessage(msg),
            )
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e, d: self._on_transfer_done(o, e, f"Pulled {name}"),
            )
            w.start()

    def _finish_root_pull(self, o, e, name, dev_tmp, save_path):
        if e:
            QMessageBox.critical(
                self._frame,
                "Error",
                o,
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            self._frame.status_bar.showMessage(f"Failed: {o}")
            return
        w = self._frame._run_transfer("pull", dev_tmp, save_path)
        self._frame._connect_worker_ui(
            w,
            w.progress,
            lambda msg: self._frame.status_bar.showMessage(msg),
        )
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o2, e2, d: (
                self._frame._run_adb(
                    "shell", self._frame._root(explorer_service.delete_command(dev_tmp))
                ).start(),
                self._on_transfer_done(o2, e2, f"Pulled {name}"),
            ),
        )
        w.start()

    def _pull_selected(self):
        rows = set(i.row() for i in self._frame.table.selectedIndexes())
        if not rows:
            return
        dest = QFileDialog.getExistingDirectory(
            self._frame, "Destination", self._global_save_dir()
        )
        if not dest:
            return
        for row in rows:
            name = self._frame._file_name_at(row)
            if name == "..":
                continue
            src = self._frame._dpath(self._frame.current_path, name)
            dst = os.path.join(dest, name)
            w = self._frame._run_transfer("pull", src, dst)
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.showMessage(msg),
            )
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e, d, n=name: self._on_transfer_done(o, e, f"Pulled {n}"),
            )
            w.start()

    def _push_file(self):
        files, _ = QFileDialog.getOpenFileNames(self._frame, "Select Files to Push")
        if not files:
            return
        for fp in files:
            dst = self._frame._dpath(self._frame.current_path, os.path.basename(fp))
            w = self._frame._run_transfer("push", fp, dst)
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.showMessage(msg),
            )
            bn = os.path.basename(fp)
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e, d, n=bn: self._on_transfer_done(o, e, f"Pushed {n}"),
            )
            w.start()

    def _on_transfer_done(self, o, e, msg):
        if e:
            QMessageBox.critical(
                self._frame,
                "Error",
                o,
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            self._frame.status_bar.showMessage(f"Failed: {o}")
            return
        self._frame.status_bar.showMessage(msg)
        self._frame._refresh()

    def _on_file_op_done(self, output: str, error: bool, success_msg: str):
        if error:
            QMessageBox.critical(
                self._frame,
                "Error",
                output,
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            self._frame.status_bar.showMessage(f"Failed: {output}")
            return
        self._frame.status_bar.showMessage(success_msg)
        self._frame._refresh()

    # ── 文件操作 ────────────────────────────────────────────────────────

    def _mkdir(self):
        name, ok = QInputDialog.getText(self._frame, "New Folder", "Name:")
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            QMessageBox.warning(
                self._frame,
                "Invalid Name",
                "Folder name contains invalid characters",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.mkdir_command(full)))
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(o, e, f"Created {n}"),
        )
        w.start()

    def _touch(self):
        name, ok = QInputDialog.getText(self._frame, "New File", "Name:")
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            QMessageBox.warning(
                self._frame,
                "Invalid Name",
                "Filename contains invalid characters",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.touch_command(full)))
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(o, e, f"Created {n}"),
        )
        w.start()

    def _rename_item(self, name: str):
        new, ok = QInputDialog.getText(self._frame, "Rename", "New name:", text=name)
        if not ok or not new or new == name:
            return
        if not self._frame._safe_name(new):
            QMessageBox.warning(
                self._frame,
                "Invalid Name",
                "New name contains invalid characters",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        old = self._frame._dpath(self._frame.current_path, name)
        new_p = self._frame._dpath(self._frame.current_path, new)
        w = self._frame._run_adb(
            "shell", self._frame._root(explorer_service.move_command(old, new_p))
        )
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, old_name=name, new_name=new: self._on_file_op_done(
                o, e, f"Renamed {old_name} -> {new_name}"
            ),
        )
        w.start()

    def _delete_item(self, name: str):
        full = self._frame._dpath(self._frame.current_path, name)
        self._frame.status_bar.showMessage(f"Deleting {name}...")
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.delete_command(full)))
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(o, e, f"Deleted {n}"),
        )
        w.start()

    def _request_delete(self, names: str | list[str]):
        """删除选中条目；不再弹窗确认，删除前仍校验目标并排除 ".."。"""

        items = [names] if isinstance(names, str) else list(names)
        items = [name for name in items if name and name != ".."]
        if not items:
            return
        for name in items:
            self._delete_item(name)

    def _delete_selected(self):
        rows = set(i.row() for i in self._frame.table.selectedIndexes())
        items = [self._frame._file_name_at(r) for r in rows if self._frame._file_name_at(r) != ".."]
        if not items:
            return
        self._request_delete(items)

    # ── 复制、剪切与粘贴 ────────────────────────────────────────────────

    def _copy_items(self, copy_mode: bool):
        rows = set(i.row() for i in self._frame.table.selectedIndexes())
        self._frame.clipboard = [
            self._frame._dpath(self._frame.current_path, self._frame._file_name_at(r))
            for r in rows
            if self._frame._file_name_at(r) != ".."
        ]
        self._frame.copy_mode = copy_mode
        self._frame.status_bar.showMessage(
            f"{'Copied' if copy_mode else 'Cut'} {len(self._frame.clipboard)} item(s)"
        )

    def _paste_items(self):
        if not self._frame.clipboard:
            return
        for src in self._frame.clipboard:
            dst = self._frame._dpath(self._frame.current_path, os.path.basename(src))
            if src == dst:
                continue
            if self._frame.copy_mode:
                w = self._frame._run_adb(
                    "shell",
                    self._frame._root(explorer_service.copy_command(src, dst)),
                    timeout=120,
                )
                self._frame._connect_worker_ui(
                    w,
                    w.result_ready,
                    lambda o, e, n=os.path.basename(src): self._on_file_op_done(
                        o, e, f"Pasted {n}"
                    ),
                )
                w.start()
            else:
                w = self._frame._run_adb(
                    "shell",
                    self._frame._root(explorer_service.move_command(src, dst)),
                    timeout=120,
                )
                self._frame._connect_worker_ui(
                    w,
                    w.result_ready,
                    lambda o, e, n=os.path.basename(src): self._on_file_op_done(o, e, f"Moved {n}"),
                )
                w.start()
        self._frame.status_bar.showMessage(f"Paste submitted: {len(self._frame.clipboard)} item(s)")
        self._frame.clipboard = []

    # ── 文件权限（chmod）────────────────────────────────────────────────

    def _show_chmod(self, name: str, is_dir: bool):
        full = self._frame._dpath(self._frame.current_path, name)
        dlg = QDialog(self._frame)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
        apply_btn.setToolTip("Apply the selected file permissions")
        apply_btn.setIcon(get_themed_icon("check-circle.svg"))
        apply_btn.setIconSize(QSize(14, 14))
        apply_btn.setEnabled(False)
        revert_btn = QPushButton("Revert")
        revert_btn.setToolTip("Restore the original file permissions")
        revert_btn.setIcon(get_themed_icon("arrow-u-up-left.svg"))
        revert_btn.setIconSize(QSize(14, 14))
        revert_btn.setEnabled(False)
        close_btn = QPushButton("Close")
        close_btn.setToolTip("Close the permissions window")
        close_btn.setIcon(get_themed_icon("x.svg"))
        close_btn.setIconSize(QSize(14, 14))
        btn_row.addStretch()
        for b in (revert_btn, apply_btn, close_btn):
            btn_row.addWidget(b)
        lo.addLayout(btn_row)
        close_btn.clicked.connect(dlg.reject)

        def to_mode():
            return explorer_service.mode_from_permissions(
                {key: cb.isChecked() for key, cb in cbs.items()}
            )

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
        w = self._frame._run_adb("shell", explorer_service.stat_mode_command(full))

        def _on_stat(o, e):
            if e:
                preview.setText("Unable to read current permissions")
                QMessageBox.critical(
                    dlg,
                    "Permissions Error",
                    o or "Permission read failed",
                    QMessageBox.StandardButton.Ok,
                    QMessageBox.StandardButton.NoButton,
                )
                return
            mode = explorer_service.parse_mode(o)
            if mode is None:
                preview.setText("Unable to read current permissions")
                QMessageBox.critical(
                    dlg,
                    "Permissions Error",
                    "The device returned an invalid permission mode.",
                    QMessageBox.StandardButton.Ok,
                    QMessageBox.StandardButton.NoButton,
                )
                return
            orig[0] = mode
            set_from_mode(orig[0])
            preview.setText(f"chmod {to_mode()}  {full}")
            apply_btn.setEnabled(True)
            revert_btn.setEnabled(True)

        self._frame._connect_worker_ui(w, w.result_ready, _on_stat, guard_objects=(dlg,))
        w.start()

        for cb in cbs.values():
            cb.stateChanged.connect(lambda: preview.setText(f"chmod {to_mode()}  {full}"))
        revert_btn.clicked.connect(
            lambda: (set_from_mode(orig[0]), preview.setText(f"chmod {to_mode()}  {full}"))
        )

        def _apply_permissions():
            apply_btn.setEnabled(False)
            revert_btn.setEnabled(False)
            mode = to_mode()
            preview.setText(f"Applying chmod {mode}  {full}...")
            chmod_worker = self._frame._run_adb(
                "shell",
                self._frame._root(explorer_service.chmod_command(mode, full)),
            )

            def _on_chmod(output, error):
                if error:
                    apply_btn.setEnabled(True)
                    revert_btn.setEnabled(True)
                    preview.setText(f"chmod failed for {full}")
                    QMessageBox.critical(
                        dlg,
                        "Permissions Error",
                        output or "Permission update failed",
                        QMessageBox.StandardButton.Ok,
                        QMessageBox.StandardButton.NoButton,
                    )
                    return
                self._frame.status_bar.showMessage(f"Permissions updated for {name}")
                self._frame._refresh()
                dlg.accept()

            self._frame._connect_worker_ui(
                chmod_worker,
                chmod_worker.result_ready,
                _on_chmod,
                guard_objects=(dlg,),
            )
            chmod_worker.start()

        apply_btn.clicked.connect(_apply_permissions)
        dlg.resize(420, 240)
        fit_secondary_window_to_owner_screen(dlg, self._frame)
        dlg.exec()
