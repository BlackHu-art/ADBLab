"""顶部工具栏构建、快捷方式与保存路径省略展示。"""

import os
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
)

from gui.styles.icon_loader import get_themed_icon

from .styles import BaseStyles, FontRole


def _debug_log(owner, event: str, **fields) -> None:
    """转发开发诊断日志到主窗口模块，避免循环导入。"""
    from gui.main_frame import _debug_log as _impl

    _impl(owner, event, **fields)


class ToolbarController:
    """组合进 MainFrame 的顶部工具栏控制器，通过 ``self._frame`` 访问主窗口。"""

    _OVERFLOW_PRIORITY = (
        "save_path",
        "cmd",
        "performance",
        "logcat",
        "file_explorer",
        "app_mgr",
        "clear",
        "about",
        "theme",
        "always_on_top",
        "settings",
    )
    _WINDOW_CONTROL_PRIORITY = ("minimize", "maximize", "exit")

    def __init__(self, frame):
        self._frame = frame

    def _create_toolbar(self) -> QFrame:
        """创建包含功能入口、主题切换和窗口控制的顶部工具栏。"""
        bar = QFrame()
        self._frame._toolbar = bar
        bar.setObjectName("toolbar")
        bar.setMinimumHeight(BaseStyles.control_height(minimum=32, padding=8))
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bar.setStyleSheet(BaseStyles.TOOLBAR_STYLE())

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(4)

        self._frame._toolbar_title = QLabel("ADBLab")
        self._frame._toolbar_title.setObjectName("toolbarTitle")
        layout.addWidget(self._frame._toolbar_title)

        self._frame._toolbar_actions = {}
        self._frame._toolbar_action_buttons = {}
        action_specs = (
            (
                "app_mgr",
                "App Manager",
                "squares-four.svg",
                "Manage apps on the selected device",
                self._frame._show_app_manager,
                False,
            ),
            (
                "file_explorer",
                "File Explorer",
                "folder-open.svg",
                "Browse files on the selected device",
                self._frame._show_file_explorer,
                False,
            ),
            (
                "logcat",
                "Live Logcat",
                "scroll.svg",
                "View live logs from the selected device",
                self._frame._show_logcat,
                False,
            ),
            (
                "performance",
                "Performance",
                "speedometer.svg",
                "Configure and start performance monitoring",
                self._frame._show_performance_monitor,
                False,
            ),
            (
                "settings",
                "Settings",
                "gear.svg",
                "Configure application preferences",
                self._frame._show_settings,
                False,
            ),
            (
                "cmd",
                "CMD",
                "terminal-window.svg",
                "Open a command prompt in the ADB tools folder",
                self._frame._open_cmd,
                False,
            ),
            (
                "save_path",
                "Change default save directory",
                "folder.svg",
                "Choose the default output directory",
                self._frame._on_save_path_clicked,
                False,
            ),
            (
                "clear",
                "Clear Log",
                "broom.svg",
                "Remove all messages from the operation log",
                self._frame.clear_log,
                False,
            ),
            (
                "about",
                "About",
                "info.svg",
                "Show application version and project information",
                self._frame._show_about_dialog,
                False,
            ),
            (
                "theme",
                "Toggle Light/Dark theme",
                "circle-half-tilt.svg",
                "Switch between light and dark themes",
                self._frame._toggle_theme,
                False,
            ),
            (
                "always_on_top",
                "Pin on top",
                "push-pin.svg",
                "Keep the main window above other windows",
                self._frame.set_always_on_top,
                True,
            ),
            (
                "minimize",
                "Minimize",
                "minus.svg",
                "Hide the main window in the taskbar",
                self._frame._minimize_window,
                False,
            ),
            (
                "maximize",
                "Maximize",
                "square.svg",
                "Expand the main window to fill the screen",
                self._frame._toggle_maximize_restore,
                False,
            ),
            (
                "exit",
                "Exit",
                "x.svg",
                "Close ADBLab",
                self._frame._request_application_close,
                False,
            ),
        )
        for key, label, icon_name, tooltip, callback, checkable in action_specs:
            self._frame._create_toolbar_action(
                key,
                label,
                icon_name,
                callback,
                tooltip=tooltip,
                checkable=checkable,
                checked=self._frame._always_on_top if key == "always_on_top" else False,
            )
        self._frame._toolbar_action_order = tuple(spec[0] for spec in action_specs)
        self._frame._toolbar_overflow_keys = ()

        self._frame.tb_app_mgr = self._frame._create_toolbar_action_button("app_mgr")
        self._frame.tb_file_explorer = self._frame._create_toolbar_action_button("file_explorer")
        self._frame.tb_logcat = self._frame._create_toolbar_action_button("logcat")
        self._frame.tb_performance = self._frame._create_toolbar_action_button("performance")
        self._frame.tb_settings = self._frame._create_toolbar_action_button("settings")
        self._frame.tb_cmd = self._frame._create_toolbar_action_button("cmd")
        self._frame._tb_save_btn = self._frame._create_toolbar_action_button("save_path")
        self._frame._tb_save_btn.setObjectName("savePathBtn")
        self._frame._tb_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._frame._save_path_label = QLabel()
        self._frame._save_path_label.setObjectName("savePathLabel")
        self._frame._save_path_label.setMinimumWidth(0)
        self._frame._save_path_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )

        layout.addWidget(self._frame.tb_app_mgr)
        layout.addWidget(self._frame.tb_file_explorer)
        layout.addWidget(self._frame.tb_logcat)
        layout.addWidget(self._frame.tb_performance)
        layout.addWidget(self._frame.tb_settings)
        layout.addWidget(self._frame.tb_cmd)
        layout.addWidget(self._frame._tb_save_btn)
        layout.addWidget(self._frame._save_path_label)
        layout.addStretch()

        self._frame.tb_clear = self._frame._create_toolbar_action_button("clear")
        self._frame.tb_about = self._frame._create_toolbar_action_button("about")
        self._frame.theme_btn = self._frame._create_toolbar_action_button(
            "theme",
            icon_size=QSize(16, 16),
        )
        self._frame.tb_always_on_top = self._frame._create_toolbar_action_button("always_on_top")
        self._frame._refresh_always_on_top_button()
        self._frame.tb_minimize = self._frame._create_toolbar_action_button("minimize")
        self._frame.tb_maximize = self._frame._create_toolbar_action_button("maximize")
        self._frame.tb_exit = self._frame._create_toolbar_action_button("exit")
        self._frame.tb_exit.setObjectName("exit_btn")

        for btn in (
            self._frame.tb_clear,
            self._frame.tb_about,
            self._frame.theme_btn,
            self._frame.tb_always_on_top,
        ):
            layout.addWidget(btn)

        layout.addWidget(self._frame.tb_minimize)
        layout.addWidget(self._frame.tb_maximize)
        layout.addWidget(self._frame.tb_exit)

        self._frame._toolbar_path_layout_timer = QTimer(self._frame)
        self._frame._toolbar_path_layout_timer.setSingleShot(True)
        self._frame._toolbar_path_layout_timer.timeout.connect(
            self._frame._update_toolbar_path_display
        )
        bar.installEventFilter(self._frame)

        self._frame._refresh_toolbar_metrics()
        self._frame._refresh_save_path()

        return bar

    def _create_toolbar_action(
        self,
        key: str,
        label: str,
        icon_name: str,
        callback: Callable,
        *,
        tooltip: str,
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        """创建业务入口唯一持有的 QAction。"""

        action = QAction(get_themed_icon(icon_name), label, self._frame)
        action.setToolTip(tooltip)
        action.setProperty("functionalToolTip", tooltip)
        action.setProperty("iconName", icon_name)
        action.setProperty("accessibleName", label)
        action.setProperty("accessibleDescription", tooltip)
        action.setCheckable(checkable)
        action.setChecked(checked)
        if checkable:
            action.triggered.connect(callback)
        else:
            action.triggered.connect(lambda _checked=False, handler=callback: handler())
        action.changed.connect(lambda key=key: self._frame._sync_toolbar_action_button(key))
        self._frame._toolbar_actions[key] = action
        return action

    def _create_toolbar_action_button(
        self,
        key: str,
        *,
        icon_size: QSize = QSize(14, 14),
    ) -> QToolButton:
        action = self._frame._toolbar_actions[key]
        button = self._frame._create_toolbar_btn(action.toolTip(), "", action=action)
        button.setIconSize(icon_size)
        self._frame._toolbar_action_buttons[key] = button
        self._frame._sync_toolbar_action_button(key)
        return button

    def _create_toolbar_btn(
        self,
        tooltip: str,
        icon_path: str,
        *,
        action: QAction | None = None,
    ) -> QToolButton:
        """创建带图标和提示文本的扁平工具栏按钮。"""
        icon_name = icon_path.replace("resources/icons/", "")
        btn = QToolButton()
        if action is not None:
            btn.setDefaultAction(action)
            icon_name = str(action.property("iconName") or "")
        elif icon_name:
            btn.setIcon(get_themed_icon(icon_name))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setProperty("iconName", icon_name)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setAutoRaise(True)
        return btn

    def _sync_toolbar_action_button(self, key: str) -> None:
        """把 QAction 的展示状态投射到兼容 QToolButton。"""

        action = getattr(self._frame, "_toolbar_actions", {}).get(key)
        button = getattr(self._frame, "_toolbar_action_buttons", {}).get(key)
        if action is None or button is None:
            return
        button.setEnabled(action.isEnabled())
        button.setCheckable(action.isCheckable())
        button.setChecked(action.isChecked())
        button.setIcon(action.icon())
        button.setToolTip(action.toolTip())
        button.setAccessibleName(str(action.property("accessibleName") or action.text()))
        button.setAccessibleDescription(str(action.property("accessibleDescription") or ""))
        button.setProperty("iconName", action.property("iconName"))

    def _set_toolbar_action_state(
        self,
        key: str,
        button_name: str,
        *,
        enabled: bool | None = None,
        checked: bool | None = None,
        tooltip: str | None = None,
        accessible_name: str | None = None,
        icon_name: str | None = None,
    ) -> None:
        """优先写 canonical QAction，并兼容只构造旧按钮的轻量调用方。"""

        action = getattr(self._frame, "_toolbar_actions", {}).get(key)
        target = action or getattr(self._frame, button_name, None)
        if target is None:
            return
        if enabled is not None:
            target.setEnabled(enabled)
        if checked is not None:
            target.setChecked(checked)
        if tooltip is not None:
            target.setToolTip(tooltip)
        if accessible_name is not None:
            if action is not None:
                action.setText(accessible_name)
                action.setProperty("accessibleName", accessible_name)
            else:
                target.setAccessibleName(accessible_name)
        if icon_name is not None:
            target.setProperty("iconName", icon_name)
            target.setIcon(get_themed_icon(icon_name))
        if action is not None:
            self._frame._sync_toolbar_action_button(key)

    def _setup_shortcuts(self) -> None:
        """注册不占用 Remote 启停组合键的主窗口快捷操作。"""

        bindings = (
            ("F5", self._frame._request_device_refresh),
            ("Ctrl+,", self._frame._show_settings),
            ("Ctrl+Shift+L", self._frame.clear_log),
        )
        self._frame._main_shortcuts = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self._frame)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._frame._main_shortcuts.append(shortcut)

    def _refresh_toolbar_metrics(self) -> None:
        """按当前界面字体更新工具栏高度和图标按钮点击区域。"""

        toolbar = getattr(self._frame, "_toolbar", None)
        if toolbar is None:
            return
        toolbar_height = BaseStyles.control_height(minimum=32, padding=8)
        requested_button_height = BaseStyles.control_height(minimum=24, padding=4)
        button_height = min(requested_button_height, max(24, toolbar_height - 2))
        size = QSize(max(28, button_height), button_height)
        toolbar.setMinimumHeight(toolbar_height)
        for button in toolbar.findChildren(QAbstractButton):
            button.setFixedSize(size)
        toolbar.updateGeometry()
        timer = getattr(self._frame, "_toolbar_path_layout_timer", None)
        if toolbar.isVisible() and timer is not None:
            timer.start(0)

    @staticmethod
    def _toolbar_widget_width(widget) -> int:
        """返回布局计算使用的稳定控件宽度。"""

        if widget.minimumWidth() == widget.maximumWidth():
            return max(0, widget.minimumWidth())
        return max(0, widget.minimumWidth(), widget.minimumSizeHint().width())

    def _toolbar_required_width(
        self,
        visible_keys: set[str],
        *,
        include_more: bool,
        include_title: bool,
    ) -> int:
        """估算不含可省略路径文本时所有固定入口所需的宽度。"""

        toolbar = self._frame._toolbar
        layout = toolbar.layout()
        margins = layout.contentsMargins()
        widgets = []
        if include_title:
            widgets.append(self._frame._toolbar_title)
        widgets.extend(
            self._frame._toolbar_action_buttons[key]
            for key in self._frame._toolbar_action_order
            if key in visible_keys
        )
        more_button = getattr(self._frame, "_toolbar_more_button", None)
        if include_more and more_button is not None:
            widgets.append(more_button)
        # 中间 stretch 在左右两组之间同样保留一处布局间距，按一格保守计入。
        gap_count = len(widgets) if widgets else 0
        return (
            margins.left()
            + margins.right()
            + sum(self._toolbar_widget_width(widget) for widget in widgets)
            + max(0, layout.spacing()) * gap_count
        )

    def _ensure_toolbar_more(self) -> tuple[QToolButton, QMenu]:
        """按需创建共享 QAction 的 More 入口。"""

        button = getattr(self._frame, "_toolbar_more_button", None)
        menu = getattr(self._frame, "_toolbar_more_menu", None)
        if button is not None and menu is not None:
            return button, menu

        toolbar = self._frame._toolbar
        layout = toolbar.layout()
        button = self._frame._create_toolbar_btn("More actions", "dots-three.svg")
        button.setObjectName("toolbarMoreButton")
        button.setAccessibleName("More actions")
        button.setAccessibleDescription("Open toolbar actions that do not fit in the window")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(toolbar)
        menu.setObjectName("toolbarMoreMenu")
        menu.setAccessibleName("More toolbar actions")
        button.setMenu(menu)
        exit_button = self._frame.tb_exit
        if exit_button.width() > 0 and exit_button.height() > 0:
            button.setFixedSize(exit_button.size())
        insert_index = layout.indexOf(self._frame.tb_minimize)
        layout.insertWidget(insert_index if insert_index >= 0 else layout.count(), button)
        button.hide()
        self._frame._toolbar_more_button = button
        self._frame._toolbar_more_menu = menu
        return button, menu

    def _update_toolbar_overflow(self) -> tuple[str, ...]:
        """在窄窗口隐藏直显按钮，并把同一 QAction 放入 More 菜单。"""

        toolbar = getattr(self._frame, "_toolbar", None)
        if toolbar is None or not toolbar.isVisible():
            return tuple(getattr(self._frame, "_toolbar_overflow_keys", ()))
        order = tuple(self._frame._toolbar_action_order)
        visible_keys = set(order)
        available_width = max(0, toolbar.contentsRect().width())
        direct_width = self._toolbar_required_width(
            visible_keys,
            include_more=False,
            include_title=True,
        )
        if direct_width <= available_width:
            for key in order:
                button = self._frame._toolbar_action_buttons[key]
                if button.isHidden():
                    button.show()
            self._frame._toolbar_title.show()
            more_button = getattr(self._frame, "_toolbar_more_button", None)
            more_menu = getattr(self._frame, "_toolbar_more_menu", None)
            if more_button is not None:
                more_button.hide()
            if more_menu is not None and more_menu.actions():
                more_menu.clear()
            self._frame._toolbar_overflow_keys = ()
            toolbar.layout().invalidate()
            toolbar.layout().activate()
            return ()

        more_button, more_menu = self._ensure_toolbar_more()
        include_title = True
        for key in self._OVERFLOW_PRIORITY:
            if (
                self._toolbar_required_width(
                    visible_keys,
                    include_more=True,
                    include_title=include_title,
                )
                <= available_width
            ):
                break
            visible_keys.discard(key)
        if (
            self._toolbar_required_width(
                visible_keys,
                include_more=True,
                include_title=include_title,
            )
            > available_width
        ):
            include_title = False
        for key in self._WINDOW_CONTROL_PRIORITY:
            if (
                self._toolbar_required_width(
                    visible_keys,
                    include_more=True,
                    include_title=include_title,
                )
                <= available_width
            ):
                break
            visible_keys.discard(key)

        hidden_keys = tuple(key for key in order if key not in visible_keys)
        for key in order:
            button = self._frame._toolbar_action_buttons[key]
            should_show = key in visible_keys
            if button.isHidden() == should_show:
                button.setVisible(should_show)
        self._frame._toolbar_title.setVisible(include_title)
        more_button.show()
        if hidden_keys != tuple(getattr(self._frame, "_toolbar_overflow_keys", ())):
            more_menu.clear()
            for key in hidden_keys:
                more_menu.addAction(self._frame._toolbar_actions[key])
        more_button.setToolTip(f"More actions ({len(hidden_keys)})")
        more_button.setAccessibleDescription(
            f"Open {len(hidden_keys)} toolbar actions that do not fit in the window"
        )
        self._frame._toolbar_overflow_keys = hidden_keys
        toolbar.layout().invalidate()
        toolbar.layout().activate()
        return hidden_keys

    def _toggle_theme(self):
        """记录工具栏主题切换请求并交给主题服务执行。"""
        _debug_log(
            self._frame,
            "ui.toolbar",
            action="theme",
            phase="requested",
            current_theme=BaseStyles.current_theme(),
        )
        BaseStyles.toggle_theme()

    def _minimize_window(self):
        """记录工具栏最小化动作。"""
        _debug_log(self._frame, "ui.toolbar", action="minimize", phase="requested")
        self._frame.showMinimized()

    def _toggle_maximize_restore(self):
        """切换最大化状态，并同步窗口控制按钮的图标和说明。"""

        if self._frame.isMaximized():
            self._frame.showNormal()
        else:
            self._frame.showMaximized()
        self._frame._refresh_maximize_button()

    def _refresh_maximize_button(self) -> None:
        maximized = self._frame.isMaximized()
        label = "Restore" if maximized else "Maximize"
        tooltip = (
            "Restore the main window to its previous size"
            if maximized
            else "Expand the main window to fill the screen"
        )
        icon_name = "corners-in.svg" if maximized else "square.svg"
        self._set_toolbar_action_state(
            "maximize",
            "tb_maximize",
            tooltip=tooltip,
            accessible_name=label,
            icon_name=icon_name,
        )

    def _request_application_close(self):
        """记录工具栏退出动作，实际资源清理由 closeEvent 接管。"""
        _debug_log(self._frame, "ui.toolbar", action="exit", phase="requested")
        self._frame.close()

    def _refresh_toolbar_icons(self):
        actions = tuple(getattr(self._frame, "_toolbar_actions", {}).values())
        for action in actions:
            icon_name = action.property("iconName")
            if icon_name:
                action.setIcon(get_themed_icon(icon_name))
        for button in self._frame.findChildren(QAbstractButton):
            icon_name = button.property("iconName")
            default_action = button.defaultAction() if isinstance(button, QToolButton) else None
            if icon_name and default_action not in actions:
                button.setIcon(get_themed_icon(icon_name))
        self._frame._refresh_always_on_top_button()

    def _sync_save_path_action(self, path: str) -> None:
        """让默认按钮公开当前完整保存路径。"""

        action = getattr(self._frame, "_toolbar_actions", {}).get("save_path")
        if action is None:
            return
        label = "Change default save directory"
        # 动作文本保持简短（窄窗口 More 菜单不得被完整路径撑出屏幕）；
        # 路径上下文经 toolTip/statusTip/accessibleDescription 承载，
        # `&` 无需转义（不进入菜单文本）。可访问名保持简短标签。
        if path:
            current_path = f"Current save directory: {path}"
            action.setText(label)
            action.setToolTip(f"Choose a different default output directory\n{current_path}")
            action.setStatusTip(current_path)
            action.setProperty("accessibleDescription", current_path)
        else:
            action.setText(label)
            action.setToolTip("Choose the default output directory")
            action.setStatusTip("")
            action.setProperty("accessibleDescription", "")
        action.setProperty("accessibleName", label)
        self._sync_toolbar_action_button("save_path")

    def _refresh_save_path(self):
        from core.settings_manager import AppSettings

        configured_path = AppSettings.instance().save_directory
        path = os.path.normpath(configured_path) if configured_path else ""
        self._sync_save_path_action(path)
        if path:
            self._frame._save_path_value = path
            self._frame._save_path_label.setToolTip(path)
            self._frame._save_path_label.setAccessibleName("Global save path")
            self._frame._save_path_label.setAccessibleDescription(path)
        else:
            self._frame._save_path_value = ""
            self._frame._save_path_label.setToolTip("")
            self._frame._save_path_label.setAccessibleDescription("")
        self._frame._save_path_label.setStyleSheet(
            f"color: {BaseStyles.color('TEXT_SECONDARY')}; padding: 0 2px;"
        )
        self._frame._save_path_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self._frame._update_toolbar_path_display()

    def _update_toolbar_path_display(self):
        """按工具栏扣除其余控件后的真实剩余宽度省略保存路径。"""

        self._update_toolbar_overflow()
        label = getattr(self._frame, "_save_path_label", None)
        if label is None:
            return
        path = getattr(self._frame, "_save_path_value", "")
        if not path:
            label.clear()
            label.hide()
            return

        save_button = getattr(self._frame, "_tb_save_btn", None)
        if save_button is not None and save_button.isHidden():
            label.hide()
            return

        toolbar = getattr(self._frame, "_toolbar", None)
        layout = toolbar.layout() if toolbar is not None else None
        if toolbar is None or layout is None:
            return
        margins = layout.contentsMargins()
        active_items = []
        required_width = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget is not label and widget.isHidden():
                continue
            active_items.append(item)
            if widget is None or widget is label:
                continue
            if widget.minimumWidth() == widget.maximumWidth():
                required_width += widget.minimumWidth()
            else:
                required_width += max(widget.minimumWidth(), widget.sizeHint().width())
        spacing_width = max(0, len(active_items) - 1) * max(0, layout.spacing())
        maximum_width = max(
            0,
            min(
                420,
                toolbar.width() - margins.left() - margins.right() - required_width - spacing_width,
            ),
        )
        label.setVisible(maximum_width > 0)
        source_text = "GlobalSavePath: " + path
        text = label.fontMetrics().elidedText(
            source_text,
            Qt.TextElideMode.ElideMiddle,
            maximum_width,
        )
        label.setMaximumWidth(maximum_width)
        label.setText(text)
        label.updateGeometry()

    def _on_save_path_clicked(self):
        from core.settings_manager import AppSettings

        _debug_log(self._frame, "ui.toolbar", action="save_path", phase="requested")
        s = AppSettings.instance()
        current = s.save_directory
        d = QFileDialog.getExistingDirectory(
            self._frame,
            "Select Default Save Directory",
            current if os.path.isdir(current) else "",
        )
        if d:
            s.set("save_directory", d)
            self._frame._refresh_save_path()
            _debug_log(self._frame, "ui.toolbar", action="save_path", phase="updated")
        else:
            _debug_log(self._frame, "ui.toolbar", action="save_path", phase="cancelled")

    def _is_toolbar_drag_target(self, position) -> bool:
        toolbar = getattr(self._frame, "_toolbar", None)
        widget = self._frame.childAt(position)
        while widget is not None:
            if isinstance(widget, QAbstractButton):
                return False
            if widget is toolbar:
                return True
            widget = widget.parentWidget()
        return False
