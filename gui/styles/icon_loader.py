"""将操作语义映射到 Fluent 图标，补充组件库缺少的设备轮廓。

Fluent 按钮直接使用 FluentIcon，保留强调、禁用和选中状态的原生绘制；
Qt 窗口与菜单通过 qicon() 使用相同图标和主题。
"""

from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QIcon
from qfluentwidgets import FluentIcon, FluentIconBase, Theme
from qfluentwidgets.common.icon import SvgIconEngine, getIconColor

from utils.resource_path import resource_path


class DeviceIcon(FluentIconBase):
    """通过 Fluent 扩展接口复用已授权的手机轮廓，避免用电话听筒表示设备。"""

    def path(self, theme=Theme.AUTO) -> str:
        """资源定位同时支持源码与打包后的解压目录。"""
        return resource_path("resources/icons/device-mobile.svg")

    def icon(self, theme=Theme.AUTO, color: QColor | str | None = None) -> QIcon:
        """颜色由当前主题或调用方确定，禁用和选中状态仍由 Fluent 引擎处理。"""
        svg = Path(self.path(theme)).read_text(encoding="utf-8")
        tint = QColor(color if color is not None else getIconColor(theme)).name()
        return QIcon(SvgIconEngine(svg.replace("currentColor", tint)))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes):
        """导航与图标控件直接绘制时使用同一份主题着色。"""
        color = attributes.get("fill") or attributes.get("stroke")
        self.icon(theme, color).paint(painter, QRectF(rect).toRect())


DEVICE_ICON = DeviceIcon()

