"""验证侧栏和独立遥控器实际加载打包翻译，同时保留设备操作协议。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QLabel

from gui import i18n
from gui.widgets.remote_toolbar import RemoteToolbar

pytestmark = pytest.mark.ui

_LABELS = (
    ("独立遥控器", "Standalone controller", "獨立遙控器"),
    ("打开独立遥控器", "Open standalone controller", "開啟獨立遙控器"),
    ("投屏操控", "Mirroring controls", "投屏操控"),
    ("当前投屏设备", "Current mirrored device", "目前投屏裝置"),
    ("当前投屏设备不可用", "Current mirrored device is unavailable", "目前投屏裝置無法使用"),
    ("更多操作", "More controls", "更多操作"),
    ("关闭更多操作", "Close more controls", "關閉更多操作"),
    ("屏幕与通知", "Screen and notifications", "螢幕與通知"),
    ("系统操作", "System controls", "系統操作"),
    ("媒体控制", "Media controls", "媒體控制"),
    ("展开侧栏", "Expand sidebar", "展開側欄"),
    ("收起侧栏", "Collapse sidebar", "收起側欄"),
    (
        "点按电源键，切换屏幕开关",
        "Press the power key to toggle the screen",
        "點按電源鍵，切換螢幕開關",
    ),
    (
        "点按切换屏幕开关；按住 0.6 秒触发长按",
        "Tap to toggle the screen; hold for 0.6 seconds to send a long press",
        "點按切換螢幕開關；按住 0.6 秒觸發長按",
    ),
    ("{action}（作用于{target}）", "{action} (target: {target})", "{action}（套用至{target}）"),
    (
        "操作当前已选的 {count} 台在线设备 · 与投屏侧栏的单台控制独立",
        "Controls the {count} selected online devices · Independent of each mirroring sidebar",
        "操作目前已選的 {count} 台在線裝置 · 與投屏側欄的單台控制獨立",
    ),
    (
        "请在主窗口选择在线设备；无需先启动投屏。",
        "Select online devices in the main window; mirroring does not need to be started.",
        "請在主視窗選擇在線裝置；無需先啟動投屏。",
    ),
    (
        "投屏窗口旁显示单台控制侧栏；更多按键和批量操作可打开独立遥控器。",
        "A sidebar beside each mirroring window controls that device. "
        "Open the standalone controller for more keys and batch actions.",
        "投屏視窗旁顯示單台控制側欄；更多按鍵和批次操作可開啟獨立遙控器。",
    ),
    (
        "按键、手势与批量操作可使用独立遥控器，无需启动镜像。",
        "Use the standalone controller for keys, gestures and batch actions; "
        "mirroring is not required.",
        "按鍵、手勢與批次操作可使用獨立遙控器，無需啟動鏡像。",
    ),
    (
        "操作主窗口当前已选的在线设备，无需启动镜像",
        "Control the online devices selected in the main window; mirroring is not required",
        "操作主視窗目前已選的在線裝置，無需啟動鏡像",
    ),
)


@pytest.fixture
def remote_language(qt_application, request):
    language = request.param
    translators = i18n.install_translators(qt_application, language)
    yield language
    for translator in reversed(translators):
        qt_application.removeTranslator(translator)
        translator.deleteLater()


@pytest.mark.parametrize("language,index", [("zh_CN", 0), ("en_US", 1), ("zh_HK", 2)])
def test_controller_and_sidebar_labels_are_embedded_in_each_language(language, index):
    """直接查询资源可区分中文译文与缺失词条的源文案回退。"""
    translator = QTranslator()
    assert translator.load(f":/adblab/i18n/adblab.{language}.qm")
    for labels in _LABELS:
        assert translator.translate("ADBLab", labels[0]) == labels[index], labels[0]


@pytest.mark.parametrize("remote_language", ["zh_CN", "en_US", "zh_HK"], indirect=True)
def test_toolbar_translates_dynamic_groups_and_both_collapse_states(remote_language):
    expected = {
        "zh_CN": (
            "当前投屏设备", "更多设备操作", "更多操作", "关闭更多操作",
            ["屏幕与通知", "滑动手势", "系统操作", "媒体控制"], "收起侧栏", "展开侧栏",
        ),
        "en_US": (
            "Current mirrored device", "More device actions", "More controls",
            "Close more controls",
            ["Screen and notifications", "Swipe gestures", "System controls", "Media controls"],
            "Collapse sidebar", "Expand sidebar",
        ),
        "zh_HK": (
            "目前投屏裝置", "更多裝置操作", "更多操作", "關閉更多操作",
            ["螢幕與通知", "滑動手勢", "系統操作", "媒體控制"], "收起側欄", "展開側欄",
        ),
    }[remote_language]
    target, more, title, close, groups, collapse, expand = expected
    toolbar = RemoteToolbar()
    try:
        assert toolbar._target.text() == target
        assert toolbar._more_button.accessibleName() == more
        assert toolbar._more_button.toolTip() == more
        assert toolbar._popup.findChild(QLabel, "remoteToolbarHeading").text() == title
        assert any(button.accessibleName() == close for button in toolbar._popup.findChildren(
            type(toolbar._more_button),
        ))
        assert [label.text() for label in toolbar._popup_content.findChildren(
            QLabel, "remoteToolbarGroup",
        )] == groups
        assert toolbar._collapse_button.accessibleName() == collapse
        toolbar._collapse_button.click()
        assert toolbar.collapsed
        assert toolbar._collapse_button.accessibleName() == expand
        assert toolbar._collapse_button.toolTip() == expand
        toolbar._collapse_button.click()
        assert not toolbar.collapsed
        assert toolbar._collapse_button.accessibleName() == collapse
    finally:
        toolbar.dispose()
        toolbar.deleteLater()


@pytest.mark.parametrize("remote_language", ["zh_CN", "en_US", "zh_HK"], indirect=True)
def test_translated_action_labels_keep_fixed_target_description_and_protocol(remote_language):
    expected = {
        "zh_CN": ("返回", "上滑", "播放/暂停", "返回（作用于Device 2）", "当前投屏设备不可用"),
        "en_US": (
            "Back", "Swipe up", "Play/Pause", "Back (target: Device 2)",
            "Current mirrored device is unavailable",
        ),
        "zh_HK": ("返回", "上滑", "播放/暫停", "返回（套用至Device 2）", "目前投屏裝置無法使用"),
    }[remote_language]
    back, swipe, play, tooltip, unavailable = expected
    toolbar = RemoteToolbar()
    requested = []
    toolbar.key_requested.connect(lambda value: requested.append(("key", value)))
    toolbar.action_requested.connect(lambda value: requested.append(("action", value)))
    try:
        back_button = toolbar._commands["BACK"][1]
        swipe_button = toolbar._commands["swipe_up"][1]
        play_button = toolbar._commands["MEDIA_PLAY"][1]
        assert back_button.toolTip() == unavailable
        toolbar.set_target_label("Device 2")
        toolbar.set_available(True)
        assert back_button.accessibleName() == back
        assert swipe_button.text() == swipe
        assert play_button.text() == play
        assert back_button.toolTip() == tooltip
        assert back_button.accessibleDescription() == tooltip
        back_button.click()
        swipe_button.click()
        play_button.click()
        assert requested == [("key", "BACK"), ("action", "swipe_up"), ("key", "MEDIA_PLAY")]
        toolbar.set_available(False)
        assert back_button.toolTip() == unavailable
    finally:
        toolbar.dispose()
        toolbar.deleteLater()


@pytest.mark.parametrize("remote_language", ["zh_CN", "en_US", "zh_HK"], indirect=True)
def test_power_tooltip_and_accessible_description_explain_tap_and_hold(remote_language):
    tooltip, unavailable = {
        "zh_CN": (
            "电源（作用于Device 2）\n点按切换屏幕开关；按住 0.6 秒触发长按",
            "当前投屏设备不可用",
        ),
        "en_US": (
            "Power (target: Device 2)\n"
            "Tap to toggle the screen; hold for 0.6 seconds to send a long press",
            "Current mirrored device is unavailable",
        ),
        "zh_HK": (
            "電源（套用至Device 2）\n點按切換螢幕開關；按住 0.6 秒觸發長按",
            "目前投屏裝置無法使用",
        ),
    }[remote_language]
    toolbar = RemoteToolbar()
    try:
        power = toolbar._commands["POWER"][1]
        toolbar.set_target_label("Device 2")
        toolbar.set_available(True)
        assert power.toolTip() == tooltip
        assert power.accessibleDescription() == tooltip
        toolbar.set_available(False)
        assert power.toolTip() == unavailable
        assert power.accessibleDescription() == unavailable
    finally:
        toolbar.dispose()
        toolbar.deleteLater()
