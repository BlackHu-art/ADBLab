"""应用管理器批量控制器 — 单项/批量应用操作、备份恢复与预设管理。"""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, LineEdit, PrimaryPushButton, PushButton, TextEdit

from core.settings_manager import AppSettings
from gui.dialogs.fluent_dialog import FluentDialog, FluentMessageBox
from gui.dialogs.lifecycle import (
    alive_callback,
    alive_forwarding_callback,
    fit_secondary_window_to_owner_screen,
    is_qobject_alive,
)
from gui.styles import BaseStyles
from gui.styles.fluent import add_menu_action, apply_label_role, configure_button
from gui.styles.typography import FontRole


class AppManagerBatch:
    """组合进 AppManagerPage 的批量控制器，通过 ``self._frame`` 访问页面。"""

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
        add_menu_action(menu, "App Details", callback=lambda: self._frame._show_details_for(pkg))
        menu.addSeparator()
        add_menu_action(menu, "Launch App", callback=lambda: self._frame._launch(pkg))
        add_menu_action(
            menu, "Force Stop", callback=lambda: self._frame._modify_one("force_stop", pkg)
        )
        add_menu_action(menu, "Clear Data", callback=lambda: self._frame._modify_one("clear", pkg))
        menu.addSeparator()
        add_menu_action(
            menu, "Uninstall", callback=lambda: self._frame._modify_one("uninstall", pkg)
        )
        if atype in ("System", "Vendor"):
            add_menu_action(
                menu, "Disable", callback=lambda: self._frame._modify_one("disable", pkg)
            )
            add_menu_action(menu, "Enable", callback=lambda: self._frame._modify_one("enable", pkg))
        menu.addSeparator()
        add_menu_action(menu, "Backup", callback=lambda: self._frame._backup_one(pkg))
        if self._frame._batch_workers or not getattr(
            self._frame, "_device_connected", True
        ):
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self._frame.tree.mapToGlobal(pos))

    def _show_details_for(self, pkg):
        return self._frame.open_details(pkg)

    def _batch_action_blocked(self) -> bool:
        if not getattr(self._frame, "_device_connected", True):
            self._frame.status_bar.setText(
                "Device offline — reconnect it before starting an application action."
            )
            return True
        if not self._frame._batch_workers:
            return False
        self._frame.status_bar.setText("A batch operation is in progress; wait for it to finish.")
        return True

    def _launch(self, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "launch_app", package_name=pkg)
        w.log_message.connect(
            alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
        )
        self._frame._track_worker(w)
        w.start()

    def _modify_one(self, action, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        if action == "force_stop":
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action="force_stop", package_name=pkg
            )
            w.log_message.connect(
                alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            self._frame._track_worker(w)
            w.start()
        elif action == "clear":
            w = _app_manager.AppManagerWorker(self._frame.device_ip, "clear_app", package_name=pkg)
            w.log_message.connect(
                alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            self._frame._track_worker(w)
            w.start()
        else:
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action=action, package_name=pkg
            )
            w.log_message.connect(
                alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            w.operation_done.connect(
                alive_callback(self._frame, "_load_apps"), Qt.ConnectionType.QueuedConnection
            )
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
        w.log_message.connect(
            alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
        )
        w.backup_progress.connect(
            alive_forwarding_callback(self._frame, "_log_backup_progress"),
            Qt.ConnectionType.QueuedConnection,
        )
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
            FluentMessageBox.warning(
                self._frame,
                "No Selection",
                "No apps selected.",
            )
            return
        workers = []
        for pkg in pkgs:
            w = _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action=action, package_name=pkg
            )
            w.log_message.connect(
                alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            w.finished.connect(
                alive_callback(self._frame, "_on_batch_worker_finished", w),
                Qt.ConnectionType.QueuedConnection,
            )
            self._frame._track_worker(w)
            workers.append(w)

        self._frame._batch_workers.update(workers)
        self._frame._batch_total = len(workers)
        self._frame._batch_action = action
        self._frame.status_bar.setText(f"{action.title()}: 0/{self._frame._batch_total} completed")
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
            self._frame.status_bar.setText(
                f"{self._frame._batch_action.title()}: "
                f"{completed}/{self._frame._batch_total} completed"
            )
            self._frame._update_selection_ui()
            return

        action = self._frame._batch_action
        total = self._frame._batch_total
        self._frame._batch_action = ""
        self._frame._batch_total = 0
        self._frame.status_bar.setText(
            f"{action.title()} completed for {total} apps; refreshing..."
        )
        self._frame._update_selection_ui()
        self._frame._load_apps()

    def _backup_selected(self):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        pkgs = self._frame._get_selected_pkgs()
        if not pkgs:
            FluentMessageBox.warning(
                self._frame,
                "No Selection",
                "No apps selected.",
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
            w.log_message.connect(
                alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            w.backup_progress.connect(
                alive_forwarding_callback(self._frame, "_log_backup_progress"),
                Qt.ConnectionType.QueuedConnection,
            )
            self._frame._track_worker(w)
            w.start()

    def _restore_apps(self):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self._frame, "Select Backup ZIP(s)", "", "ZIP Files (*.zip)"
        )
        if not files:
            return
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "restore_apps", file_paths=files)
        w.log_message.connect(
            alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
        )
        w.backup_progress.connect(
            alive_forwarding_callback(self._frame, "_log_backup_progress"),
            Qt.ConnectionType.QueuedConnection,
        )
        w.operation_done.connect(
            alive_callback(self._frame, "_load_apps"), Qt.ConnectionType.QueuedConnection
        )
        self._frame._track_worker(w)
        w.start()

    def _show_details(self):
        packages = self._frame._get_selected_pkgs()
        if not packages:
            FluentMessageBox.warning(
                self._frame,
                "No Selection",
                "No app selected.",
            )
            return
        pkg = packages[0]
        if pkg:
            self._frame._show_details_for(pkg)

    def _create_preset(self):
        if not self._frame.selected_packages:
            FluentMessageBox.warning(
                self._frame,
                "No Selection",
                "Select apps first.",
            )
            return
        dlg = FluentDialog(self._frame)
        dlg.setWindowTitle("Create Preset")
        dlg.setMinimumSize(380, 280 + dlg.TITLE_BAR_HEIGHT)
        dlg.resize(380, 280 + dlg.TITLE_BAR_HEIGHT)
        dlg.setFont(BaseStyles.font_for_role(FontRole.UI))
        lo = QVBoxLayout(dlg)
        lo.addWidget(apply_label_role(BodyLabel("Preset Name:"), FontRole.UI))
        ni = LineEdit()
        lo.addWidget(ni)
        lo.addWidget(apply_label_role(BodyLabel("Author (optional):"), FontRole.UI))
        ai = LineEdit()
        lo.addWidget(ai)
        lo.addWidget(apply_label_role(BodyLabel("Description (optional):"), FontRole.UI))
        di = TextEdit()
        di.setMaximumHeight(60)
        lo.addWidget(di)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = PushButton()
        configure_button(
            cancel_button,
            text="Cancel",
            tooltip="Close without creating a preset",
        )
        create_button = PrimaryPushButton()
        configure_button(
            create_button,
            text="Create",
            tooltip="Create this application preset",
        )
        create_button.setDefault(True)
        cancel_button.clicked.connect(dlg.reject)
        create_button.clicked.connect(dlg.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(create_button)
        lo.addLayout(button_row)
        dlg.finalize_fluent_layout(lo)
        fit_secondary_window_to_owner_screen(
            dlg,
            self._frame,
            minimum_floor=dlg.minimumSize(),
        )
        accepted = False
        preset_fields: tuple[str, str, str] | None = None
        try:
            accepted = bool(dlg.exec())
            if accepted:
                preset_fields = (
                    ni.text().strip(),
                    ai.text().strip(),
                    di.toPlainText().strip(),
                )
        finally:
            # 模态 exec 返回后先复制控件值，再显式排队释放，避免关闭即销毁导致悬空访问。
            dlg.deleteLater()
        if not accepted or preset_fields is None:
            return
        name, author, description = preset_fields
        name = name or "New Preset"
        data = {
            "name": name,
            "author": author,
            "description": description,
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
        FluentMessageBox.critical(
            self._frame,
            "Preset Error",
            message,
        )
        self._frame.status_bar.setText(message)
        self._frame.log(message)

    def _track_worker(self, w):
        w.setParent(self._frame)
        w.finished.connect(
            alive_callback(self._frame, "_prune_worker", w), Qt.ConnectionType.QueuedConnection
        )
        self._frame._workers.append(w)

    def _prune_worker(self, w):
        if w in self._frame._workers:
            self._frame._workers.remove(w)
        if is_qobject_alive(w) and hasattr(w, "deleteLater"):
            w.deleteLater()
        maybe_finish = getattr(self._frame, "_maybe_finish_dispose", None)
        if callable(maybe_finish):
            maybe_finish()