# 旧文件名只作兼容键；多个文件类型可复用参考组件中的同一语义图标。
_FLUENT_ICONS = {
    name: icon
    for icon, names in (
        (FluentIcon.APPLICATION, ("android-logo.svg", "target.svg", "square.svg")),
        (FluentIcon.ZIP_FOLDER, ("archive.svg", "file-archive.svg", "file-zip.svg")),
        (FluentIcon.ROTATE, ("arrow-counter-clockwise.svg", "device-rotate.svg")),
        (FluentIcon.DOWN, ("arrow-down.svg",)),
        (FluentIcon.LEFT_ARROW, ("arrow-left.svg", "caret-left.svg")),
        (FluentIcon.RIGHT_ARROW, ("arrow-right.svg", "caret-right.svg")),
        (FluentIcon.EMBED, ("arrow-square-in.svg",)),
        (FluentIcon.SHARE, ("arrow-square-out.svg", "upload-simple.svg", "tray-arrow-up.svg")),
        (FluentIcon.RETURN, ("arrow-u-left-up.svg", "arrow-u-up-left.svg")),
        (FluentIcon.UP, ("arrow-up.svg",)),
        (FluentIcon.SYNC, ("arrows-clockwise.svg", "repeat.svg")),
        (FluentIcon.ALIGNMENT, ("arrows-left-right.svg",)),
        (FluentIcon.REMOVE, ("backspace.svg",)),
        (FluentIcon.IOT, ("battery-full.svg",)),
        (FluentIcon.BLUETOOTH, ("bluetooth.svg",)),
        (FluentIcon.MEGAPHONE, ("broadcast.svg",)),
        (FluentIcon.BROOM, ("broom.svg",)),
        (FluentIcon.DEVELOPER_TOOLS, ("bug.svg", "cpu.svg")),
        (FluentIcon.CAMERA, ("camera.svg",)),
        (FluentIcon.PIE_SINGLE, ("chart-bar.svg",)),
        (FluentIcon.SPEED_HIGH, ("chart-line.svg", "speedometer.svg")),
        (FluentIcon.MESSAGE, ("chat-text.svg",)),
        (FluentIcon.ACCEPT, ("check-circle.svg",)),
        (FluentIcon.CHECKBOX, ("check-square.svg",)),
        (FluentIcon.PASTE, ("clipboard-text.svg",)),
        (FluentIcon.HISTORY, ("clock.svg",)),
        (FluentIcon.CLOUD_DOWNLOAD, ("cloud-arrow-down.svg",)),
        (FluentIcon.COPY, ("copy.svg",)),
        (FluentIcon.LIBRARY, ("database.svg", "memory.svg")),
        (DEVICE_ICON, ("device-mobile.svg",)),
        (FluentIcon.PHONE, ("phone-call.svg",)),
        (FluentIcon.DOWNLOAD, ("download-simple.svg", "tray-arrow-down.svg")),
        (FluentIcon.ERASE_TOOL, ("eraser.svg",)),
        (FluentIcon.SAVE_AS, ("file-arrow-down.svg",)),
        (FluentIcon.MUSIC, ("file-audio.svg",)),
        (FluentIcon.CODE, (
            "file-code.svg", "file-css.svg", "file-html.svg", "file-js.svg", "file-py.svg",
            "file-sql.svg",
        )),
        (FluentIcon.DOCUMENT, (
            "file-csv.svg", "file-md.svg", "file-pdf.svg", "file-text.svg", "file-txt.svg",
            "file-xls.svg", "file.svg",
        )),
        (FluentIcon.PHOTO, (
            "file-image.svg", "file-jpg.svg", "file-png.svg", "file-svg.svg", "image.svg",
            "image-broken.svg",
        )),
        (FluentIcon.SETTING, ("file-ini.svg", "gear.svg")),
        (FluentIcon.ADD, ("file-plus.svg",)),
        (FluentIcon.VIDEO, ("file-video.svg", "video-camera.svg")),
        (FluentIcon.SAVE, ("floppy-disk.svg",)),
        (FluentIcon.FOLDER, ("folder-open.svg", "folder.svg")),
        (FluentIcon.FOLDER_ADD, ("folder-plus.svg",)),
        (FluentIcon.FULL_SCREEN, ("frame-corners.svg",)),
        (FluentIcon.HOME, ("house.svg",)),
        (FluentIcon.INFO, ("info.svg", "warning.svg")),
        (FluentIcon.COMMAND_PROMPT, ("keyboard.svg", "terminal-window.svg", "terminal.svg")),
        (FluentIcon.CANCEL, (
            "link-break.svg", "prohibit.svg", "skull.svg", "stop-circle.svg", "x-circle.svg",
        )),
        (FluentIcon.LINK, ("link.svg",)),
        (FluentIcon.MENU, ("list-bullets.svg", "list.svg")),
        (FluentIcon.FINGERPRINT, ("lock.svg",)),
        (FluentIcon.ZOOM_OUT, ("magnifying-glass-minus.svg",)),
        (FluentIcon.ZOOM_IN, ("magnifying-glass-plus.svg",)),
        (FluentIcon.SEARCH, ("magnifying-glass.svg",)),
        (FluentIcon.PIN, ("map-pin.svg",)),
        (FluentIcon.PROJECTOR, ("monitor-play.svg",)),
        (FluentIcon.UNIT, ("number-square-one.svg",)),
        (FluentIcon.EDIT, ("pencil-simple.svg",)),
        (FluentIcon.PLAY, ("play.svg",)),
        (FluentIcon.CONNECT, ("plug.svg",)),
        (FluentIcon.POWER_BUTTON, ("power.svg",)),
        (FluentIcon.VIEW, ("radio-button.svg",)),
        (FluentIcon.ROBOT, ("robot.svg",)),
        (FluentIcon.SCROLL, ("scroll.svg",)),
        (FluentIcon.SKIP_BACK, ("skip-back.svg",)),
        (FluentIcon.SKIP_FORWARD, ("skip-forward.svg",)),
        (FluentIcon.VOLUME, ("speaker-high.svg",)),
        (FluentIcon.MUTE, ("speaker-low.svg",)),
        (FluentIcon.TILES, ("squares-four.svg",)),
        (FluentIcon.ADD_TO, ("stack-plus.svg",)),
        (FluentIcon.HEART, ("star.svg",)),
        (FluentIcon.FONT, ("text-aa.svg",)),
        (FluentIcon.DELETE, ("trash.svg",)),
        (FluentIcon.LAYOUT, ("tree-structure.svg",)),
        (FluentIcon.PEOPLE, ("user-switch.svg",)),
        (FluentIcon.WIFI, ("wifi-high.svg",)),
        (FluentIcon.CLOSE, ("x.svg",)),
    )
    for name in names
}


def get_fluent_icon(name: str) -> FluentIconBase:
    """解析操作语义；遗漏映射立即报错，避免界面悄然显示空图标。"""

    return _FLUENT_ICONS[name]


def get_themed_icon(name: str) -> QIcon:
    """为 Qt 原生 API 提供随主题更新的 QIcon，绘制由 qfluentwidgets 负责。"""

    return get_fluent_icon(name).qicon()
