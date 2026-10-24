"""基于 PyQt-Fluent-Widgets Gallery 示例（GPL-3.0）移植的主界面页面组件。

页面骨架和流式操作卡片直接沿用参考项目的组织方式，并改写为
PySide6 与 ADBLab 业务入口。这里不再复刻旧主窗口的分栏、工具条或页签体系。
来源与许可说明见仓库根目录 ``THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QPushButton,
    QWidget,
)
from qfluentwidgets import (
    ColorPickerButton,
    ComboBox,
    ExpandLayout,
    FluentIcon,
    PushSettingCard,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SwitchSettingCard,
)

from core.exec import reset_adb_program_cache
from core.settings_manager import AppSettings, normalise_language, normalise_ui_scale
from gui.features import AboutPanel
from gui.i18n import tr
from gui.notifications import show_toast
from gui.styles import BaseStyles, FontRole
from gui.styles.combo_menu import configure_combo_menu
from gui.styles.fluent import (
    apply_font_role,
    apply_label_role,
    set_fluent_font_rule,
    use_instant_scroll,
)
from gui.styles.icon_loader import cached_fluent_icon
from gui.styles.theme import normalise_accent_color
from gui.widgets.adb_client_card import AdbClientSettingCard, AdbEnvironmentSettingCard
from gui.widgets.setting_card_layout import (
    SettingsCardPresentation as _SettingsCardPresentation,
)
from gui.widgets.setting_card_layout import apply_setting_text_style
from gui.widgets.settings_scroll import SettingsWheelScroll
from gui.window_effects import is_mica_supported
from services.adb_clients import clear_client_probe_cache
from utils.adb_resolver import (
    CLIENT_PREFERENCE_AUTO,
    CLIENT_SOURCE_TOKENS,
    invalidate_adb_path_cache,
    set_client_preference,
)

from .home import (
    ActionCard as ActionCard,
)
from .home import (
    ActionCardView as ActionCardView,
)
from .home import (
    DeviceContextCard as DeviceContextCard,
)
from .home import (
    HomePage as HomePage,
)
from .workspace_containers import (
    GalleryPage as GalleryPage,
)
from .workspace_containers import (
    WorkspaceAreaPage as WorkspaceAreaPage,
)
from .workspace_containers import (
    WorkspaceSectionPage as WorkspaceSectionPage,
)


class _SettingsPathLabel(QLabel):
    """长路径中间省略，完整配置仍由文本、悬停提示和辅助技术读取。"""

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleDescription(text)

    def heightForWidth(self, _width: int) -> int:
        return self.fontMetrics().height()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideMiddle, self.contentsRect().width(),
        )
        painter.drawText(
            self.contentsRect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )




class _SettingsContentLayout(ExpandLayout):
    """将页尾留白计入内容高度，避免可调整滚动区按尺寸提示裁掉底边距。"""

    def heightForWidth(self, width: int) -> int:
        # 当前 Fluent ExpandLayout 的高度测量只计算到最后一个控件底部。
        return super().heightForWidth(width) + self.contentsMargins().bottom()


class SettingsPage(ScrollArea):
    """使用参考项目 SettingCardGroup 体系重写的设置页。"""

    THEME_LABELS = {
        "System": "跟随系统",
        "Light": "浅色",
        "Dark": "深色",
    }
    THEME_MODES = {label: mode for mode, label in THEME_LABELS.items()}
    SCALE_LABELS = {
        "Auto": "跟随系统", 1.0: "100%", 1.25: "125%", 1.5: "150%",
        1.75: "175%", 2.0: "200%",
    }
    SCALE_VALUES = {label: value for value, label in SCALE_LABELS.items()}
    LANGUAGE_LABELS = {
        "Auto": "跟随系统", "zh_CN": "简体中文", "zh_HK": "繁體中文", "en_US": "English",
    }

    def __init__(
        self, frame, parent: QWidget | None = None, *, defer_startup_detection: bool = False,
    ) -> None:
        super().__init__(parent)
        use_instant_scroll(self)
        self._wheel_scroll = SettingsWheelScroll(self, self.scrollDelagate.vScrollBar)
        self._frame = frame
        self._settings = AppSettings.instance()
        self._startup_detection_scheduled = False
        # 取色器会在拖动时逐帧发出 colorChanged；合并到停止拖动后只应用一次全局 QSS。
        self._accent_apply_timer = QTimer(self)
        self._accent_apply_timer.setSingleShot(True)
        self._accent_apply_timer.setInterval(120)
        self._accent_apply_timer.timeout.connect(self._apply_pending_accent)
        self._pending_accent: QColor | None = None
        # 宽度拖动只提交最后一次布局；首次显示或字体/文案变化仍走同步重排。
        self._settings_reflow_timer = QTimer(self)
        self._settings_reflow_timer.setSingleShot(True)
        self._settings_reflow_timer.setInterval(60)
        self._settings_reflow_timer.timeout.connect(
            lambda: self._reflow_settings(force=False)
        )
        # 只翻译显示标签；持久化值与路由标识不随界面语言变化。
        self.THEME_LABELS = {mode: tr(label) for mode, label in type(self).THEME_LABELS.items()}
        self.THEME_MODES = {label: mode for mode, label in self.THEME_LABELS.items()}
        self.SCALE_LABELS = {value: tr(label) for value, label in type(self).SCALE_LABELS.items()}
        self.SCALE_VALUES = {label: value for value, label in self.SCALE_LABELS.items()}
        self.LANGUAGE_LABELS = {**type(self).LANGUAGE_LABELS, "Auto": tr("跟随系统")}
        self._language_values = {label: value for value, label in self.LANGUAGE_LABELS.items()}
        self.setObjectName("settingsPage")
        self.setAccessibleName(tr("设置"))
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        # 内容和底部留白使用同一透明表面，避免滚动区出现独立色带。
        self.setStyleSheet(
            "#settingsPage, #settingsView { background: transparent; border: none; }"
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)

        view = QWidget(self)
        view.setObjectName("settingsView")
        self.expand_layout = _SettingsContentLayout(view)
        self.expand_layout.setSpacing(28)
        # 留白随内容滚动，滚动条保持原生定位及完整视口高度。
        self.expand_layout.setContentsMargins(32, 16, 32, 44)

        general = SettingCardGroup(tr("常规"), view)
        self.save_card = PushSettingCard(
            tr("选择文件夹"),
            FluentIcon.FOLDER,
            tr("默认输出目录"),
            str(self._settings.get("save_directory", "") or tr("系统默认目录")),
            general,
        )
        self.scan_card = _LocalizedSwitchSettingCard(
            FluentIcon.SYNC,
            tr("持续扫描设备"),
            tr("后台定期刷新已连接的 Android 设备"),
            parent=general,
        )
        self.scan_card.setChecked(bool(self._settings.get("continuous_device_scan", True)))
        general.addSettingCard(self.save_card)
        general.addSettingCard(self.scan_card)
        self.log_lines_card = ComboSettingCard(
            FluentIcon.SCROLL,
            tr("性能采集输出行数"),
            tr("限制新打开的性能采集页保留的过程输出行数"),
            ["500", "1000", "2000", "5000", "10000"],
            str(self._settings.get("log_max_lines", 2000)),
            general,
        )
        general.addSettingCard(self.log_lines_card)

        appearance = SettingCardGroup(tr("个性化"), view)
        theme_mode = str(self._settings.get("theme", "System"))
        self.theme_card = ComboSettingCard(
            FluentIcon.BRUSH,
            tr("应用主题"),
            tr("选择浅色、深色或跟随 Windows 设置"),
            list(self.THEME_MODES),
            self.THEME_LABELS.get(theme_mode, tr("跟随系统")),
            appearance,
        )
        self.scale_card = ComboSettingCard(
            FluentIcon.ZOOM,
            tr("显示缩放"),
            tr("调整控件与文字的整体比例，重启应用后生效；窗口布局随宽度自动调整"),
            list(self.SCALE_VALUES),
            self.SCALE_LABELS[normalise_ui_scale(self._settings.get("ui_scale", "Auto"))],
            appearance,
        )
        self.accent_card = AccentColorSettingCard(
            FluentIcon.PALETTE,
            tr("强调色"),
            tr("应用到主要按钮、选中状态和键盘焦点"),
            str(self._settings.get("accent_color", "#0F6CBD")),
            appearance,
        )
        self.mica_card = _LocalizedSwitchSettingCard(
            FluentIcon.TRANSPARENT,
            tr("云母效果"),
            tr("使用 Windows 云母材质，底色随主题和桌面壁纸变化") if is_mica_supported()
            else tr("云母效果需要 Windows 11，当前系统使用实色背景"),
            parent=appearance,
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.mica_card.setEnabled(is_mica_supported())
        self.language_card = ComboSettingCard(
            FluentIcon.LANGUAGE,
            tr("语言"),
            tr("选择界面使用的语言，重启应用后生效"),
            list(self._language_values),
            self.LANGUAGE_LABELS[normalise_language(self._settings.get("language", "Auto"))],
            appearance,
        )
        self.pin_card = _LocalizedSwitchSettingCard(
            FluentIcon.PIN,
            tr("窗口置顶"),
            tr("让 ADBLab 保持在其他窗口上方"),
            parent=appearance,
        )
        self.pin_card.setChecked(bool(frame._always_on_top))
        for card in (self.scan_card, self.mica_card, self.pin_card):
            card.switchButton.setOnText(tr("开"))
            card.switchButton.setOffText(tr("关"))
        appearance.addSettingCard(self.mica_card)
        appearance.addSettingCard(self.theme_card)
        appearance.addSettingCard(self.accent_card)
        appearance.addSettingCard(self.scale_card)
        appearance.addSettingCard(self.language_card)
        appearance.addSettingCard(self.pin_card)

        typography = SettingCardGroup(tr("字体"), view)
        configured_family = str(self._settings.get("font_family", "") or tr("系统默认"))
        installed = set(QFontDatabase.families())
        families = [tr("系统默认")]
        for family in (
            "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", configured_family,
        ):
            if family != tr("系统默认") and family in installed and family not in families:
                families.append(family)
        self.font_family_card = ComboSettingCard(
            FluentIcon.FONT,
            tr("界面字体"),
            tr("应用到导航、页面与对话框文字"),
            families,
            configured_family,
            typography,
        )
        self.ui_size_card = ComboSettingCard(
            FluentIcon.FONT_SIZE,
            tr("界面字号（pt）"),
            tr("即时调整正文大小；推荐 11 pt，已有字号保持不变"),
            [str(value) for value in range(8, 23)],
            str(self._settings.get("ui_font_size", 12)),
            typography,
        )
        self.log_size_card = ComboSettingCard(
            FluentIcon.CODE,
            tr("输出文本字号（pt）"),
            tr("即时调整操作结果、文件预览和采集输出的等宽文字大小"),
            [str(value) for value in range(7, 17)],
            str(self._settings.get("log_font_size", 9)),
            typography,
        )
        typography.addSettingCard(self.font_family_card)
        typography.addSettingCard(self.ui_size_card)
        typography.addSettingCard(self.log_size_card)

        application = SettingCardGroup(tr("应用"), view)
        self.reset_card = PushSettingCard(
            tr("恢复"),
            FluentIcon.UPDATE,
            tr("恢复默认设置"),
            tr("恢复窗口、主题、字体和常规选项"),
            application,
        )
        application.addSettingCard(self.reset_card)
        self.diagnostics_card = PushSettingCard(
            tr("导出诊断"), FluentIcon.INFO, tr("应用诊断"),
            tr("本次运行尚无应用异常记录"), application,
        )
        application.addSettingCard(self.diagnostics_card)
        self.diagnostics_card.button.setEnabled(False)

        maintenance = SettingCardGroup(tr("ADB 维护"), view)
        self._last_adb_environment_text = ""
        # 三张卡平铺：客户端选择 → 执行环境（模式 + 状态 + 重新检测）→ 重启本机服务。
        self.adb_client_card = AdbClientSettingCard(maintenance)
        self.adb_check_card = AdbEnvironmentSettingCard(maintenance)
        self.restart_adb_card = PushSettingCard(
            tr("重启 ADB"), FluentIcon.SYNC, tr("重启本机 ADB 服务"),
            tr(
                "用当前选择的 ADB 客户端重启本机 5037 服务；"
                "会中断当前连接与投屏，完成后自动重新检测"
            ),
            maintenance,
        )
        maintenance.addSettingCard(self.adb_client_card)
        maintenance.addSettingCard(self.adb_check_card)
        maintenance.addSettingCard(self.restart_adb_card)

        self.adb_check_card.recheck_requested.connect(
            lambda: frame.recheck_adb_environment()
        )
        self.adb_check_card.mode_requested.connect(self._apply_adb_mode)
        self.adb_client_card.client_selected.connect(self._apply_adb_client)
        self.adb_client_card.custom_requested.connect(self._pick_custom_adb)
        self.adb_client_card.rescan_requested.connect(self._rescan_adb_clients)
        self.restart_adb_card.clicked.connect(
            lambda: frame.left_panel.signals.restart_adb_requested.emit()
        )
        current_client = str(self._settings.get("adb_client", CLIENT_PREFERENCE_AUTO))
        if current_client not in CLIENT_SOURCE_TOKENS:
            self.adb_client_card.set_custom_path(current_client)
        self.adb_client_card.set_selection(current_client)
        if not defer_startup_detection:
            self.start_startup_detection()
        self.about_panel = AboutPanel(view)
        self.about_panel.layoutChanged.connect(self._reflow_settings)

        self.expand_layout.addWidget(general)
        self.expand_layout.addWidget(appearance)
        self.expand_layout.addWidget(typography)
        self.expand_layout.addWidget(application)
        self.expand_layout.addWidget(maintenance)
        self.expand_layout.addWidget(self.about_panel)
        self.setWidget(view)

        self.save_card.clicked.connect(self._pick_save_directory)
        self.scan_card.checkedChanged.connect(self._set_continuous_scan)
        self.theme_card.valueChanged.connect(self._set_theme)
        self.scale_card.valueChanged.connect(self._set_ui_scale)
        self.language_card.valueChanged.connect(self._set_language)
        self.accent_card.colorChanged.connect(self._set_accent_color)
        self.mica_card.checkedChanged.connect(self._set_mica_enabled)
        self.pin_card.checkedChanged.connect(frame.set_always_on_top)
        self.log_lines_card.valueChanged.connect(self._set_log_max_lines)
        self.font_family_card.valueChanged.connect(self._apply_typography)
        self.ui_size_card.valueChanged.connect(self._apply_typography)
        self.log_size_card.valueChanged.connect(self._apply_typography)
        self.reset_card.clicked.connect(self._reset_settings)
        # ADB 分组包含展开卡，由原生 ExpandLayout 随动画逐帧调整高度，
        # 不参与普通设置分组的固定高度循环。
        self._setting_groups = (general, appearance, typography, application)
        self._adb_group = maintenance
        original_path = self.save_card.contentLabel
        self.save_card.vBoxLayout.removeWidget(original_path)
        self.save_card.contentLabel = _SettingsPathLabel(self.save_card)
        self.save_card.contentLabel.setObjectName("contentLabel")
        self.save_card.contentLabel.setText(original_path.text())
        original_path.hide()
        original_path.deleteLater()
        self._card_presentations = [
            _SettingsCardPresentation(card, control)
            for card, control in (
                (self.save_card, self.save_card.button),
                (self.scan_card, self.scan_card.switchButton),
                (self.log_lines_card, self.log_lines_card.combo_box),
                (self.theme_card, self.theme_card.combo_box),
                (self.scale_card, self.scale_card.combo_box),
                (self.language_card, self.language_card.combo_box),
                (self.accent_card, self.accent_card.color_button),
                (self.mica_card, self.mica_card.switchButton),
                (self.pin_card, self.pin_card.switchButton),
                (self.font_family_card, self.font_family_card.combo_box),
                (self.ui_size_card, self.ui_size_card.combo_box),
                (self.log_size_card, self.log_size_card.combo_box),
                (self.reset_card, self.reset_card.button),
                (self.diagnostics_card, self.diagnostics_card.button),
                (self.restart_adb_card, self.restart_adb_card.button),
            )
        ]
        # 只在构造时准备静态图标；包装器在绘制时仍按当前主题选色。
        icon_labels = [item.card.iconLabel for item in self._card_presentations]
        icon_labels.extend((
            self.adb_client_card.card.iconLabel, self.adb_check_card.card.iconLabel,
        ))
        for label in icon_labels:
            label.setIcon(cached_fluent_icon(label._icon))
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._refresh_typography)
        self._refresh_typography()

    # ── ADB 页签与客户端选择 ─────────────────────────────────────────────

    def prepare_shutdown(self) -> None:
        """异步关闭前停止设置页动画及客户端探测，不等待窗口最终隐藏。"""
        self._accent_apply_timer.stop()
        self._settings_reflow_timer.stop()
        pending, self._pending_accent = self._pending_accent, None
        if pending is not None:
            # 关闭阶段只持久化最后选择，不再触发全量 QSS；避免退出被 700ms 阻塞。
            self._settings.set("accent_color", normalise_accent_color(pending.name()))
        self._wheel_scroll.prepare_shutdown()
        for card in (self.adb_client_card, self.adb_check_card):
            card.expandAni.stop()
            card.card.expandButton.rotateAni.stop()
        self.adb_client_card.prepare_shutdown()

    def start_startup_detection(self) -> None:
        """主窗就绪后预热一次客户端识别；卡片销毁会撤销尚未投递的回调。"""
        if self._startup_detection_scheduled:
            return
        self._startup_detection_scheduled = True
        QTimer.singleShot(0, self.adb_client_card, self._detect_startup_client)

    def _detect_startup_client(self) -> None:
        """异步预热交付前复核退出状态，避免启动刚取消又派发设备相关查询。"""
        if not getattr(self._frame, "_closing", False):
            self.adb_client_card.start_detection()

    def _apply_adb_mode(self, mode: str) -> None:
        """切换执行模式：只影响后续命令，不重放在途请求。"""

        self.adb_check_card.set_mode(mode)
        self._frame.set_adb_selection_mode(mode)

    def _apply_adb_client(self, value: str) -> None:
        """应用客户端选择：写配置、清两层路径缓存并重新检测执行环境。"""

        text = str(value or "").strip() or CLIENT_PREFERENCE_AUTO
        invalidate_pairing = getattr(self._frame, "invalidate_wireless_pairing", None)
        if callable(invalidate_pairing):
            invalidate_pairing("client_changed")
        set_client_preference(text)
        clear_client_probe_cache()
        invalidate_adb_path_cache()
        reset_adb_program_cache()
        if self._settings.get("adb_client", CLIENT_PREFERENCE_AUTO) != text:
            self._settings.set("adb_client", text)
        self.adb_client_card.set_selection(text)
        self._frame.recheck_adb_environment()
        self.adb_client_card.restart_detection()

    def _pick_custom_adb(self) -> None:
        """选择自定义 adb 可执行文件；取消选择时恢复原显示。"""

        path, _filter = QFileDialog.getOpenFileName(
            self, tr("选择 ADB 可执行文件"), "", tr("所有文件 (*)")
        )
        if not path:
            self.adb_client_card.set_selection(
                str(self._settings.get("adb_client", CLIENT_PREFERENCE_AUTO))
            )
            return
        self.adb_client_card.set_custom_path(path)
        self._apply_adb_client(path)

    def _rescan_adb_clients(self) -> None:
        """重新识别本地 ADB 环境：清缓存并让卡片重新探测。"""

        invalidate_adb_path_cache()
        clear_client_probe_cache()
        self.adb_client_card.start_detection()

    def update_adb_environment(self, snapshot) -> None:
        """自动模式跟随有效后端；手动模式保留选择，能力回退只更新执行状态说明。"""
        # 手动模式回显用户选择；自动模式只显示实际模式，不改变开关类控件状态。
        self.adb_check_card.set_mode(snapshot.selection_mode)
        mode = {
            "auto": tr("自动选择"),
            "fast": tr("手动快速"),
            "native": tr("手动原生"),
        }[snapshot.selection_mode]
        # 这里的分段只描述"用哪条通道"，与设置里的"持续扫描设备"无关：
        # fast_devices 表示设备列表查询可走 5037 直连，fast_shell_devices 表示
        # 逐设备 Shell 已验证通过的数量。
        segments = [tr("模式：{mode}").format(mode=mode)]
        if snapshot.fast_devices:
            segments.append(tr("设备列表：快速直连"))
        else:
            segments.append(tr("设备列表：原生 ADB"))
        if snapshot.checked_devices:
            segments.append(
                tr("设备 Shell {count}/{checked} 台使用快速通道").format(
                    count=snapshot.fast_shell_devices,
                    checked=snapshot.checked_devices,
                )
            )
        else:
            segments.append(tr("设备 Shell 未检查"))
        status = {
            "idle": tr("等待执行环境检测"),
            "checking": tr("正在检查执行环境"),
            "starting_server": tr("正在启动本机 ADB 服务"),
            "retrying": tr("正在恢复执行环境"),
            "ready": tr("执行环境已就绪"),
            "missing_adb": tr("未找到 ADB，请检查安装环境"),
            "custom_server": tr("已配置自定义 ADB 服务，保留原生执行"),
            "host_timeout": tr("本机 ADB 服务响应超时，可重新检测"),
            "host_unavailable": tr("本机 ADB 服务不可用，可重新检测或重启服务"),
            "host_protocol": tr("本机 ADB 服务协议不兼容，保留原生执行"),
            "host_transport": tr("本机 ADB 服务通信异常，可重新检测"),
            "shell_unavailable": tr("部分设备 Shell 未通过验证，保留原生执行"),
        }[snapshot.status]
        segments.append(status)
        content = " · ".join(segments)
        if snapshot.checking and self._last_adb_environment_text:
            # 检测期间保留上一次稳定结果，避免状态行在"检查中"与结果之间来回跳。
            content = tr("检测中…（上次：{previous}）").format(
                previous=self._last_adb_environment_text
            )
        elif not snapshot.checking:
            self._last_adb_environment_text = content
        self.adb_check_card.set_status(content)
        self.adb_check_card.set_recheck_enabled(not snapshot.checking)
        self._reflow_settings()

    def update_diagnostics_summary(self, content: str) -> None:
        """诊断摘要变化后同步重排卡片与分组，保证多行说明和导出按钮可达。"""
        self.diagnostics_card.setContent(content)
        self.diagnostics_card.button.setAccessibleDescription(content)
        self._reflow_settings()

    def _refresh_typography(self, _config=None) -> None:
        """设置字号本身也可即时阅读；仅更新呈现，不触发任何配置写入。"""

        for group in (*self._setting_groups, self._adb_group):
            apply_label_role(group.titleLabel, FontRole.UI, bold=True)
            self._set_setting_font(group.titleLabel, FontRole.UI, bold=True)
            group.titleLabel.adjustSize()
        for card in (self.adb_client_card, self.adb_check_card):
            self._set_setting_font(card.card.titleLabel, FontRole.UI)
            self._set_setting_font(card.card.contentLabel, FontRole.UI_SMALL)
            for label in card.findChildren(QLabel):
                self._set_setting_font(label, FontRole.UI_SMALL)
            for label in (card.card.titleLabel, card.card.contentLabel):
                # 使用最终字体度量，避免沿用上次字号的固定最小高度。
                label.setMinimumHeight(label.sizeHint().height())
            card.card.hBoxLayout.invalidate()
            header_height = max(70, card.card.hBoxLayout.minimumSize().height())
            card.card.setFixedHeight(header_height)
            # 展开动画以 viewport 顶部边距为表头基线，必须与实际表头同步。
            card.setViewportMargins(0, header_height, 0, 0)
            if not card.isExpand:
                card.setFixedHeight(header_height)
            card._adjustViewSize()
        for presentation in self._card_presentations:
            card, control = presentation.card, presentation.control
            apply_label_role(card.titleLabel, FontRole.UI)
            apply_label_role(card.contentLabel, FontRole.UI_SMALL)
            self._set_setting_font(card.titleLabel, FontRole.UI)
            self._set_setting_font(card.contentLabel, FontRole.UI_SMALL)
            control.setMaximumHeight(16777215)
            apply_font_role(control, FontRole.UI)
            if type(control) is QPushButton:
                self._set_setting_font(control, FontRole.UI)
            elif isinstance(control, ComboBox):
                font = BaseStyles.font_for_role(FontRole.UI)
                family = font.family().replace("'", "\\'")
                rule = f"ComboBox {{ font-family: '{family}'; font-size: {font.pointSizeF()}pt; }}"
                set_fluent_font_rule(control, rule)
            for child in control.findChildren(QWidget):
                child.setFont(control.font())
                if isinstance(child, QLabel):
                    self._set_setting_font(child, FontRole.UI)
            control.ensurePolished()
            control.setMinimumHeight(max(32, control.fontMetrics().height() + 14))
        self._reflow_settings()

    @staticmethod
    def _set_setting_font(widget: QWidget, role: FontRole, *, bold: bool = False) -> None:
        """局部覆盖 SettingCard 给普通 QLabel 固定的像素字号，保留其主题颜色。"""

        apply_setting_text_style(widget, role, bold=bold)

    def _reflow_settings(self, *, force: bool = True) -> None:
        """ExpandLayout 使用当前控件高度，先测量卡片再更新分组与页面总高。

        force=False 只用于 resize 的尾沿提交：宽度未变时直接返回，避免滚动条或
        子控件高度回传造成的重复 remove/add。
        """

        if not hasattr(self, "_card_presentations"):
            return
        viewport_width = self.viewport().width()
        if not force and viewport_width == getattr(self, "_settings_reflow_width", None):
            return
        self._settings_reflow_width = viewport_width
        margins = self.expand_layout.contentsMargins()
        width = max(1, viewport_width - margins.left() - margins.right())
        for presentation in self._card_presentations:
            presentation.reflow(width)
        for group in self._setting_groups:
            cards = [item.card for item in self._card_presentations if item.card.parent() is group]
            height = sum(card.height() for card in cards) + max(0, len(cards) - 1) * 2
            group.setFixedHeight(height + group.titleLabel.sizeHint().height() + 12)
        if hasattr(self, "_adb_group"):
            # 保留分组的自由高度，让原生 ExpandLayout 将卡片动画的高度差
            # 逐帧传递给页面；锁定高度会裁切中间帧，直到整页重排才突然展开。
            adb_cards = (self.adb_client_card, self.adb_check_card, self.restart_adb_card)
            content = sum(card.height() for card in adb_cards) + 2 * (len(adb_cards) - 1)
            self._adb_group.resize(
                self._adb_group.width(),
                content + self._adb_group.titleLabel.sizeHint().height() + 12,
            )
        self.about_panel.reflow(width)
        view = self.widget()
        if view is not None:
            view.resize(
                self.viewport().width(),
                self.expand_layout.heightForWidth(self.viewport().width()),
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 卡片换行只依赖可用宽度；高度变化由滚动容器承担，不重挂所有操作控件。
        # 拖动窗口时只保留最后一次宽度，字体/文案/状态变化仍同步重排。
        if self.viewport().width() != getattr(self, "_settings_reflow_width", None):
            # 首帧/拖动起点先同步落实一次，后续同一次拖动只保留尾沿；这样既有即时
            # 反馈，又不会在每个像素级 resize 上重挂所有卡片。
            if not self._settings_reflow_timer.isActive():
                self._reflow_settings()
            self._settings_reflow_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 首次可见且宽度确实变化时同步落实，不能等 60ms 定时器让首帧沿用旧网格。
        self._settings_reflow_timer.stop()
        if self.viewport().width() != getattr(self, "_settings_reflow_width", None):
            self._reflow_settings()

    def _pick_save_directory(self) -> None:
        self._frame._on_save_path_clicked()
        value = str(self._settings.get("save_directory", "") or tr("系统默认目录"))
        self.save_card.setContent(value)
        self._reflow_settings()

    def _set_continuous_scan(self, checked: bool) -> None:
        self._settings.set("continuous_device_scan", bool(checked))
        self._frame.set_continuous_scan(bool(checked))

    def _set_theme(self, label: str) -> None:
        mode = self.THEME_MODES.get(label, "System")
        BaseStyles.switch_theme(mode)

    def _set_ui_scale(self, label: str) -> None:
        """只保存下次启动比例，当前窗口继续使用创建 QApplication 时的 DPI。"""

        self._settings.set("ui_scale", self.SCALE_VALUES[label])

    def _set_language(self, label: str) -> None:
        """保存语言偏好并提示重启，避免重建正在持有设备任务的页面。"""
        language = self._language_values[label]
        if language == self._settings.get("language", "Auto"):
            return
        self._settings.set("language", language)
        self._show_language_restart_hint()

    def _show_language_restart_hint(self) -> None:
        show_toast(
            self.window() or self,
            tr("设置已保存"),
            tr("语言设置将在重启应用后生效"),
            level="success",
        )

    def _set_accent_color(self, color: QColor) -> None:
        """记录取色器最新颜色；停止拖动 120ms 后再应用，避免逐帧全量重建。"""
        self._pending_accent = QColor(color)
        self._accent_apply_timer.start()

    def _apply_pending_accent(self) -> None:
        """由 120ms 防抖计时器触发，应用并持久化最后一次强调色；pending 为空时无操作。"""
        color, self._pending_accent = self._pending_accent, None
        if color is None:
            return
        value = BaseStyles.set_accent_color(color.name())
        self._settings.set("accent_color", value)

    def _set_mica_enabled(self, checked: bool) -> None:
        enabled = bool(checked)
        self._settings.set("mica_enabled", enabled)
        self._frame.setMicaEffectEnabled(enabled)
        self._frame._refresh_window_chrome_theme()

    def _set_log_max_lines(self, value: str) -> None:
        lines = int(value)
        self._settings.set("log_max_lines", lines)

    def _apply_typography(self, _value: str) -> None:
        family = self.font_family_card.value()
        self._settings.set_many(
            {
                "font_family": "" if family == tr("系统默认") else family,
                "ui_font_size": int(self.ui_size_card.value()),
                "log_font_size": int(self.log_size_card.value()),
            }
        )
        BaseStyles.reload_from_settings()

    def _reset_settings(self) -> None:
        # 重置会立即写默认色；必须取消 120ms 内的待应用颜色，否则旧色会在之后覆盖默认。
        self._accent_apply_timer.stop()
        self._pending_accent = None
        previous_language = self._settings.get("language", "Auto")
        self._settings.reset()

        # reset() 会直接替换配置快照；显式回填全部可见卡片，避免页面仍显示
        # 重置前的值。阻断卡片信号后再统一应用运行态，防止重复写盘。
        blocked_cards = (
            self.scan_card,
            self.theme_card,
            self.scale_card,
            self.language_card,
            self.accent_card,
            self.mica_card,
            self.pin_card,
            self.log_lines_card,
            self.font_family_card,
            self.ui_size_card,
            self.log_size_card,
        )
        blockers = [QSignalBlocker(card) for card in blocked_cards]
        self.scan_card.setChecked(bool(self._settings.get("continuous_device_scan", True)))
        theme = str(self._settings.get("theme", "System"))
        self.theme_card.combo_box.setCurrentText(
            self.THEME_LABELS.get(theme, tr("跟随系统"))
        )
        self.scale_card.combo_box.setCurrentText(
            self.SCALE_LABELS[normalise_ui_scale(self._settings.get("ui_scale", "Auto"))]
        )
        self.language_card.combo_box.setCurrentText(
            self.LANGUAGE_LABELS[normalise_language(self._settings.get("language", "Auto"))]
        )
        self.accent_card.set_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        self.mica_card.setChecked(bool(self._settings.get("mica_enabled", True)))
        self.pin_card.setChecked(bool(self._settings.get("always_on_top", False)))
        self.log_lines_card.combo_box.setCurrentText(
            str(self._settings.get("log_max_lines", 2000))
        )
        family = str(self._settings.get("font_family", "") or tr("系统默认"))
        self.font_family_card.combo_box.setCurrentText(family)
        self.ui_size_card.combo_box.setCurrentText(
            str(self._settings.get("ui_font_size", 12))
        )
        self.log_size_card.combo_box.setCurrentText(
            str(self._settings.get("log_font_size", 9))
        )

        self.save_card.setContent(
            str(self._settings.get("save_directory", "") or tr("系统默认目录"))
        )
        del blockers

        self.adb_check_card.set_mode("auto")
        self._apply_adb_client(CLIENT_PREFERENCE_AUTO)

        BaseStyles.switch_theme(theme)
        BaseStyles.set_accent_color(
            str(self._settings.get("accent_color", "#0F6CBD"))
        )
        BaseStyles.reload_from_settings()
        self._frame.setMicaEffectEnabled(
            bool(self._settings.get("mica_enabled", True))
        )
        self._frame.set_continuous_scan(
            bool(self._settings.get("continuous_device_scan", True))
        )
        self._frame.set_always_on_top(bool(self._settings.get("always_on_top", False)))
        self._frame.restore_default_window_size()
        if previous_language != self._settings.get("language", "Auto"):
            self._show_language_restart_hint()


class _LocalizedSwitchSettingCard(SwitchSettingCard):
    """保持原生设置开关的信号契约，更新状态后仍使用当前语言标签。"""

    def setValue(self, isChecked: bool) -> None:
        # 上游 setValue 会覆盖 SwitchButton.onText/offText；恢复默认和手动
        # 切换都会经过此边界，因此在原生更新后统一还原当前语言并重新度量。
        super().setValue(isChecked)
        # 同步策略可能在 checkedChanged 内修正有效状态，标签必须读取最终投影。
        self.switchButton.setText(tr("开") if self.isChecked() else tr("关"))


class ComboSettingCard(SettingCard):
    """参考 ComboBoxSettingCard 的项目设置适配版，不引入第二套配置系统。"""

    valueChanged = Signal(str)

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        values: list[str],
        current: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, title, content, parent)
        self.combo_box = ComboBox(self)
        configure_combo_menu(self.combo_box)
        self.combo_box.addItems(values)
        if self.combo_box.findText(current) < 0:
            self.combo_box.addItem(current)
        self.combo_box.setCurrentText(current)
        self.hBoxLayout.addWidget(self.combo_box, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.combo_box.currentTextChanged.connect(self.valueChanged)

    def value(self) -> str:
        return self.combo_box.currentText()


class AccentColorSettingCard(SettingCard):
    """参考 CustomColorSettingCard 的 AppSettings 适配版。"""

    colorChanged = Signal(QColor)

    def __init__(
        self,
        icon,
        title: str,
        content: str,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, title, content, parent)
        self.color_button = ColorPickerButton(
            QColor(color),
            tr("选择 ADBLab 强调色"),
            self,
        )
        self.color_button.setToolTip(tr("选择主要按钮和选中状态使用的颜色"))
        self.hBoxLayout.addWidget(self.color_button, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.color_button.colorChanged.connect(self.colorChanged.emit)

    def set_color(self, color: str) -> None:
        blocker = QSignalBlocker(self.color_button)
        self.color_button.setColor(QColor(color))
        del blocker


__all__ = [
    "ActionCard",
    "ActionCardView",
    "AccentColorSettingCard",
    "ComboSettingCard",
    "DeviceContextCard",
    "GalleryPage",
    "HomePage",
    "SettingsPage",
    "WorkspaceAreaPage",
    "WorkspaceSectionPage",
]
