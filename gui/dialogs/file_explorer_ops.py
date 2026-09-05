"""提供文件浏览器页的文件操作与传输控制器。"""

import base64
import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CheckBox, PushButton

from gui.dialogs.fluent_dialog import FluentDialog, FluentInputDialog, FluentMessageBox
from gui.dialogs.lifecycle import fit_secondary_window_to_owner_screen, safe_disconnect
from gui.styles import FontRole
from gui.styles.fluent import apply_label_role
from gui.styles.icon_loader import get_themed_icon
from services import file_explorer as explorer_service


class FileExplorerOps:
    """组合进 FileExplorerPage 的文件操作控制器，通过 ``self._frame`` 访问页面。"""

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
        if not self._frame._can_operate():
            return
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = self._frame._root(explorer_service.save_text_command(b64, full_path))
        w = self._frame._run_adb("shell", cmd)
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self._on_save_result(o, e, name),
        )
        w.start()

    def _on_save_result(self, output, error, name):
        if error:
            FluentMessageBox.critical(
                self._frame,
                "Error",
                f"Save failed: {output}",
            )
        else:
            self._frame.status_bar.setText(f"Saved {name}")
            self._frame._refresh()

    # ── 拉取与推送 ──────────────────────────────────────────────────────

    def _pull_file(self, name: str):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        save_path, _ = QFileDialog.getSaveFileName(
            self._frame, "Save As", os.path.join(self._global_save_dir(), name)
        )
        if not save_path:
            return
        self._frame.status_bar.setText(f"Pulling {name}...")
        if self._frame.root_cb.isChecked():
            dt = f"/data/local/tmp/{name}"
            w = self._frame._run_adb(
                "shell",
                self._frame._root(explorer_service.copy_for_root_pull_command(full, dt)),
                timeout=120,
            )
            if w is None:
                return
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._finish_root_pull(o, e, name, dt, save_path),
            )
            w.start()
        else:
            w = self._frame._run_transfer("pull", full, save_path)
            if w is None:
                return
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.setText(msg),
            )
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e, d: self._on_transfer_done(o, e, f"Pulled {name}"),
            )
            w.start()

    def _finish_root_pull(self, o, e, name, dev_tmp, save_path):
        if e:
            FluentMessageBox.critical(
                self._frame,
                "Error",
                o,
            )
            self._frame.status_bar.setText(f"Failed: {o}")
            return
        if not self._frame._can_operate():
            self._frame._cleanup_remote_file(dev_tmp, root=True)
            return
        w = self._frame._run_transfer("pull", dev_tmp, save_path)
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.progress,
            lambda msg: self._frame.status_bar.setText(msg),
        )
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o2, e2, d: (
                self._frame._cleanup_remote_file(dev_tmp, root=True),
                self._on_transfer_done(o2, e2, f"Pulled {name}"),
            ),
        )
        w.start()

    def _pull_selected(self):
        if not self._frame._can_operate():
            return
        rows = set(i.row() for i in self._frame.table.selectedIndexes())
        if not rows:
            return
        dest = QFileDialog.getExistingDirectory(self._frame, "Destination", self._global_save_dir())
        if not dest:
            return
        for row in rows:
            name = self._frame._file_name_at(row)
            if name == "..":
                continue
            src = self._frame._dpath(self._frame.current_path, name)
            dst = os.path.join(dest, name)
            w = self._frame._run_transfer("pull", src, dst)
            if w is None:
                return
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.setText(msg),
            )
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e, d, n=name: self._on_transfer_done(o, e, f"Pulled {n}"),
            )
            w.start()

    def _push_file(self):
        if not self._frame._can_operate():
            return
        files, _ = QFileDialog.getOpenFileNames(self._frame, "Select Files to Push")
        if not files:
            return
        for fp in files:
            dst = self._frame._dpath(self._frame.current_path, os.path.basename(fp))
            w = self._frame._run_transfer("push", fp, dst)
            if w is None:
                return
            self._frame._connect_worker_ui(
                w,
                w.progress,
                lambda msg: self._frame.status_bar.setText(msg),
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
            FluentMessageBox.critical(
                self._frame,
                "Error",
                o,
            )
            self._frame.status_bar.setText(f"Failed: {o}")
            return
        self._frame.status_bar.setText(msg)
        self._frame._refresh()

    def _on_file_op_done(self, output: str, error: bool, success_msg: str):
        if error:
            FluentMessageBox.critical(
                self._frame,
                "Error",
                output,
            )
            self._frame.status_bar.setText(f"Failed: {output}")
            return
        self._frame.status_bar.setText(success_msg)
        self._frame._refresh()

    # ── 文件操作 ────────────────────────────────────────────────────────

    def _mkdir(self):
        if not self._frame._can_operate():
            return
        name, ok = FluentInputDialog.getText(self._frame, "New Folder", "Name:")
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            FluentMessageBox.warning(
                self._frame,
                "Invalid Name",
                "Folder name contains invalid characters",
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.mkdir_command(full)))
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(o, e, f"Created {n}"),
        )
        w.start()

    def _touch(self):
        if not self._frame._can_operate():
            return
        name, ok = FluentInputDialog.getText(self._frame, "New File", "Name:")
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            FluentMessageBox.warning(
                self._frame,
                "Invalid Name",
                "Filename contains invalid characters",
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.touch_command(full)))
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(o, e, f"Created {n}"),
        )
        w.start()

    def _rename_item(self, name: str):
        if not self._frame._can_operate():
            return
        new, ok = FluentInputDialog.getText(self._frame, "Rename", "New name:", text=name)
        if not ok or not new or new == name:
            return
        if not self._frame._safe_name(new):
            FluentMessageBox.warning(
                self._frame,
                "Invalid Name",
                "New name contains invalid characters",
            )
            return
        old = self._frame._dpath(self._frame.current_path, name)
        new_p = self._frame._dpath(self._frame.current_path, new)
        w = self._frame._run_adb(
            "shell", self._frame._root(explorer_service.move_command(old, new_p))
        )
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, old_name=name, new_name=new: self._on_file_op_done(
                o, e, f"Renamed {old_name} -> {new_name}"
            ),
        )
        w.start()

    def _delete_item(self, name: str):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        self._frame.status_bar.setText(f"Deleting {name}...")
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.delete_command(full)))
        if w is None:
            return
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
        self._frame.status_bar.setText(
            f"{'Copied' if copy_mode else 'Cut'} {len(self._frame.clipboard)} item(s)"
        )

    def _paste_items(self):
        if not self._frame._can_operate():
            return
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
                if w is None:
                    return
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
                if w is None:
                    return
                self._frame._connect_worker_ui(
                    w,
                    w.result_ready,
                    lambda o, e, n=os.path.basename(src): self._on_file_op_done(o, e, f"Moved {n}"),
                )
                w.start()
        self._frame.status_bar.setText(f"Paste submitted: {len(self._frame.clipboard)} item(s)")
        self._frame.clipboard = []

    # ── 文件权限（chmod）────────────────────────────────────────────────

    def _show_chmod(self, name: str, is_dir: bool):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        dlg = FluentDialog(self._frame)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowTitle(f"Permissions - {name}")
        dlg.setModal(True)
        lo = QVBoxLayout(dlg)

        grid = QGridLayout()
        grid.addWidget(apply_label_role(BodyLabel(""), FontRole.UI), 0, 0)
        for c, col in enumerate(["Owner", "Group", "Other"], 1):
            grid.addWidget(
                apply_label_role(BodyLabel(col), FontRole.UI, bold=True),
                0,
                c,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
        cbs = {}
        for r, (label, key) in enumerate([("Read", "r"), ("Write", "w"), ("Execute", "x")], 1):
            grid.addWidget(apply_label_role(BodyLabel(label), FontRole.UI), r, 0)
            for c, col in enumerate(["owner", "group", "other"], 1):
                cb = CheckBox()
                grid.addWidget(cb, r, c, alignment=Qt.AlignmentFlag.AlignCenter)
                cbs[(col, key)] = cb
        lo.addLayout(grid)

        preview = apply_label_role(BodyLabel("chmod: "), FontRole.MONO, color_key="TEXT_SECONDARY")
        lo.addWidget(preview)
        btn_row = QHBoxLayout()
        apply_btn = PushButton()
        apply_btn.setText("Apply")
        apply_btn.setToolTip("Apply the selected file permissions")
        apply_btn.setIcon(get_themed_icon("check-circle.svg"))
        apply_btn.setIconSize(QSize(14, 14))
        apply_btn.setEnabled(False)
        revert_btn = PushButton()
        revert_btn.setText("Revert")
        revert_btn.setToolTip("Restore the original file permissions")
        revert_btn.setIcon(get_themed_icon("arrow-u-up-left.svg"))
        revert_btn.setIconSize(QSize(14, 14))
        revert_btn.setEnabled(False)
        close_btn = PushButton()
        close_btn.setText("Close")
        close_btn.setToolTip("Close the permissions window")
        close_btn.setIcon(get_themed_icon("x.svg"))
        close_btn.setIconSize(QSize(14, 14))
        btn_row.addStretch()
        for b in (revert_btn, apply_btn, close_btn):
            btn_row.addWidget(b)
        lo.addLayout(btn_row)
        dlg.finalize_fluent_layout()
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
        applying = [False]

        def _sync_apply_access(*_args):
            apply_btn.setEnabled(
                bool(orig[0]) and not applying[0] and self._frame._can_operate()
            )

        w = self._frame._run_adb("shell", explorer_service.stat_mode_command(full))
        if w is None:
            return

        def _on_stat(o, e):
            if e:
                preview.setText("Unable to read current permissions")
                FluentMessageBox.critical(
                    dlg,
                    "Permissions Error",
                    o or "Permission read failed",
                )
                return
            mode = explorer_service.parse_mode(o)
            if mode is None:
                preview.setText("Unable to read current permissions")
                FluentMessageBox.critical(
                    dlg,
                    "Permissions Error",
                    "The device returned an invalid permission mode.",
                )
                return
            orig[0] = mode
            set_from_mode(orig[0])
            preview.setText(f"chmod {to_mode()}  {full}")
            _sync_apply_access()
            revert_btn.setEnabled(True)

        self._frame._connect_worker_ui(w, w.result_ready, _on_stat, guard_objects=(dlg,))
        w.start()

        for cb in cbs.values():
            cb.stateChanged.connect(lambda: preview.setText(f"chmod {to_mode()}  {full}"))
        revert_btn.clicked.connect(
            lambda: (set_from_mode(orig[0]), preview.setText(f"chmod {to_mode()}  {full}"))
        )

        def _apply_permissions():
            if not self._frame._can_operate() or not orig[0] or applying[0]:
                return
            applying[0] = True
            apply_btn.setEnabled(False)
            revert_btn.setEnabled(False)
            mode = to_mode()
            preview.setText(f"Applying chmod {mode}  {full}...")
            chmod_worker = self._frame._run_adb(
                "shell",
                self._frame._root(explorer_service.chmod_command(mode, full)),
            )
            if chmod_worker is None:
                applying[0] = False
                _sync_apply_access()
                return

            def _on_chmod(output, error):
                if error:
                    applying[0] = False
                    _sync_apply_access()
                    revert_btn.setEnabled(True)
                    preview.setText(f"chmod failed for {full}")
                    FluentMessageBox.critical(
                        dlg,
                        "Permissions Error",
                        output or "Permission update failed",
                    )
                    return
                self._frame.status_bar.setText(f"Permissions updated for {name}")
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
        dlg.resize(420, 240 + dlg.TITLE_BAR_HEIGHT)
        fit_secondary_window_to_owner_screen(
            dlg,
            self._frame,
            minimum_floor=QSize(420, 240 + dlg.TITLE_BAR_HEIGHT),
        )
        self._frame.operation_availability_changed.connect(_sync_apply_access)
        try:
            dlg.exec()
        finally:
            safe_disconnect(self._frame.operation_availability_changed, _sync_apply_access)
