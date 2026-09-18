"""集中定义 spec 与 CLI 的资源白名单，不导入 Qt 或 PyInstaller。"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON_DATA = (
    ("resources/icons", "resources/icons"),
    ("resources/images/gallery_header.png", "resources/images"),
    ("resources/images/LICENSE.gallery.txt", "licenses/gallery"),
    ("resources/app_settings.json", "resources"),
    ("resources/connected_devices.yaml", "resources"),
    ("resources/chkbugreport-0.5-215.jar", "resources"),
    ("resources/app-icon-helper.jar", "resources"),
    ("resources/ZFB.jpg", "resources"),
    ("THIRD_PARTY_NOTICES.md", "licenses"),
    ("mobileperf/LICENSE", "licenses/mobileperf"),
    ("mobileperf/extlib/xlsxwriter/LICENSE.txt", "licenses/xlsxwriter"),
    ("icon.ico", "."),
    ("build/runtime-helpers", "runtime-helpers"),
)
WINDOWS_DATA = (("scrcpy-win64", "scrcpy-win64"),)
SUBMODULE_PACKAGES = ("mobileperf", "qfluentwidgets")


def resource_datas(platform: str | None = None) -> list[tuple[str, str]]:
    """返回当前目标平台的独立列表，Windows 工具不进入其他平台产物。"""
    platform = sys.platform if platform is None else platform
    return [*COMMON_DATA, *(WINDOWS_DATA if platform == "win32" else ())]


def collection_options(platform: str | None = None, *, root: Path | None = None) -> list[str]:
    """生成无 shell 拼接的 CLI 参数，与 spec 共用同一资源及子模块清单。"""
    platform = sys.platform if platform is None else platform
    separator = ";" if platform == "win32" else ":"
    options = []
    for source, destination in resource_datas(platform):
        if root is not None:
            source = str(root / source)
        options.extend(("--add-data", f"{source}{separator}{destination}"))
    for package in SUBMODULE_PACKAGES:
        options.extend(("--collect-submodules", package))
    return options
