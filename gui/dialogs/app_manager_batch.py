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
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import add_menu_action, apply_label_role, configure_button
from gui.styles.typography import FontRole


class AppManagerBatch:
    """组合进 AppManagerPage 的批量控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame

    @staticmethod
    def _action_label(action: str) -> str:
        """仅翻译展示名称，worker 继续接收原有动作键。"""
        return {"uninstall": tr("卸载"), "disable": tr("停用"), "enable": tr("启用")}.get(
            action, action
        )

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
        add_menu_action(menu, tr("应用详情"), callback=lambda: self._frame._show_details_for(pkg))
        menu.addSeparator()
        add_menu_action(menu, tr("启动应用"), callback=lambda: self._frame._launch(pkg))
        add_menu_action(
            menu, tr("强制停止"), callback=lambda: self._frame._modify_one("force_stop", pkg)
        )
        add_menu_action(
            menu, tr("清除数据"), callback=lambda: self._frame._modify_one("clear", pkg)
        )
        menu.addSeparator()
        add_menu_action(
            menu, tr("卸载"), callback=lambda: self._frame._modify_one("uninstall", pkg)
        )
        if atype in ("System", "Vendor"):
            add_menu_action(
                menu, tr("停用"), callback=lambda: self._frame._modify_one("disable", pkg)
            )
            add_menu_action(
                menu, tr("启用"), callback=lambda: self._frame._modify_one("enable", pkg)
            )
        menu.addSeparator()
        add_menu_action(menu, tr("备份"), callback=lambda: self._frame._backup_one(pkg))
        if self._frame._batch_workers or not self._frame._can_operate():
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self._frame.tree.mapToGlobal(pos))

    def _show_details_for(self, pkg):
        return self._frame.open_details(pkg)

    def _batch_action_blocked(self) -> bool:
        if not self._frame._can_operate():
            self._frame.status_bar.setText(
                tr("请在顶部设备栏勾选当前在线设备后执行应用操作。")
            )
            return True
        if not self._frame._batch_workers:
            return False
        self._frame.status_bar.setText(tr("正在执行批量操作，请等待完成。"))
        return True

    def _launch(self, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        worker = _app_manager.AppManagerWorker(
            self._frame.device_ip, "launch_app", package_name=pkg
        )
        self._submit_batch([worker], "launch", refresh=False)

    def _modify_one(self, action, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        operation = "clear_app" if action == "clear" else "modify_app"
        kwargs = {"package_name": pkg}
        if operation == "modify_app":
            kwargs["action"] = action
        worker = _app_manager.AppManagerWorker(self._frame.device_ip, operation, **kwargs)
        self._submit_batch([worker], action, refresh=action != "force_stop")

    @staticmethod
    def _global_save_dir() -> str:

        return AppSettings.instance().save_directory

    def _backup_one(self, pkg):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        sd = QFileDialog.getExistingDirectory(
            self._frame, tr("选择备份目录"), self._frame._global_save_dir()
        )
        if not sd or self._batch_action_blocked():
            return
        w = _app_manager.AppManagerWorker(
            self._frame.device_ip, "backup_app", package_name=pkg, save_dir=sd
        )
        self._submit_batch([w], "backup", refresh=False)

    def _deselect_all(self):
        self._frame.selected_packages.clear()
        self._frame._sync_selection_views()
        self._frame.log(tr("已取消全部应用选择。"))

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
                tr("未选择应用"),
                tr("请先选择应用。"),
            )
            return
        workers = [
            _app_manager.AppManagerWorker(
                self._frame.device_ip, "modify_app", action=action, package_name=pkg
            )
            for pkg in pkgs
        ]
        self._submit_batch(workers, action, refresh=True)

    def _submit_batch(self, workers, action: str, *, refresh: bool) -> None:
        """一个固定设备会话只运行一个业务 worker；待启动项不占线程或进程。"""
        frame = self._frame
        frame._batch_pending = list(workers)
        frame._batch_workers.update(workers)
        frame._batch_total = len(workers)
        frame._batch_action = action
        frame._batch_refresh = refresh
        for worker in workers:
            worker.log_message.connect(
                alive_forwarding_callback(frame, "log"), Qt.ConnectionType.QueuedConnection
            )
            worker.backup_progress.connect(
                alive_forwarding_callback(frame, "_log_backup_progress"),
                Qt.ConnectionType.QueuedConnection,
            )
            worker.finished.connect(
                alive_callback(frame, "_on_batch_worker_finished", worker),
                Qt.ConnectionType.QueuedConnection,
            )
            frame._track_worker(worker)
        frame.status_bar.setText(tr("正在执行批量操作，请等待完成。"))
        frame._update_selection_ui()
        self._start_next_worker()
        if not frame._batch_workers:
            self._finish_batch()

    def cancel_pending(self) -> None:
        """撤销未启动的任务；在途写操作仍归原设备，关闭方另行请求停止。"""
        frame = self._frame
        pending = getattr(frame, "_batch_pending", [])
        frame._batch_pending = []
        for worker in pending:
            worker.abort()
            frame._batch_workers.discard(worker)
            frame._prune_worker(worker)

    def _start_next_worker(self) -> None:
        """仅在上一 worker 完成且原设备仍可操作时消耗下一项。"""
        frame = self._frame
        if not frame._can_operate():
            self.cancel_pending()
            return
        pending = getattr(frame, "_batch_pending", [])
        while pending:
            worker = pending.pop(0)
            try:
                worker.start()
            except RuntimeError as exc:
                # 未启动的线程不会发送 finished；显式释放它，再推进其余任务。
                frame._batch_workers.discard(worker)
                frame._prune_worker(worker)
                frame._on_operation_feedback(
                    "error", f"Unable to start application operation: {type(exc).__name__}",
                )
            else:
                return

    def _on_batch_worker_finished(self, worker):
        """串行推进批次；所有终态（包括失败）汇合后至多刷新一次。"""
        frame = self._frame
        if worker not in frame._batch_workers:
            return
        frame._batch_workers.discard(worker)
        if frame._closing or not frame._can_operate():
            self.cancel_pending()
        else:
            self._start_next_worker()
        if frame._batch_workers:
            completed = frame._batch_total - len(frame._batch_workers)
            frame.status_bar.setText(tr("{value0}：已完成 {value1}/{value2}").format(
                value0=self._action_label(frame._batch_action), value1=completed,
                value2=frame._batch_total,
            ))
            frame._update_selection_ui()
            return
        self._finish_batch()

    def _finish_batch(self) -> None:
        """汇合已完成或启动失败的批次，只恢复准入，不合成业务成功。"""
        frame = self._frame
        refresh = getattr(frame, "_batch_refresh", True)
        frame._batch_action = ""
        frame._batch_total = 0
        frame._update_selection_ui()
        if frame._can_operate():
            frame.status_bar.setText(tr("就绪"))
            if refresh:
                frame._load_apps()

    def _backup_selected(self):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        pkgs = self._frame._get_selected_pkgs()
        if not pkgs:
            FluentMessageBox.warning(
                self._frame,
                tr("未选择应用"),
                tr("请先选择应用。"),
            )
            return
        sd = QFileDialog.getExistingDirectory(
            self._frame, tr("备份目录"), self._frame._global_save_dir()
        )
        if not sd or self._batch_action_blocked():
            return
        workers = [
            _app_manager.AppManagerWorker(
                self._frame.device_ip, "backup_app", package_name=pkg, save_dir=sd
            )
            for pkg in pkgs
        ]
        self._submit_batch(workers, "backup", refresh=False)

    def _restore_apps(self):
        from gui.dialogs import app_manager as _app_manager

        if self._batch_action_blocked():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self._frame, tr("选择备份 ZIP 文件"), "", tr("ZIP 文件 (*.zip)")
        )
        if not files or self._batch_action_blocked():
            return
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "restore_apps", file_paths=files)
        self._submit_batch([w], "restore", refresh=True)

    def _show_details(self):
        packages = self._frame._get_selected_pkgs()
        if not packages:
            FluentMessageBox.warning(
                self._frame,
                tr("未选择应用"),
                tr("请先选择一个应用。"),
            )
            return
        pkg = packages[0]
        if pkg:
            self._frame._show_details_for(pkg)

    def _create_preset(self):
        if not self._frame.selected_packages:
            FluentMessageBox.warning(
                self._frame,
                tr("未选择应用"),
                tr("请先选择应用。"),
            )
            return
        dlg = FluentDialog(self._frame)
        dlg.setWindowTitle(tr("创建预设"))
        dlg.setMinimumSize(380, 280 + dlg.TITLE_BAR_HEIGHT)
        dlg.resize(380, 280 + dlg.TITLE_BAR_HEIGHT)
        dlg.setFont(BaseStyles.font_for_role(FontRole.UI))
        lo = QVBoxLayout(dlg)
        lo.addWidget(apply_label_role(BodyLabel(tr("预设名称")), FontRole.UI))
        ni = LineEdit()
        lo.addWidget(ni)
        lo.addWidget(apply_label_role(BodyLabel(tr("作者（可选）")), FontRole.UI))
        ai = LineEdit()
        lo.addWidget(ai)
        lo.addWidget(apply_label_role(BodyLabel(tr("说明（可选）")), FontRole.UI))
        di = TextEdit()
        di.setMaximumHeight(60)
        lo.addWidget(di)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = PushButton()
        configure_button(
            cancel_button,
            text=tr("取消"),
            tooltip=tr("关闭并取消创建预设"),
        )
        create_button = PrimaryPushButton()
        configure_button(
            create_button,
            text=tr("创建"),
            tooltip=tr("创建此应用预设"),
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
        name = name or tr("新建预设")
        data = {
            "name": name,
            "author": author,
            "description": description,
            "selected_packages": sorted(list(self._frame.selected_packages)),
        }
        fp, _ = QFileDialog.getSaveFileName(
            self._frame, tr("保存预设"), name + ".json", "JSON (*.json)"
        )
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except (OSError, TypeError, ValueError) as exc:
                self._frame._report_preset_error("save", exc)
                return
            self._frame.log(
                tr("已保存预设“{value0}”，包含 {value1} 个应用。").format(
                    value0=name, value1=len(data["selected_packages"])
                )
            )

    def _load_preset(self):
        fp, _ = QFileDialog.getOpenFileName(self._frame, tr("加载预设"), "", "JSON (*.json)")
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
            self._frame.log(tr("预设没有包含应用。"))
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
            tr("已加载预设“{value0}”，选中 {value1} 个应用。").format(
                value0=data.get("name", "?"), value1=len(self._frame.selected_packages)
            )
        )

    @staticmethod
    def _validate_preset(data) -> None:
        if not isinstance(data, dict):
            raise ValueError(tr("预设根节点必须是 JSON 对象。"))
        packages = data.get("selected_packages")
        if not isinstance(packages, list) or any(
            not isinstance(package, str) or not package.strip() for package in packages
        ):
            raise ValueError(tr("预设 selected_packages 必须是有效包名列表。"))
        for field in ("name", "author", "description"):
            if field in data and not isinstance(data[field], str):
                raise ValueError(tr('预设字段 {value0} 必须是文本。').format(value0=field))

    def _report_preset_error(self, action: str, error: Exception) -> None:
        action_text = tr("保存") if action == "save" else tr("加载")
        message = tr('无法{value0}预设：{value1}').format(value0=action_text, value1=error)
        FluentMessageBox.critical(
            self._frame,
            tr("预设错误"),
            message,
        )
        self._frame.status_bar.setText(message)
        self._frame.log(message)

    def _track_worker(self, w):
        w.setParent(self._frame)
        if hasattr(w, "operation_feedback"):
            w.operation_feedback.connect(
                alive_forwarding_callback(self._frame, "_on_operation_feedback"),
                Qt.ConnectionType.QueuedConnection,
            )
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
