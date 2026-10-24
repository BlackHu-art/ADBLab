"""集中定义设置默认值与字段规范化，不访问设置文件。"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from utils.adb_resolver import CLIENT_SOURCE_TOKENS
from utils.console_colors import normalise_console_level

# RemotePanel 只允许通过这组正式键跨会话保存 scrcpy 表单值。该映射同时作为
# AppSettings 加载白名单的一部分，使旧版本已经写入 JSON 的同名键无需迁移即可恢复。
SCRCPY_SETTING_DEFAULTS = {
    "scrcpy_preset": "Smooth",
    "scrcpy_maxsize": "1024",
    "scrcpy_fps": "30",
    "scrcpy_codec": "h264",
    "scrcpy_buffer": "50",
    "scrcpy_bitrate": "4",
    "scrcpy_orientation": "0",
}


# Auto 保留平台的 DPI 策略；手动比例只在下一次 GUI 启动前传给 Qt。
UI_SCALE_OPTIONS = ("Auto", 1.0, 1.25, 1.5, 1.75, 2.0)
LANGUAGE_OPTIONS = ("Auto", "zh_CN", "zh_HK", "en_US")


def normalise_language(value: Any) -> str:
    """限定为受支持的界面语言；无效值回退到跟随系统。"""
    return value if isinstance(value, str) and value in LANGUAGE_OPTIONS else "Auto"


def normalise_ui_scale(value: Any) -> str | float:
    """只接受设置页提供的显示比例，非法值安全回退到跟随系统。"""
    if isinstance(value, bool):
        return "Auto"
    if isinstance(value, str) and value.strip().casefold() == "auto":
        return "Auto"
    try:
        factor = float(value)
    except (TypeError, ValueError, OverflowError):
        return "Auto"
    return factor if factor in UI_SCALE_OPTIONS[1:] else "Auto"


DEFAULTS = {
    # 空字符串表示跟随 Qt 提供的系统默认界面字体。
    "font_family": "",
    "ui_font_size": 12,
    "ui_scale": "Auto",
    "language": "Auto",
    "log_font_size": 9,
    "save_directory": "",
    "log_max_lines": 2000,
    "console_log_level": "DEBUG",
    "adb_client": "auto",
    "confirm_dangerous_ops": True,
    "continuous_device_scan": True,
    "device_scan_interval_ms": 15000,
    "always_on_top": False,
    "performance_log_threshold_ms": 300,
    "monkey_params": {
        "events": 10000,
        "throttle": 300,
        "touch": 30,
        "motion": 15,
        "trackball": 0,
        "nav": 20,
        "majornav": 10,
        "syskeys": 5,
        "appswitch": 8,
        "anyevent": 10,
        "pinch": 2,
        # 各事件比例须合计为 100%，启动 Monkey 前会再次统一校验。
        "ignore_crashes": True,
        "ignore_timeouts": True,
        "ignore_security": True,
    },
    "theme": "System",
    "accent_color": "#0F6CBD",
    "mica_enabled": True,
    "window_width": 1250,
    "window_height": 700,
    "left_panel_width": 400,
    "right_panel_width": 600,
    "panel_split_ratio": 0.5,
    "device_log_split_ratio": 0.6,
    **SCRCPY_SETTING_DEFAULTS,
}

_FONT_SIZE_RULES = {
    "ui_font_size": (8, 22, 12),
    "log_font_size": (7, 16, 9),
}


def _normalise_integer(value: Any, default: int) -> int:
    """读取整型设置；布尔值、非整数和转换失败均回退到默认值。"""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _normalise_adb_client(value: Any) -> str:
    """限定 ADB 客户端选择：自动、命名来源或绝对路径；其余回退自动。

    绝对路径只做形态校验，不检查文件是否存在：盘符临时不可用时不能丢配置，
    缺失状态由设置界面和运行时诊断显示。
    """

    if not isinstance(value, str):
        return DEFAULTS["adb_client"]
    text = value.strip()
    if not text:
        return DEFAULTS["adb_client"]
    if text in CLIENT_SOURCE_TOKENS:
        return text
    if os.path.isabs(text):
        return text[:512]
    return DEFAULTS["adb_client"]


def normalise_setting(key: str, value: Any) -> Any:
    """校验需要稳定边界的设置，其他设置保持原有类型与行为。"""

    if key == "ui_scale":
        return normalise_ui_scale(value)

    if key == "language":
        return normalise_language(value)

    if key == "save_directory":
        # 路径中的首尾空白可能属于真实目录名，不能随类型校验一并裁剪。
        return value if isinstance(value, str) else DEFAULTS[key]

    if key == "log_max_lines":
        count = _normalise_integer(value, DEFAULTS[key])
        return count if count > 0 else DEFAULTS[key]

    if key == "console_log_level":
        return normalise_console_level(value)

    if key == "adb_client":
        return _normalise_adb_client(value)

    if key == "monkey_params":
        defaults = DEFAULTS[key]
        if not isinstance(value, dict):
            return deepcopy(defaults)
        # 只规范已知字段的类型；比例合计和执行范围仍由 Monkey 启动边界校验。
        # 保留未来版本的未知字段，普通版本的字段清理由既有迁移流程负责。
        normalised = deepcopy(value)
        for field, default in defaults.items():
            item = value.get(field, default)
            if isinstance(default, bool):
                normalised[field] = item if isinstance(item, bool) else default
            else:
                if field == "throttle" and isinstance(item, str):
                    text = item.strip()
                    item = text[:-2].rstrip() if text.casefold().endswith("ms") else text
                normalised[field] = _normalise_integer(item, default)
        return normalised

    if key in SCRCPY_SETTING_DEFAULTS:
        if value is None or isinstance(value, (bool, dict, list, tuple, set)):
            return SCRCPY_SETTING_DEFAULTS[key]
        text = str(value).strip()
        return text[:128] if text else SCRCPY_SETTING_DEFAULTS[key]

    if key == "theme":
        aliases = {
            "auto": "System",
            "system": "System",
            "light": "Light",
            "dark": "Dark",
        }
        return aliases.get(str(value).strip().casefold(), DEFAULTS[key])

    if key == "accent_color":
        text = str(value).strip().upper()
        if len(text) == 7 and text.startswith("#"):
            try:
                int(text[1:], 16)
            except ValueError:
                pass
            else:
                return text
        return DEFAULTS[key]

    if key == "mica_enabled":
        return value if isinstance(value, bool) else DEFAULTS[key]

    if key == "font_family":
        if not isinstance(value, str):
            return DEFAULTS[key]
        family = value.strip()
        if family.casefold() == "system default":
            return ""
        return family[:128]

    if key in _FONT_SIZE_RULES:
        minimum, maximum, default = _FONT_SIZE_RULES[key]
        if isinstance(value, bool):
            return default
        try:
            size = int(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return max(minimum, min(maximum, size))

    if key in {"panel_split_ratio", "device_log_split_ratio"}:
        if isinstance(value, bool):
            return DEFAULTS[key]
        try:
            ratio = float(value)
        except (TypeError, ValueError, OverflowError):
            return DEFAULTS[key]
        return max(0.2, min(0.7, ratio))

    return value
