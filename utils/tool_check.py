"""独立检查随包工具，不允许系统 PATH 掩盖漏打包，也不连接设备。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from core.exec import CommandRunner
from utils.resource_path import resource_path
from utils.runtime_tools import bundled_tool_path
from utils.tool_manifest import get_tool_bundle


def check_bundled_tools() -> list[tuple[str, bool, str]]:
    """检查资源、缓存和版本命令；未承诺内置工具的平台沿用环境工具策略。"""
    bundle = get_tool_bundle()
    if bundle is None:
        return []
    checks: list[tuple[str, bool, str]] = []
    for name in bundle.required_files:
        present = Path(resource_path(f"{bundle.directory}/{name}")).is_file()
        checks.append((f"resource:{name}", present, ""))
    try:
        with Path(resource_path(f"{bundle.directory}/{bundle.server}")).open("rb") as server:
            matched = hashlib.file_digest(server, "sha256").hexdigest() == bundle.server_sha256
    except OSError:
        matched = False
    checks.append(("version:scrcpy-server", matched, ""))
    for name, option, marker in (
        (bundle.adb, "version", "Android Debug Bridge version"),
        (bundle.scrcpy, "--version", f"scrcpy {bundle.scrcpy_version}"),
    ):
        if not Path(resource_path(f"{bundle.directory}/{name}")).is_file():
            continue
        executable = bundled_tool_path(bundle.directory, name, verify_tree=True)
        permitted = os.name == "nt" or os.access(executable, os.X_OK)
        checks.append((f"executable:{name}", permitted, ""))
        if not permitted:
            continue
        result = CommandRunner.run([executable, option], timeout=10, native_only=True)
        matched = (
            re.search(rf"^{re.escape(marker)}(?:\s|$)", result.output, re.MULTILINE) is not None
        )
        checks.append((f"runtime:{name}", result.success and matched,
                       "" if result.success else "工具版本命令执行失败"))
    return checks
