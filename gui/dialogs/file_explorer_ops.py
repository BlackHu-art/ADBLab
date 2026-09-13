"""提供文件浏览器页的文件操作与传输控制器。"""

import base64
import os
import uuid

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CheckBox, PushButton

from core.log_service import LogService
from gui.dialogs.fluent_dialog import FluentDialog, FluentInputDialog, FluentMessageBox
from gui.dialogs.lifecycle import fit_secondary_window_to_owner_screen, safe_disconnect
from gui.feedback import report_feedback
from gui.i18n import tr
from gui.styles import FontRole
from gui.styles.fluent import apply_label_role
from gui.styles.icon_loader import get_themed_icon
from services import file_explorer as explorer_service


class FileExplorerOps:
    """组合进 FileExplorerPage 的文件操作控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame
        self._last_batch_results = ()

    # ── 查看与编辑文件 ──────────────────────────────────────────────────

    @staticmethod
    def _global_save_dir() -> str:
        from core.settings_manager import AppSettings

        return AppSettings.instance().save_directory

    def _save_as(self, name, content):
        fp, _ = QFileDialog.getSaveFileName(
            self._frame, tr("Save As"), os.path.join(self._global_save_dir(), name)
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
        self._on_file_op_done(output, error, tr('Saved {value0}').format(value0=name))

    # ── 拉取与推送 ──────────────────────────────────────────────────────

    def _pull_file(self, name: str):
        """单文件下载冻结设备与 Root 模式，独占中转资源直到清理完成。"""
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        device = self._frame.device_ip
        use_root = self._frame.root_cb.isChecked()
        save_path, _ = QFileDialog.getSaveFileName(
            self._frame, tr("Save As"), os.path.join(self._global_save_dir(), name)
        )
        if not save_path or not self._frame._can_operate():
            return
        self._frame.status_bar.setText(tr('Pulling {value0}...').format(value0=name))
        if not use_root:
            self._queue_single_pull(name, full, save_path, device)
            return
        remote = f"/data/local/tmp/adblab-pull-{uuid.uuid4().hex}"
        token = self._frame._transfers.hold_cleanup()
        command = explorer_service.root_command(
            explorer_service.copy_for_root_pull_command(full, remote), True
        )
        worker = self._frame._run_adb("shell", command, timeout=120, _device_ip=device)
        if worker is None:
            self._frame._transfers.release_cleanup(token)
            return
        result = []
        worker.result_ready.connect(
            lambda output, failed: result.append((output, failed)),
            Qt.ConnectionType.QueuedConnection,
        )

        def prepared():
            if (not result or worker._aborted.is_set() or not self._frame._can_operate()
                    or result[-1][1]):
                self._cleanup_owned_pull(remote, device, token)
                if result and result[-1][1] and not self._frame._closing:
                    self._on_transfer_done(result[-1][0], True, "")
                return
            self._queue_single_pull(
                name, remote, save_path, device,
                cleanup=lambda: self._cleanup_owned_pull(remote, device, token),
            )

        self._frame._transfers.enqueue(worker, on_terminal=prepared)

    def _cleanup_owned_pull(self, remote, device, token):
        """清理既有请求的精确中转路径；页面关闭和 Root 切换不改变归属。"""
        command = explorer_service.root_command(explorer_service.delete_command(remote), True)
        worker = self._frame._run_adb(
            "shell", command, timeout=15, _cleanup=True, _device_ip=device
        )
        if worker is None:
            self._frame._transfers.release_cleanup(token)
            return
        result = []
        worker.result_ready.connect(
            lambda output, failed: result.append((output, failed)),
            Qt.ConnectionType.QueuedConnection,
        )

        def cleaned():
            if not result or result[-1][1]:
                LogService().log("WARNING", "文件下载的远端临时文件清理失败，设备可能已离线。")
            self._frame._transfers.release_cleanup(token)

        worker.finished.connect(cleaned, Qt.ConnectionType.QueuedConnection)
        self._frame._connect_worker_ui(
            worker, worker.result_ready,
            lambda output, failed: self._on_transfer_done(output, True, "") if failed else None,
        )
        worker.start()

    def _queue_single_pull(self, name, remote, destination, device, cleanup=None):
        """普通下载与中转下载共用 FIFO，清理回调不依赖界面存活守卫。"""
        worker = self._frame._run_transfer("pull", remote, destination, _device_ip=device)
        if worker is None:
            if cleanup is not None:
                cleanup()
            return
        self._frame._connect_worker_ui(
            worker, worker.progress, lambda message: self._frame.status_bar.setText(message)
        )
        self._frame._connect_worker_ui(
            worker, worker.result_ready,
            lambda output, failed, _local: self._on_transfer_done(
                output, failed, tr("Pulled {value0}").format(value0=name)
            ),
        )
        self._frame._transfers.enqueue(worker, cleanup=cleanup)

    def _finish_root_pull(self, o, e, name, dev_tmp, save_path):
        """兼容已准备中转文件的续发入口，下载失败或取消也履行清理义务。"""
        device = self._frame.device_ip
        token = self._frame._transfers.hold_cleanup()
        def cleanup():
            self._cleanup_owned_pull(dev_tmp, device, token)

        if e or not self._frame._can_operate():
            cleanup()
            if e and not self._frame._closing:
                self._on_transfer_done(o, True, "")
            return
        self._queue_single_pull(name, dev_tmp, save_path, device, cleanup)

    def _pull_selected(self):
        if not self._frame._can_operate():
            return
        origin = self._frame.current_path
        rows = sorted({index.row() for index in self._frame.table.selectedIndexes()})
        names = [self._frame._file_name_at(row) for row in rows]
        names = [name for name in names if name != ".."]
        if not names:
            return
        dest = QFileDialog.getExistingDirectory(
            self._frame, tr("Destination"), self._global_save_dir()
        )
        if dest:
            items = [(name, self._frame._dpath(origin, name), os.path.join(dest, name))
                     for name in names]
            self._enqueue_batch("pull", items, origin)

    def _push_file(self):
        if not self._frame._can_operate():
            return
        origin = self._frame.current_path
        files, _ = QFileDialog.getOpenFileNames(self._frame, tr("Select Files to Push"))
        if files:
            items = [(os.path.basename(path), path,
                      self._frame._dpath(origin, os.path.basename(path))) for path in files]
            self._enqueue_batch("push", items, origin)

    def _enqueue_batch(self, direction, items, origin):
        """冻结路径后串行调度整批，保留每项结果，终态只刷新一次原目标。"""
        if not self._frame._can_operate() or not items:
            return
        records = []
        remaining = [len(items)]
        device = self._frame.device_ip

        def finish_item(record):
            if record["result"] is None:
                record["result"] = ("cancelled", "")
            remaining[0] -= 1
            if remaining[0]:
                return
            self._last_batch_results = tuple(
                (item["name"], *item["result"]) for item in records
            )
            if self._frame._closing:
                return
            success = sum(item["result"][0] == "succeeded" for item in records)
            failed = sum(item["result"][0] == "failed" for item in records)
            cancelled = len(records) - success - failed
            labels = {
                "succeeded": tr("成功"), "failed": tr("失败"), "cancelled": tr("已取消")
            }
            summary = (
                f"{labels['succeeded']}: {success} | {labels['failed']}: {failed} | "
                f"{labels['cancelled']}: {cancelled}"
            )
            details = "\n".join(
                f"{name}: {labels[state]}" for name, state, _output in self._last_batch_results
            )
            self._frame.status_bar.setText(summary)
            report_feedback(
                self._frame, "devices.files", tr("文件管理"), f"{summary}\n{details}",
                level="error" if failed else "info" if cancelled else "success",
                notify=not cancelled, target=device,
            )
            attempted = any(getattr(item["worker"], "_transfer_dispatched", False)
                            for item in records)
            if (direction == "push" and attempted and self._frame._can_operate()
                    and self._frame.current_path == origin):
                self._frame._refresh()

        for name, source, target in items:
            worker = self._frame._run_transfer(direction, source, target, _device_ip=device)
            if worker is None:
                return
            record = {"name": name, "worker": worker, "result": None}
            records.append(record)

            def remember(output, error, _local, record=record):
                record["result"] = ("failed" if error else "succeeded", output)

            worker.result_ready.connect(remember, Qt.ConnectionType.QueuedConnection)
            self._frame._connect_worker_ui(
                worker, worker.progress, lambda message: self._frame.status_bar.setText(message)
            )
        for record in records:
            self._frame._transfers.enqueue(
                record["worker"], on_terminal=lambda record=record: finish_item(record)
            )

    def _on_transfer_done(self, o, e, msg):
        """下载终态只更新反馈；本地写入不改变远端目录。"""
        report_feedback(
            self._frame, "devices.files", tr("文件管理"), str(o) if e else msg,
            level="error" if e else "success", notify=True, target=self._frame.device_ip,
        )
        self._frame.status_bar.setText(tr('Failed: {value0}').format(value0=o) if e else msg)

    def _on_file_op_done(self, output: str, error: bool, success_msg: str):
        """文件终态进入任务记录并分级通知；列表刷新和传输状态仍归当前页面管理。"""
        report_feedback(
            self._frame, "devices.files", tr("文件管理"),
            str(output) if error else success_msg,
            level="error" if error else "success", notify=True,
            target=self._frame.device_ip,
        )
        if error:
            self._frame.status_bar.setText(tr('Failed: {value0}').format(value0=output))
            return
        self._frame.status_bar.setText(success_msg)
        self._frame._refresh()

    # ── 文件操作 ────────────────────────────────────────────────────────

    def _mkdir(self):
        if not self._frame._can_operate():
            return
        name, ok = FluentInputDialog.getText(self._frame, tr("New Folder"), tr("Name:"))
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            FluentMessageBox.warning(
                self._frame,
                tr("Invalid Name"),
                tr("Folder name contains invalid characters"),
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.mkdir_command(full)))
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(
                o, e, tr("Created {value0}").format(value0=n)
            ),
        )
        w.start()

    def _touch(self):
        if not self._frame._can_operate():
            return
        name, ok = FluentInputDialog.getText(self._frame, tr("New File"), tr("Name:"))
        if not ok or not name or "/" in name:
            return
        if not self._frame._safe_name(name):
            FluentMessageBox.warning(
                self._frame,
                tr("Invalid Name"),
                tr("Filename contains invalid characters"),
            )
            return
        full = self._frame._dpath(self._frame.current_path, name)
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.touch_command(full)))
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(
                o, e, tr("Created {value0}").format(value0=n)
            ),
        )
        w.start()

    def _rename_item(self, name: str):
        if not self._frame._can_operate():
            return
        new, ok = FluentInputDialog.getText(self._frame, tr("Rename"), tr("New name:"), text=name)
        if not ok or not new or new == name:
            return
        if not self._frame._safe_name(new):
            FluentMessageBox.warning(
                self._frame,
                tr("Invalid Name"),
                tr("New name contains invalid characters"),
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
                o, e, tr('Renamed {value0} -> {value1}').format(value0=old_name, value1=new_name)
            ),
        )
        w.start()

    def _delete_item(self, name: str):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        self._frame.status_bar.setText(tr('Deleting {value0}...').format(value0=name))
        w = self._frame._run_adb("shell", self._frame._root(explorer_service.delete_command(full)))
        if w is None:
            return
        self._frame._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e, n=name: self._on_file_op_done(
                o, e, tr("Deleted {value0}").format(value0=n)
            ),
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
            tr("{value0} {value1} item(s)").format(
                value0=tr("Copied") if copy_mode else tr("Cut"), value1=len(self._frame.clipboard)
            )
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
                        o, e, tr('Pasted {value0}').format(value0=n)
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
                    lambda o, e, n=os.path.basename(src): self._on_file_op_done(
                        o, e, tr("Moved {value0}").format(value0=n)
                    ),
                )
                w.start()
        self._frame.status_bar.setText(
            tr("Paste submitted: {value0} item(s)").format(value0=len(self._frame.clipboard))
        )
        self._frame.clipboard = []

    # ── 文件权限（chmod）────────────────────────────────────────────────

    def _show_chmod(self, name: str, is_dir: bool):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        dlg = FluentDialog(self._frame)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowTitle(tr('Permissions - {value0}').format(value0=name))
        dlg.setModal(True)
        lo = QVBoxLayout(dlg)

        grid = QGridLayout()
        grid.addWidget(apply_label_role(BodyLabel(""), FontRole.UI), 0, 0)
        for c, col in enumerate([tr("Owner"), tr("Group"), tr("Other")], 1):
            grid.addWidget(
                apply_label_role(BodyLabel(col), FontRole.UI, bold=True),
                0,
                c,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
        cbs = {}
        for r, (label, key) in enumerate(
            [(tr("Read"), "r"), (tr("Write"), "w"), (tr("Execute"), "x")], 1
        ):
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
        apply_btn.setText(tr("Apply"))
        apply_btn.setToolTip(tr("Apply the selected file permissions"))
        apply_btn.setIcon(get_themed_icon("check-circle.svg"))
        apply_btn.setIconSize(QSize(14, 14))
        apply_btn.setEnabled(False)
        revert_btn = PushButton()
        revert_btn.setText(tr("Revert"))
        revert_btn.setToolTip(tr("Restore the original file permissions"))
        revert_btn.setIcon(get_themed_icon("arrow-u-up-left.svg"))
        revert_btn.setIconSize(QSize(14, 14))
        revert_btn.setEnabled(False)
        close_btn = PushButton()
        close_btn.setText(tr("Close"))
        close_btn.setToolTip(tr("Close the permissions window"))
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
                preview.setText(tr("Unable to read current permissions"))
                FluentMessageBox.critical(
                    dlg,
                    tr("Permissions Error"),
                    o or tr("Permission read failed"),
                )
                return
            mode = explorer_service.parse_mode(o)
            if mode is None:
                preview.setText(tr("Unable to read current permissions"))
                FluentMessageBox.critical(
                    dlg,
                    tr("Permissions Error"),
                    tr("The device returned an invalid permission mode."),
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
            preview.setText(
                tr("Applying chmod {value0}  {value1}...").format(value0=mode, value1=full)
            )
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
                    preview.setText(tr('chmod failed for {value0}').format(value0=full))
                    FluentMessageBox.critical(
                        dlg,
                        tr("Permissions Error"),
                        output or tr("Permission update failed"),
                    )
                    return
                self._frame.status_bar.setText(
                    tr("Permissions updated for {value0}").format(value0=name)
                )
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
