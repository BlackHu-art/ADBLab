"""集中判断原生窗口材质的系统支持范围。"""

import ctypes
import sys
from ctypes import wintypes


def is_mica_supported() -> bool:
    """云母材质需要 Windows 11；旧系统与其他平台保留实色窗口。"""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


def set_dwm_attribute(hwnd: int, attribute: int, value: int) -> bool:
    """设置原生窗口属性；独立函数签名避免第三方修改 ctypes 全局缓存造成调用失败。"""
    if sys.platform != "win32":
        return False
    try:
        setter = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
    except (AttributeError, OSError):
        return False
    setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    setter.restype = ctypes.c_long
    data = ctypes.c_int(value)
    return setter(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0


def sync_mica_backdrop(hwnd: int, enabled: bool) -> bool:
    """同步 Windows 云母状态，关闭时显式清除上游遗留的系统 backdrop。"""
    if not is_mica_supported():
        return False
    if sys.getwindowsversion().build < 22523:
        return set_dwm_attribute(hwnd, 1029, int(enabled))
    # DWMSBT_NONE 必须使用 1；AUTO 会让 DWM 继续推断窗口已有的材质。
    return set_dwm_attribute(hwnd, 38, 2 if enabled else 1)
