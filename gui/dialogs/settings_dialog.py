"""提供即时生效、支持主题切换的完整设置对话框。"""

import weakref

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.window_layout import DEFAULT_PANEL_RATIO, ratio_from_sizes


class SettingsDialog(QDialog):
    settings_applied = Signal()
    continuous_scan_toggled = Signal(bool)
    log_max_lines_changed = Signal(int)
    save_directory_changed = Signal(str)

    _SYSTEM_DEFAULT_FONT = "System Default"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._owner_ref = weakref.ref(parent) if parent is not None else lambda: None
        self.s = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setWindowIcon(get_themed_icon("gear.svg"))
        self.setMinimumSize(520, 420)
        self.resize(700, 600)
        self.setModal(False)

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._fonts_changed_signal = BaseStyles.fonts_changed
        self._fonts_changed_signal.connect(self._on_fonts_changed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content_widget = QWidget()
        content_widget.setObjectName("settingsContent")
        content_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(content_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(10, 10, 10, 10)
        body_row.setSpacing(10)

        # ── 分组导航：左侧分组列表，选中即滚动定位到对应分组 ─────────────
        # 视觉重设计：设置改为"分组导航"形态；分区仍垂直堆叠在同一滚动内容中，
        # 导航只是锚点跳转——所有分区控件保持挂载与可见性，压缩断点、网格坐标
        # 与滚动契约全部不变（映射注释见各测试适配处）。
        self._settings_nav = QListWidget()
        self._settings_nav.setObjectName("settingsNav")
        self._settings_nav.setFixedWidth(180)
        self._settings_nav.setProperty("fontRole", FontRole.UI.value)
        nav_order = (
            ("Appearance", 0),
            ("Window & Layout", 1),
            ("Storage & Logs", 2),
            ("Behavior", 3),
        )
        self._nav_targets: dict[int, QWidget] = {}
        for title, target_index in nav_order:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, target_index)
            self._settings_nav.addItem(item)
        self._settings_nav.currentRowChanged.connect(self._on_nav_row_changed)

        sections_widget = QWidget()
        content = QVBoxLayout(sections_widget)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(8)

        self._build_appearance(content)
        self._build_window(content)
        self._build_general(content)
        self._build_behavior(content)
        content.addStretch()

        for index in range(content.count()):
            item = content.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QGroupBox):
                self._nav_targets[index] = widget

        self._settings_scroll = QScrollArea()
        self._settings_scroll.setObjectName("settingsScroll")
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._settings_scroll.setWidget(sections_widget)
        self._settings_scroll.viewport().installEventFilter(self)
        body_row.addWidget(self._settings_nav)
        body_row.addWidget(self._settings_scroll, 1)
        outer.addLayout(body_row)
        root.addWidget(content_widget, 1)
        self._build_footer(root)
        self._appearance_compact = None
        self._window_compact = None
        self._general_compact = None
        self._settings_nav.setCurrentRow(0)
        self._update_responsive_form_layout(force=True)

    def _on_nav_row_changed(self, row: int) -> None:
        """分组导航：把对应分组滚动到视口顶部。"""

        target = self._nav_targets.get(row)
        if target is not None:
            self._settings_scroll.ensureWidgetVisible(target, 0, 20)

    # ── 外观 ────────────────────────────────────────────────────────────

    def _build_appearance(self, body):
        g = self._section("Appearance")
        self._theme_combo = self._combo(
            BaseStyles.theme_names(), BaseStyles.current_theme(), maximum_width=180
        )
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        configured_family = str(self.s.get("font_family", "") or "")
        font_families = self._available_ui_font_families(configured_family)
        selected_family = configured_family or self._SYSTEM_DEFAULT_FONT
        self._font_combo = self._combo(
            font_families,
            selected_family,
            maximum_width=260,
        )
        self._font_combo.setMinimumContentsLength(13)
        self._font_combo.currentTextChanged.connect(self._on_font_family_changed)
        self._combo_font = self._combo(
            ["8", "9", "10", "11", "12", "13", "14", "15", "16", "18", "20", "22"],
            str(self.s.get("ui_font_size", 12)),
            maximum_width=100,
        )
        self._combo_font.currentTextChanged.connect(self._on_font_changed)
        self._combo_log_font = self._combo(
            ["7", "8", "9", "10", "11", "12", "13", "14", "15", "16"],
            str(self.s.get("log_font_size", 9)),
            maximum_width=100,
        )
        self._combo_log_font.currentTextChanged.connect(self._on_log_font_changed)

        gg = QGridLayout(g)
        gg.setContentsMargins(10, 10, 10, 10)
        gg.setHorizontalSpacing(10)
        gg.setVerticalSpacing(8)
        self._appearance_grid = gg
        self._theme_label = self._label("Theme")
        self._ui_font_label = self._label("Interface Font")
        self._ui_size_label = self._label("Interface Size")
        self._log_size_label = self._label("Log Size")
        self._theme_label.setBuddy(self._theme_combo)
        self._ui_font_label.setBuddy(self._font_combo)
        self._ui_size_label.setBuddy(self._combo_font)
        self._log_size_label.setBuddy(self._combo_log_font)
        gg.addWidget(
            self._theme_label, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._theme_combo, 0, 1)
        gg.addWidget(
            self._ui_font_label, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._font_combo, 0, 3)
        gg.addWidget(
            self._ui_size_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._combo_font, 1, 1)
        gg.addWidget(
            self._log_size_label, 1, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._combo_log_font, 1, 3)

        self._ui_font_preview = QLabel("Aa 中文 123")
        self._ui_font_preview.setObjectName("uiFontPreview")
        self._ui_font_preview.setWordWrap(True)
        self._ui_font_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._log_font_preview = QLabel("12:30  INFO  Sample log")
        self._log_font_preview.setObjectName("logFontPreview")
        self._log_font_preview.setWordWrap(True)
        self._log_font_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._ui_preview_label = self._label("UI Preview")
        self._log_preview_label = self._label("Log Preview")
        gg.addWidget(
            self._ui_preview_label,
            2,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        gg.addWidget(self._ui_font_preview, 2, 1)
        gg.addWidget(
            self._log_preview_label,
            2,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        gg.addWidget(self._log_font_preview, 2, 3)

        self._font_apply_hint = QLabel("Changes apply immediately.")
        self._font_apply_hint.setObjectName("hintLabel")
        self._font_apply_hint.setWordWrap(True)
        self._font_apply_hint.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        gg.addWidget(self._font_apply_hint, 3, 1, 1, 3)
        gg.setColumnStretch(1, 1)
        gg.setColumnStretch(3, 1)
        body.addWidget(g)

    # ── 窗口 ────────────────────────────────────────────────────────────

    def _build_window(self, body):
        g = self._section("Window & Layout")
        self._window_size_value = QLabel()
        self._window_size_value.setObjectName("settingsValue")
        self._panel_split_value = QLabel()
        self._panel_split_value.setObjectName("settingsValue")

        self._btn_reset_window_size = self._icon_button(
            "arrow-u-up-left.svg",
            "Reset Size",
            "Restore the default main window size",
        )
        self._btn_reset_window_size.clicked.connect(self._restore_default_window_size)
        self._btn_reset_panel_split = self._icon_button(
            "arrow-u-up-left.svg",
            "Reset Split",
            "Restore the default panel proportions",
        )
        self._btn_reset_panel_split.clicked.connect(self._reset_panel_split)

        owner = self._layout_owner()
        self._btn_reset_window_size.setEnabled(
            callable(getattr(owner, "restore_default_window_size", None))
        )
        self._btn_reset_panel_split.setEnabled(callable(getattr(owner, "reset_panel_split", None)))

        gg = QGridLayout(g)
        gg.setContentsMargins(10, 10, 10, 10)
        gg.setHorizontalSpacing(10)
        gg.setVerticalSpacing(8)
        self._window_grid = gg
        self._current_size_label = self._label("Current Size")
        self._panel_split_label = self._label("Panel Split")
        gg.addWidget(
            self._current_size_label,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        gg.addWidget(self._window_size_value, 0, 1)
        gg.addWidget(self._btn_reset_window_size, 0, 2)
        gg.addWidget(
            self._panel_split_label,
            1,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        gg.addWidget(self._panel_split_value, 1, 1)
        gg.addWidget(self._btn_reset_panel_split, 1, 2)
        gg.setColumnStretch(1, 1)
        body.addWidget(g)
        self._refresh_window_layout_summary()

    # ── 行为 ────────────────────────────────────────────────────────────

    def _build_behavior(self, body):
        g = self._section("Behavior")

        self._chk_confirm = self._checkbox("Confirm risky actions")
        self._chk_confirm.setChecked(self.s.get("confirm_dangerous_ops", True))
        self._chk_confirm.toggled.connect(self._on_confirm_dangerous_toggled)
        self._confirm_description = self._description(
            "Confirm reboot, uninstall, clear data, Shell, port, and process operations."
        )

        self._chk_continuous_scan = self._checkbox("Scan for new devices")
        self._chk_continuous_scan.setChecked(self.s.get("continuous_device_scan", True))
        self._chk_continuous_scan.toggled.connect(self._on_continuous_scan_toggled)
        self._scan_description = self._description(
            "Periodically checks for newly connected devices in the background."
        )

        vl = QVBoxLayout(g)
        vl.setContentsMargins(10, 10, 10, 10)
        vl.setSpacing(4)
        vl.addWidget(self._chk_confirm)
        vl.addWidget(self._confirm_description)
        vl.addWidget(self._chk_continuous_scan)
        vl.addWidget(self._scan_description)
        body.addWidget(g)

    # ── 常规 ────────────────────────────────────────────────────────────

    def _build_general(self, body):
        g = self._section("Storage & Logs")
        gg = QGridLayout(g)
        self._general_grid = gg
        gg.setContentsMargins(10, 10, 10, 10)
        gg.setHorizontalSpacing(10)
        gg.setVerticalSpacing(8)

        save_dir = self.s.get("save_directory", "")
        self._lbl_save = QLabel(save_dir if save_dir else "~/ADBLab (default)")
        self._lbl_save.setObjectName("hintLabel")
        self._lbl_save.setWordWrap(True)
        self._lbl_save.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_save.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._lbl_save.setMinimumWidth(0)
        self._update_save_directory_display(save_dir)
        self._btn_save = self._icon_button(
            "folder.svg", "Choose...", "Select the default output directory"
        )
        self._btn_save.clicked.connect(self._on_pick_save_dir)
        self._save_dir_label = self._label("Save Directory")
        self._save_dir_label.setBuddy(self._btn_save)
        gg.addWidget(
            self._save_dir_label, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._lbl_save, 0, 1)
        gg.addWidget(self._btn_save, 0, 2)

        self._combo_log_lines = self._combo(
            ["1000", "2000", "3000", "5000", "10000"],
            str(self.s.get("log_max_lines", 2000)),
            maximum_width=128,
        )
        self._combo_log_lines.currentTextChanged.connect(self._on_log_max_lines_changed)
        self._max_log_label = self._label("Visible Log Lines")
        self._max_log_label.setBuddy(self._combo_log_lines)
        gg.addWidget(
            self._max_log_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gg.addWidget(self._combo_log_lines, 1, 1)

        gg.setColumnStretch(1, 1)
        body.addWidget(g)

    # ── 底部操作 ────────────────────────────────────────────────────────

    def _build_footer(self, body):
        body.addSpacing(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(10, 8, 10, 10)
        self._btn_restore_defaults = QPushButton("Restore Defaults")
        self._btn_restore_defaults.setToolTip("Reset all preferences to their defaults")
        self._btn_restore_defaults.setIcon(get_themed_icon("arrow-u-up-left.svg"))
        self._btn_restore_defaults.setIconSize(QSize(14, 14))
        self._btn_restore_defaults.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_restore_defaults.setAutoDefault(False)
        self._btn_restore_defaults.clicked.connect(self._reset_all)
        row.addWidget(self._btn_restore_defaults)
        row.addStretch()
        self._btn_close = QPushButton("Close")
        self._btn_close.setToolTip("Save changes and close settings")
        self._btn_close.setIcon(get_themed_icon("x.svg"))
        self._btn_close.setIconSize(QSize(14, 14))
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setObjectName("accent")
        self._btn_close.setDefault(True)
        self._btn_close.clicked.connect(self.accept)
        row.addWidget(self._btn_close)
        body.addLayout(row)

    # ── 控件辅助方法 ────────────────────────────────────────────────────

    def _section(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setObjectName("settingsSection")
        g.setProperty("fontRole", FontRole.UI.value)
        return g

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("settingsLabel")
        lbl.setProperty("fontRole", FontRole.UI.value)
        return lbl

    def _combo(self, items: list, current: str, *, maximum_width: int) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setCurrentText(current)
        c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        c.setMinimumContentsLength(8)
        c.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        c.setMinimumWidth(0)
        c.setMaximumWidth(maximum_width)
        return c

    def _description(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsDescription")
        label.setProperty("fontRole", FontRole.UI_SMALL.value)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setMinimumWidth(0)
        return label

    @classmethod
    def _available_ui_font_families(cls, configured_family: str = "") -> list[str]:
        """返回系统字体列表，并保留旧配置中暂时不可用的字体。"""
        families = sorted(
            {str(family).strip() for family in QFontDatabase.families() if str(family).strip()},
            key=str.casefold,
        )
        if configured_family and configured_family not in families:
            families.insert(0, configured_family)
        return [cls._SYSTEM_DEFAULT_FONT, *families]

    def _checkbox(self, text: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setObjectName("settingsCheck")
        cb.setProperty("fontRole", FontRole.UI.value)
        cb.setToolTip(text)
        cb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        cb.setMinimumWidth(0)
        return cb

    def _icon_button(self, icon: str, text: str = "", tooltip: str = "") -> QPushButton:
        btn = QPushButton(text)
        if icon:
            btn.setIcon(get_themed_icon(icon))
            btn.setIconSize(QSize(14, 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setAccessibleDescription(tooltip)
        if text:
            btn.setAccessibleName(text)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        return btn

    def _window_layout_snapshot(self) -> dict[str, int | float]:
        """通过主窗口公开接口读取布局状态，并为独立打开场景提供设置回退值。"""
        owner = self._layout_owner()
        snapshot_method = getattr(owner, "window_layout_snapshot", None)
        snapshot = snapshot_method() if callable(snapshot_method) else {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        def positive_int(value, fallback: int) -> int:
            try:
                normalized_fallback = int(fallback)
            except (TypeError, ValueError, OverflowError):
                normalized_fallback = 1
            try:
                parsed = int(value)
            except (TypeError, ValueError, OverflowError):
                return normalized_fallback
            return parsed if parsed > 0 else normalized_fallback

        width = positive_int(
            snapshot.get("width"), positive_int(self.s.get("window_width", 1120), 1120)
        )
        height = positive_int(
            snapshot.get("height"), positive_int(self.s.get("window_height", 640), 640)
        )
        stored_ratio = self.s.get("panel_split_ratio", None)
        if stored_ratio is None:
            stored_ratio = ratio_from_sizes(
                self.s.get("left_panel_width", 400),
                self.s.get("right_panel_width", 600),
            )
        try:
            ratio = float(snapshot.get("panel_ratio", stored_ratio))
        except (TypeError, ValueError, OverflowError):
            ratio = DEFAULT_PANEL_RATIO
        if not 0 < ratio < 1:
            ratio = DEFAULT_PANEL_RATIO
        return {"width": width, "height": height, "panel_ratio": ratio}

    def _refresh_window_layout_summary(self):
        snapshot = self._window_layout_snapshot()
        width = int(snapshot["width"])
        height = int(snapshot["height"])
        left_percent = round(float(snapshot["panel_ratio"]) * 100)
        self._window_size_value.setText(f"{width} × {height} px")
        self._panel_split_value.setText(f"{left_percent}% / {100 - left_percent}%")

    def _restore_default_window_size(self):
        action = getattr(self._layout_owner(), "restore_default_window_size", None)
        if callable(action):
            action()
        self._refresh_window_layout_summary()

    def _reset_panel_split(self):
        action = getattr(self._layout_owner(), "reset_panel_split", None)
        if callable(action):
            action()
        self._refresh_window_layout_summary()

    @staticmethod
    def _remove_widgets(layout: QGridLayout, widgets):
        for widget in widgets:
            layout.removeWidget(widget)

    def _layout_appearance(self, compact: bool):
        widgets = (
            self._theme_label,
            self._theme_combo,
            self._ui_font_label,
            self._font_combo,
            self._ui_size_label,
            self._combo_font,
            self._log_size_label,
            self._combo_log_font,
            self._ui_preview_label,
            self._ui_font_preview,
            self._log_preview_label,
            self._log_font_preview,
            self._font_apply_hint,
        )
        grid = self._appearance_grid
        self._remove_widgets(grid, widgets)
        if compact:
            rows = (
                (self._theme_label, self._theme_combo),
                (self._ui_font_label, self._font_combo),
                (self._ui_size_label, self._combo_font),
                (self._log_size_label, self._combo_log_font),
                (self._ui_preview_label, self._ui_font_preview),
                (self._log_preview_label, self._log_font_preview),
            )
            current_row = 0
            for label, control in rows:
                grid.addWidget(
                    label,
                    current_row,
                    0,
                    1,
                    2,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                grid.addWidget(control, current_row + 1, 0, 1, 2)
                current_row += 2
            grid.addWidget(self._font_apply_hint, current_row, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 0)
            grid.setColumnStretch(3, 0)
            return

        grid.addWidget(
            self._theme_label, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(self._theme_combo, 0, 1)
        grid.addWidget(
            self._ui_font_label, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(self._font_combo, 0, 3)
        grid.addWidget(
            self._ui_size_label, 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(self._combo_font, 1, 1)
        grid.addWidget(
            self._log_size_label, 1, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(self._combo_log_font, 1, 3)
        grid.addWidget(
            self._ui_preview_label,
            2,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addWidget(self._ui_font_preview, 2, 1)
        grid.addWidget(
            self._log_preview_label,
            2,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addWidget(self._log_font_preview, 2, 3)
        grid.addWidget(self._font_apply_hint, 3, 1, 1, 3)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)

    def _layout_window(self, compact: bool):
        widgets = (
            self._current_size_label,
            self._window_size_value,
            self._btn_reset_window_size,
            self._panel_split_label,
            self._panel_split_value,
            self._btn_reset_panel_split,
        )
        grid = self._window_grid
        self._remove_widgets(grid, widgets)
        if compact:
            grid.addWidget(self._current_size_label, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._window_size_value, 1, 0, 1, 2)
            grid.addWidget(self._btn_reset_window_size, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._panel_split_label, 3, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._panel_split_value, 4, 0, 1, 2)
            grid.addWidget(self._btn_reset_panel_split, 5, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 0)
            return

        grid.addWidget(
            self._current_size_label,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addWidget(self._window_size_value, 0, 1)
        grid.addWidget(self._btn_reset_window_size, 0, 2)
        grid.addWidget(
            self._panel_split_label,
            1,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addWidget(self._panel_split_value, 1, 1)
        grid.addWidget(self._btn_reset_panel_split, 1, 2)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)

    def _layout_general(self, compact: bool):
        widgets = (
            self._save_dir_label,
            self._lbl_save,
            self._btn_save,
            self._max_log_label,
            self._combo_log_lines,
        )
        grid = self._general_grid
        self._remove_widgets(grid, widgets)
        if compact:
            grid.addWidget(self._save_dir_label, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._lbl_save, 1, 0, 1, 2)
            grid.addWidget(self._btn_save, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._max_log_label, 3, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(self._combo_log_lines, 4, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
        else:
            grid.addWidget(
                self._save_dir_label,
                0,
                0,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            grid.addWidget(self._lbl_save, 0, 1)
            grid.addWidget(self._btn_save, 0, 2)
            grid.addWidget(
                self._max_log_label,
                1,
                0,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            grid.addWidget(self._combo_log_lines, 1, 1)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 0)

    def _update_responsive_form_layout(self, force: bool = False):
        if not hasattr(self, "_settings_scroll") or not hasattr(self, "_appearance_compact"):
            return
        available_width = max(0, self._settings_scroll.viewport().width())
        threshold = 640 + max(0, BaseStyles.DEFAULT_FONT_SIZE - 12) * 18
        compact = available_width < threshold
        if force or compact != self._appearance_compact:
            self._layout_appearance(compact)
            self._appearance_compact = compact
        if force or compact != self._window_compact:
            self._layout_window(compact)
            self._window_compact = compact
        if force or compact != self._general_compact:
            self._layout_general(compact)
            self._general_compact = compact

    # ── 回调辅助方法 ────────────────────────────────────────────────────

    # ── 回调 ────────────────────────────────────────────────────────────

    def _on_theme_changed(self, t: str):
        BaseStyles.switch_theme(t)
        self.s.set("theme", t)

    def _selected_font_family(self) -> str:
        family = self._font_combo.currentText().strip()
        return "" if family == self._SYSTEM_DEFAULT_FONT else family

    def _update_settings(self, values: dict):
        updater = getattr(self.s, "update", None)
        if callable(updater):
            updater(values)
            return
        for key, value in values.items():
            self.s.set(key, value)

    def _apply_ui_font(self):
        """通过统一兼容入口应用 UI 字体配置。"""
        self._update_settings(
            {
                "font_family": self._selected_font_family(),
                "ui_font_size": int(self._combo_font.currentText()),
            }
        )
        BaseStyles.reload_from_settings()

    def _apply_log_font(self):
        """通过统一兼容入口应用日志字号配置。"""
        self._update_settings({"log_font_size": int(self._combo_log_font.currentText())})
        BaseStyles.reload_from_settings()

    def _on_font_family_changed(self, _family: str):
        self._apply_ui_font()

    def _on_font_changed(self, _size: str):
        self._apply_ui_font()

    def _on_log_font_changed(self, _size: str):
        self._apply_log_font()

    def _on_fonts_changed(self, _config=None):
        self._apply_theme()

    def _on_continuous_scan_toggled(self, checked: bool):
        self.s.set("continuous_device_scan", checked)
        self.continuous_scan_toggled.emit(checked)

    def _on_confirm_dangerous_toggled(self, checked: bool):
        """兼容保留：危险操作确认已全局移除，该键仅作兼容存储不再驱动弹窗。"""

        self.s.set("confirm_dangerous_ops", checked)

    def _on_log_max_lines_changed(self, text: str):
        value = int(text)
        self.s.set("log_max_lines", value)
        self.log_max_lines_changed.emit(value)

    def _layout_owner(self):
        """返回仍然存活的主窗口；对话框解除 Qt parent 后仍可调用布局接口。"""

        try:
            return self._owner_ref()
        except (ReferenceError, RuntimeError):
            return None

    def _update_save_directory_display(self, directory: str):
        text = str(directory or "~/ADBLab (default)")
        self._lbl_save.setText(text)
        self._lbl_save.setToolTip(text)

    def _on_pick_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select default save directory")
        if d:
            self.s.set("save_directory", d)
            self._update_save_directory_display(d)
            self.save_directory_changed.emit(d)

    # ── 主题 ────────────────────────────────────────────────────────────

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "_settings_scroll")
            and watched is self._settings_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._update_responsive_form_layout()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._update_responsive_form_layout()

    def closeEvent(self, event):
        try:
            BaseStyles.theme_changed.disconnect(self._apply_theme)
        except (RuntimeError, TypeError):
            pass
        try:
            self._fonts_changed_signal.disconnect(self._on_fonts_changed)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)

    @staticmethod
    def _font_preview_qss(font: QFont, color: str) -> str:
        family = font.family().replace("'", "\\'")
        if font.pointSizeF() > 0:
            size = f"{font.pointSizeF():g}pt"
        else:
            size = f"{max(1, font.pixelSize())}px"
        return f"color: {color}; font-family: '{family}'; font-size: {size};"

    def _refresh_font_previews(self):
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        log_font = BaseStyles.font_for_role(FontRole.LOG)
        self._ui_font_preview.setFont(ui_font)
        self._log_font_preview.setFont(log_font)
        self._ui_font_preview.setStyleSheet(
            self._font_preview_qss(ui_font, BaseStyles.color("TEXT_PRIMARY"))
        )
        self._log_font_preview.setStyleSheet(
            self._font_preview_qss(log_font, BaseStyles.color("TEXT_SECONDARY"))
        )

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        if hasattr(self, "_theme_combo"):
            blocker = QSignalBlocker(self._theme_combo)
            self._theme_combo.setCurrentText(BaseStyles.current_theme())
            blocker.unblock()
        c = BaseStyles.color
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        small_font = BaseStyles.font_for_role(FontRole.UI_SMALL)
        self.setFont(ui_font)
        for section in self.findChildren(QGroupBox, "settingsSection"):
            section_font = QFont(ui_font)
            section_font.setBold(True)
            section.setFont(section_font)
        for label in self.findChildren(QLabel, "settingsLabel"):
            label.setFont(ui_font)
        for hint in self.findChildren(QLabel, "hintLabel"):
            hint.setFont(small_font)
        for description in self.findChildren(QLabel, "settingsDescription"):
            description.setFont(small_font)
        for value in self.findChildren(QLabel, "settingsValue"):
            value.setFont(ui_font)

        control_height = BaseStyles.control_height(minimum=28, padding=8)
        for control_type in (QComboBox, QPushButton):
            for control in self.findChildren(control_type):
                control.setMinimumHeight(control_height)
        self.setStyleSheet(
            BaseStyles.INPUT_STYLE()
            + BaseStyles.BUTTON_QSS()
            + BaseStyles.SCROLLBAR_STYLE()
            + BaseStyles.GROUP_BOX_STYLE()
            + f"""
            QDialog {{
                background-color: {c("WINDOW_BG")};
                color: {c("TEXT_PRIMARY")};
            }}
            QDialog QLabel,
            QDialog QComboBox,
            QDialog QComboBox QAbstractItemView,
            QDialog QCheckBox,
            QDialog QPushButton {{ color: {c("TEXT_PRIMARY")}; }}
            QScrollArea#settingsScroll {{
                border: none;
                background-color: transparent;
            }}
            QWidget#settingsContent {{ background-color: transparent; }}
            QListWidget#settingsNav {{
                background-color: transparent;
                border: none;
                border-right: 1px solid {c("BORDER_COLOR")};
            }}
            QListWidget#settingsNav::item {{
                color: {c("TEXT_PRIMARY")};
                padding: 8px 10px;
                border-radius: 6px;
                margin: 1px 6px 1px 0;
            }}
            QListWidget#settingsNav::item:hover {{
                background-color: {c("BUTTON_HOVER")};
            }}
            QListWidget#settingsNav::item:selected {{
                background-color: {c("BUTTON_ACCENT")};
                color: #ffffff;
            }}
            QLabel#settingsLabel {{
                color: {c("TEXT_PRIMARY")};
                min-width: 72px;
            }}
            QLabel#hintLabel {{
                color: {c("TEXT_SECONDARY")};
                padding: 1px 2px;
            }}
            QLabel#settingsValue {{
                color: {c("TEXT_PRIMARY")};
                padding: 1px 2px;
            }}
            QLabel#settingsDescription {{
                color: {c("TEXT_SECONDARY")};
                padding: 0 0 4px 26px;
            }}
            QCheckBox#settingsCheck {{
                color: {c("TEXT_PRIMARY")};
                spacing: 8px;
                padding: 2px 0;
            }}
            QCheckBox#settingsCheck:focus {{
                border: 1px solid {c("BORDER_FOCUS")};
                border-radius: 4px;
            }}
        """
        )
        self._refresh_font_previews()
        self._update_responsive_form_layout(force=True)

    # ── 重置 ────────────────────────────────────────────────────────────

    def _sync_controls_from_settings(self):
        """在信号阻塞期间将全部可见控件同步为当前设置值。"""
        theme = str(self.s.get("theme", "Light"))
        family = str(self.s.get("font_family", "") or "")
        family_text = family or self._SYSTEM_DEFAULT_FONT
        if self._font_combo.findText(family_text) < 0:
            self._font_combo.addItem(family_text)

        self._theme_combo.setCurrentText(theme)
        self._font_combo.setCurrentText(family_text)
        self._combo_font.setCurrentText(str(self.s.get("ui_font_size", 12)))
        self._combo_log_font.setCurrentText(str(self.s.get("log_font_size", 9)))
        self._chk_confirm.setChecked(bool(self.s.get("confirm_dangerous_ops", True)))
        self._chk_continuous_scan.setChecked(bool(self.s.get("continuous_device_scan", True)))
        self._combo_log_lines.setCurrentText(str(self.s.get("log_max_lines", 2000)))
        save_dir = str(self.s.get("save_directory", "") or "")
        self._update_save_directory_display(save_dir)

        self._refresh_window_layout_summary()

    def _reset_all(self):
        self.s.reset()
        controls = (
            self._theme_combo,
            self._font_combo,
            self._combo_font,
            self._combo_log_font,
            self._chk_confirm,
            self._chk_continuous_scan,
            self._combo_log_lines,
        )
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            self._sync_controls_from_settings()
        finally:
            for blocker in blockers:
                blocker.unblock()

        self._restore_default_window_size()
        self._reset_panel_split()
        BaseStyles.switch_theme(str(self.s.get("theme", "Light")))
        BaseStyles.reload_from_settings()
        self.continuous_scan_toggled.emit(bool(self.s.get("continuous_device_scan", True)))
        self.log_max_lines_changed.emit(int(self.s.get("log_max_lines", 2000)))
        self.save_directory_changed.emit(str(self.s.get("save_directory", "") or ""))
        self.settings_applied.emit()
