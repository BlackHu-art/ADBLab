"""应用管理器批量控制器 — 单项/批量应用操作、备份恢复与预设管理。"""

import json

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from core.settings_manager import AppSettings
from gui.dialogs.app_manager_details import AppDetailsDialog
from gui.dialogs.lifecycle import (
    alive_callback,
    alive_forwarding_callback,
    fit_secondary_window_to_owner_screen,
    is_qobject_alive,
)
from gui.styles import BaseStyles
from gui.styles.typography import FontRole


class AppManagerBatch:
    """组合进 AppManagerDialog 的批量控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _context_menu(self, pos):
        idx = self._frame.tree.indexAt(pos)
        if not idx.isValid():
            return
        src = self._frame.proxy.mapToSource(idx)
        row = src.row()
        pkg_item = self._frame.model.item(row, 2)
        atype_item = self._frame.model.item(row, 5)
        if pkg_item is None or atype_item is None:
            return
        pkg = pkg_item.text()
        atype = atype_item.text()
        menu = self._frame._create_context_menu()
        menu.addAction("App Details", lambda: self._frame._show_details_for(pkg))
        menu.addSeparator()
        menu.addAction("Launch App", lambda: self._frame._launch(pkg))
        menu.addAction("Force Stop", lambda: self._frame._modify_one("force_stop", pkg))
        menu.addAction("Clear Data", lambda: self._frame._modify_one("clear", pkg))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self._frame._modify_one("uninstall", pkg))
        if atype in ("System", "Vendor"):
            menu.addAction("Disable", lambda: self._frame._modify_one("disable", pkg))
            menu.addAction("Enable", lambda: self._frame._modify_one("enable", pkg))
        menu.addSeparator()
        menu.addAction("Backup", lambda: self._frame._backup_one(pkg))
        if self._frame._batch_workers:
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self._frame.tree.mapToGlobal(pos))

    def _show_details_for(self, pkg):
        if self._batch_action_blocked():
            return None
        existing = self._frame._detail_dialogs.get(pkg)
        if is_qobject_alive(existing):
            fit_secondary_window_to_owner_screen(existing, self._frame)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        dlg = AppDetailsDialog(self._frame, self._frame.device_ip, pkg)
        fit_secondary_window_to_owner_screen(dlg, self._frame)
        self._frame._detail_dialogs[pkg] = dlg
        dlg.finished.connect(alive_callback(self._frame, "_forget_detail_dialog", pkg, dlg))
        dlg.destroyed.connect(alive_callback(self._frame, "_forget_detail_dialog", pkg, dlg))
        dlg.show()
        return dlg

    def _forget_detail_dialog(self, pkg, dialog):
        if self._frame._detail_dialogs.get(pkg) is dialog:
            self._frame._detail_dialogs.pop(pkg, None)

    def _batch_action_blocked(self) -> bool:
        if not self._frame._batch_workers:
            return False
        self._frame.status_bar.showMessage(
            "A batch operation is in progress; wait for it to finish."
        )
        return True

    def _launch(self, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "launch_app", package_name=pkg)
        w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
        self._frame._track_worker(w)
        w.start()

    def _modify_one(self, action, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        if not self._frame._confirm_dangerous_action(action, 1):
            return
        if action == "force_stop":
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action="force_stop", package_name=pkg
            )
            w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
            self._frame._track_worker(w)
            w.start()
        elif action == "clear":
            w = _app_manager.AppManagerWorker(self._frame.device_ip, "clear_app", package_name=pkg)
            w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
            self._frame._track_worker(w)
            w.start()
        else:
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action=action, package_name=pkg
            )
            w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
            w.operation_done.connect(alive_callback(self._frame, "_load_apps"))
            self._frame._track_worker(w)
            w.start()

    @staticmethod
    def _global_save_dir() -> str:

        return AppSettings.instance().save_directory

    def _backup_one(self, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        sd = QFileDialog.getExistingDirectory(
            self._frame, "Select Backup Directory", self._frame._global_save_dir()
        )
        if not sd:
            return
        w = _app_manager.AppManagerWorker(
            self._frame.device_ip, "backup_app", package_name=pkg, save_dir=sd
        )
        w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
        w.backup_progress.connect(alive_forwarding_callback(self._frame, "_log_backup_progress"))
        self._frame._track_worker(w)
        w.start()

    def _deselect_all(self):
        self._frame.selected_packages.clear()
        self._frame._sync_selection_views()
        self._frame.log("Deselected all.")

    def _log_backup_progress(self, progress, message) -> None:
        self._frame.log(f"[{progress}] {message}")

    def _get_selected_pkgs(self):
        return sorted(self._frame.selected_packages)

    def _modify_selected(self, action):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        pkgs = self._frame._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(
                self._frame,
                "No Selection",
                "No apps selected.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        if not self._frame._confirm_dangerous_action(action, len(pkgs)):
            return
        workers = []
        for pkg in pkgs:
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action=action, package_name=pkg
            )
            w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
            w.finished.connect(alive_callback(self._frame, "_on_batch_worker_finished", w))
            self._frame._track_worker(w)
            workers.append(w)

        self._frame._batch_workers.update(workers)
        self._frame._batch_total = len(workers)
        self._frame._batch_action = action
        self._frame.status_bar.showMessage(
            f"{action.title()}: 0/{self._frame._batch_total} completed"
        )
        self._frame._update_selection_ui()
        for w in workers:
            w.start()

    def _on_batch_worker_finished(self, worker):
        """等待当前批次全部结束后统一刷新一次应用列表。"""

        if worker not in self._frame._batch_workers:
            return
        self._frame._batch_workers.discard(worker)
        if self._frame._closing:
            return
        remaining = len(self._frame._batch_workers)
        completed = self._frame._batch_total - remaining
        if remaining:
            self._frame.status_bar.showMessage(
                f"{self._frame._batch_action.title()}: "
                f"{completed}/{self._frame._batch_total} completed"
            )
            self._frame._update_selection_ui()
            return

        action = self._frame._batch_action
        total = self._frame._batch_total
        self._frame._batch_action = ""
        self._frame._batch_total = 0
        self._frame.status_bar.showMessage(
            f"{action.title()} completed for {total} apps; refreshing..."
        )
        self._frame._update_selection_ui()
        self._frame._load_apps()

    def _confirm_dangerous_action(self, action: str, target_count: int) -> bool:
        """兼容占位：危险操作不再弹窗确认，直接放行。"""

        del action, target_count
        return True

    def _backup_selected(self):
        from gui.dialogs import app_manager as _app_manager

        pkgs = self._frame._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(
                self._frame,
                "No Selection",
                "No apps selected.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        sd = QFileDialog.getExistingDirectory(
            self._frame, "Backup Directory", self._frame._global_save_dir()
        )
        if not sd:
            return
        for pkg in pkgs:
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "backup_app", package_name=pkg, save_dir=sd
            )
            w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
            w.backup_progress.connect(
                alive_forwarding_callback(self._frame, "_log_backup_progress")
            )
            self._frame._track_worker(w)
            w.start()

    def _restore_apps(self):
        from gui.dialogs import app_manager as _app_manager

        files, _ = QFileDialog.getOpenFileNames(
            self._frame, "Select Backup ZIP(s)", "", "ZIP Files (*.zip)"
        )
        if not files:
            return
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "restore_apps", file_paths=files)
        w.log_message.connect(alive_forwarding_callback(self._frame, "log"))
        w.backup_progress.connect(alive_forwarding_callback(self._frame, "_log_backup_progress"))
        w.operation_done.connect(alive_callback(self._frame, "_load_apps"))
        self._frame._track_worker(w)
        w.start()

    def _show_details(self):
        packages = self._frame._get_selected_pkgs()
        if not packages:
            QMessageBox.warning(
                self._frame,
                "No Selection",
                "No app selected.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        pkg = packages[0]
        if pkg:
            self._frame._show_details_for(pkg)

    def _create_preset(self):
        if not self._frame.selected_packages:
            QMessageBox.warning(
                self._frame,
                "No Selection",
                "Select apps first.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        dlg = QDialog(self._frame)
        dlg.setWindowTitle("Create Preset")
        dlg.setMinimumSize(380, 280)
        dlg.resize(380, 280)
        dlg.setFont(BaseStyles.font_for_role(FontRole.UI))
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
        btns.button(QDialogButtonBox.StandardButton.Ok).setToolTip("Create this application preset")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Close without creating a preset"
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lo.addWidget(btns)
        fit_secondary_window_to_owner_screen(
            dlg,
            self._frame,
            minimum_floor=dlg.minimumSize(),
        )
        if not dlg.exec():
            return
        name = ni.text().strip() or "New Preset"
        data = {
            "name": name,
            "author": ai.text().strip(),
            "description": di.toPlainText().strip(),
            "selected_packages": sorted(list(self._frame.selected_packages)),
        }
        fp, _ = QFileDialog.getSaveFileName(
            self._frame, "Save Preset", name + ".json", "JSON (*.json)"
        )
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except (OSError, TypeError, ValueError) as exc:
                self._frame._report_preset_error("save", exc)
                return
            self._frame.log(f"Preset '{name}' saved ({len(data['selected_packages'])} apps).")

    def _load_preset(self):
        fp, _ = QFileDialog.getOpenFileName(self._frame, "Load Preset", "", "JSON (*.json)")
        if not fp:
            return
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            self._frame._validate_preset(data)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self._frame._report_preset_error("load", exc)
            return
        pkgs = set(data.get("selected_packages", []))
        if not pkgs:
            self._frame.log("Preset empty.")
            return
        available_packages = set()
        for r in range(self._frame.model.rowCount()):
            pkg_item = self._frame.model.item(r, 2)
            if pkg_item is None:
                continue
            p = pkg_item.text()
            if p:
                available_packages.add(p)
        self._frame.selected_packages.clear()
        self._frame.selected_packages.update(pkgs & available_packages)
        self._frame._sync_selection_views()
        self._frame.log(
            f"Loaded preset '{data.get('name', '?')}' ({len(self._frame.selected_packages)} apps)."
        )

    @staticmethod
    def _validate_preset(data) -> None:
        if not isinstance(data, dict):
            raise ValueError("Preset root must be a JSON object.")
        packages = data.get("selected_packages")
        if not isinstance(packages, list) or any(
            not isinstance(package, str) or not package.strip() for package in packages
        ):
            raise ValueError("Preset selected_packages must be a list of package names.")
        for field in ("name", "author", "description"):
            if field in data and not isinstance(data[field], str):
                raise ValueError(f"Preset {field} must be text.")

    def _report_preset_error(self, action: str, error: Exception) -> None:
        message = f"Unable to {action} preset: {error}"
        QMessageBox.critical(
            self._frame,
            "Preset Error",
            message,
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.NoButton,
        )
        self._frame.status_bar.showMessage(message)
        self._frame.log(message)

    def _track_worker(self, w):
        w.setParent(self._frame)
        w.finished.connect(alive_callback(self._frame, "_prune_worker", w))
        self._frame._workers.append(w)

    def _prune_worker(self, w):
        if self._frame._closing:
            return
        if w in self._frame._workers:
            self._frame._workers.remove(w)
        if is_qobject_alive(w) and hasattr(w, "deleteLater"):
            w.deleteLater()
