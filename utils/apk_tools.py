"""定位本地 APK 分析工具；运行时不联网，不修改系统环境。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from utils.resource_path import resource_path
from utils.runtime_tools import bundled_tool_path
from utils.tool_manifest import get_aapt2_bundle


def resolve_apk_tool() -> str | None:
    """优先返回当前平台的完整内置 AAPT2，缺失时兼容 PATH 中的 aapt/aapt2。

    资源路径和 onefile 稳定缓存复用统一入口；只选择可用文件，不执行探测命令。
    不缓存缺失结果，源码准备工具后下一次解析即可重试。
    """
    bundle = get_aapt2_bundle()
    if bundle is not None:
        source = Path(resource_path(bundle.directory))
        # 旧运行时缓存不能掩盖本次安装包缺失的入口或许可证。
        if all((source / name).is_file() for name in bundle.required_files):
            executable = Path(bundled_tool_path(
                bundle.directory, bundle.executable, verify_tree=True,
            ))
            complete = all((executable.parent / name).is_file() for name in bundle.required_files)
            if complete and (os.name == "nt" or os.access(executable, os.X_OK)):
                return str(executable)
    return shutil.which("aapt") or shutil.which("aapt2")
