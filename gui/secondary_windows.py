"""二级窗口托管、事件过滤与实时设置刷新。"""

from PySide6.QtCore import QEvent, Qt

from core.settings_manager import AppSettings
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.lifecycle import (
    configure_independent_secondary_window,
    fit_secondary_window_to_owner_screen,
)
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.settings_dialog import SettingsDialog

from .styles import BaseStyles


def _debug_log(owner, event: str, **fields) -> None:
    """转发开发诊断日志到主窗口模块，避免循环导入。"""
    from gui.main_frame import _debug_log as _impl

    _impl(owner, event, **fields)


class SecondaryWindowHost:
    """组合进 MainFrame 的二级窗口托管器，通过 ``self._frame`` 访问主窗口。"""

    def __init__(self, frame):
        self._frame = frame

    def _show_about_dialog(self):
        """显示关于对话框。"""
        _debug_log(self._frame, "ui.toolbar", action="about", phase="requested")
        dialog = AboutDialog(self._frame)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.installEventFilter(self._frame)
        _debug_log(self._frame, "ui.secondary_window", dialog="AboutDialog", phase="opened")
        result = dialog.exec_()
        _debug_log(
            self._frame,
            "ui.secondary_window",
            dialog="AboutDialog",
            phase="closed",
            result=result,
        )

    def _show_app_manager(self):
        """为每个已选设备打开应用管理窗口。"""
        _debug_log(self._frame, "ui.toolbar", action="app_manager", phase="requested")
        self._frame._show_device_dialogs(AppManagerDialog)

    def _show_file_explorer(self):
        """为每个已选设备打开文件浏览窗口。"""
        _debug_log(self._frame, "ui.toolbar", action="file_explorer", phase="requested")
        self._frame._show_device_dialogs(FileExplorerDialog)

    def _show_logcat(self):
        """为每个已选设备打开实时 Logcat 窗口。"""
        _debug_log(self._frame, "ui.toolbar", action="live_logcat", phase="requested")
        self._frame._show_device_dialogs(
            LiveLogcatDialog,
            task_supervisor=self._frame.task_supervisor,
            log_service=getattr(self._frame, "log_service", None),
        )

    def _show_performance_monitor(self):
        """打开原生性能采集启动对话框。"""
        from gui.dialogs.performance_launcher import PerformanceLauncherDialog

        _debug_log(self._frame, "ui.toolbar", action="performance", phase="requested")
        devices = self._frame.left_panel.selected_devices
        if not devices:
            _debug_log(
                self._frame,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="blocked",
                reason="no_device",
            )
            self._frame.log_service.log("WARNING", "No device selected")
            return
        if len(devices) != 1:
            _debug_log(
                self._frame,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="blocked",
                reason="ambiguous_device_selection",
            )
            self._frame.log_service.log(
                "WARNING",
                "Performance requires exactly one selected device",
            )
            return
        device_ip = devices[0]
        try:
            package_name = self._frame.left_panel.current_package_text()
        except RuntimeError:
            package_name = ""
        dlg = self._frame._find_active_dialog(PerformanceLauncherDialog, device_ip or "default")
        if dlg:
            _debug_log(
                self._frame,
                "ui.secondary_window",
                dialog="PerformanceLauncherDialog",
                phase="reused",
            )
            self._show_fitted_dialog(dlg)
            return
        dlg = self._frame._register_dialog(
            PerformanceLauncherDialog(
                device_ip=device_ip,
                package_name=package_name,
            ),
            PerformanceLauncherDialog,
            device_ip or "default",
        )
        dlg.show()

    def _show_device_dialogs(self, dialog_cls, **dialog_kwargs):
        """为选中设备创建由主窗口托管的非模态窗口。"""
        devices = self._frame.left_panel.selected_devices
        if not devices:
            _debug_log(
                self._frame,
                "ui.secondary_window",
                dialog=dialog_cls.__name__,
                phase="blocked",
                reason="no_device",
            )
            self._frame.log_service.log("WARNING", "No device selected")
            return
        for ip in devices:
            dlg = self._frame._find_active_dialog(dialog_cls, ip)
            if dlg:
                _debug_log(
                    self._frame,
                    "ui.secondary_window",
                    dialog=dialog_cls.__name__,
                    phase="reused",
                )
                self._show_fitted_dialog(dlg)
                continue
            dlg = self._frame._register_dialog(
                dialog_cls(device_ip=ip, **dialog_kwargs),
                dialog_cls,
                ip,
            )
            dlg.show()

    def _register_dialog(self, dialog, dialog_cls=None, device_ip=None):
        configure_independent_secondary_window(dialog)
        fit_secondary_window_to_owner_screen(dialog, self._frame)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.installEventFilter(self._frame)
        dialog_name = dialog_cls.__name__ if dialog_cls is not None else type(dialog).__name__
        if dialog_cls is not None:
            dialog.setProperty("dialog_class", dialog_name)
        if device_ip is not None:
            dialog.setProperty("device_ip", device_ip)
        self._frame._active_dialogs.append(dialog)
        _debug_log(
            self._frame,
            "ui.secondary_window",
            active_count=len(self._frame._active_dialogs),
            dialog=dialog_name,
            phase="created",
        )
        dialog.destroyed.connect(
            lambda _obj=None, dlg=dialog, name=dialog_name: self._frame._on_dialog_destroyed(
                dlg,
                name,
            )
        )
        return dialog

    def _show_fitted_dialog(self, dialog) -> None:
        """复用二级窗口前重新限制几何，并将其激活。"""

        try:
            fit_secondary_window_to_owner_screen(dialog, self._frame)
        except (AttributeError, RuntimeError, TypeError):
            pass
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _find_active_dialog(self, dialog_cls, device_ip):
        survivors = []
        match = None
        for dialog in self._frame._active_dialogs:
            try:
                if getattr(dialog, "_closing", False):
                    survivors.append(dialog)
                    continue
                same_dialog = (
                    dialog.property("dialog_class") == dialog_cls.__name__
                    and dialog.property("device_ip") == device_ip
                )
            except RuntimeError:
                continue
            survivors.append(dialog)
            if same_dialog and match is None:
                match = dialog
        self._frame._active_dialogs = survivors
        return match

    def _forget_dialog(self, dialog):
        try:
            self._frame._active_dialogs.remove(dialog)
        except ValueError:
            pass

    def _on_dialog_destroyed(self, dialog, dialog_name: str):
        """移除已销毁窗口并记录二级窗口关闭完成。"""
        self._frame._forget_dialog(dialog)
        _debug_log(
            self._frame,
            "ui.secondary_window",
            active_count=len(self._frame._active_dialogs),
            dialog=dialog_name,
            phase="closed",
        )

    def eventFilter(self, watched, event):
        """记录受主窗口托管的二级窗口关闭请求。"""
        if event.type() == QEvent.Type.Close:
            try:
                dialog_name = watched.property("dialog_class") or type(watched).__name__
            except RuntimeError:
                dialog_name = type(watched).__name__
            _debug_log(
                self._frame,
                "ui.secondary_window",
                dialog=dialog_name,
                phase="close_requested",
            )
            return False
        return None

    def _show_settings(self):
        """显示或激活非模态的单实例设置窗口。"""
        _debug_log(self._frame, "ui.toolbar", action="settings", phase="requested")
        dialog = self._frame._find_active_dialog(SettingsDialog, "global")
        if dialog:
            self._show_fitted_dialog(dialog)
            return
        dialog = self._frame._register_dialog(SettingsDialog(self._frame), SettingsDialog, "global")
        dialog.continuous_scan_toggled.connect(self._frame.set_continuous_scan)
        dialog.log_max_lines_changed.connect(self._frame.log_panel.set_max_lines)
        dialog.save_directory_changed.connect(lambda _path: self._frame._refresh_save_path())
        dialog.settings_applied.connect(self._frame._refresh_live_settings)
        _debug_log(self._frame, "ui.secondary_window", dialog="SettingsDialog", phase="opened")
        dialog.show()

    def _refresh_active_dialog_themes(self):
        survivors = []
        for dialog in list(getattr(self._frame, "_active_dialogs", [])):
            try:
                if hasattr(dialog, "_sync_theme_state"):
                    dialog._sync_theme_state(force=True)
                elif hasattr(dialog, "_apply_theme"):
                    dialog._apply_theme(BaseStyles.current_theme())
                survivors.append(dialog)
            except RuntimeError:
                continue
        self._frame._active_dialogs = survivors

    def _refresh_live_settings(self) -> None:
        """让主窗口和已加载页签重新读取可即时生效的设置。"""

        settings = AppSettings.instance()
        always_on_top = bool(settings.get("always_on_top", False))
        if always_on_top != self._frame._always_on_top:
            self._frame.set_always_on_top(always_on_top)
        else:
            self._frame._refresh_always_on_top_button()
        self._frame.log_panel.set_max_lines(settings.get("log_max_lines", 2000))
        refresh_panels = getattr(self._frame.left_panel, "refresh_from_settings", None)
        if callable(refresh_panels):
            refresh_panels()
        self._frame._refresh_save_path()
