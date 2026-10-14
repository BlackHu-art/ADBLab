"""独立检查随包工具，不允许系统 PATH 掩盖漏打包，也不连接设备。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from core.adb_runtime import native_capture
from core.exec import CommandRunner
from utils.resource_path import resource_path
from utils.runtime_tools import bundled_tool_path
from utils.tool_manifest import Aapt2Bundle, ToolBundle, get_aapt2_bundle, get_tool_bundle


def check_bundled_tools() -> list[tuple[str, bool, str]]:
    """检查资源、缓存和版本命令；未承诺内置工具的平台沿用环境工具策略。"""
    checks: list[tuple[str, bool, str]] = []
    bundle = get_tool_bundle()
    if bundle is not None:
        checks.extend(_check_scrcpy_bundle(bundle))
    aapt2 = get_aapt2_bundle()
    if aapt2 is not None:
        checks.extend(_check_aapt2_bundle(aapt2))
    return checks


def _check_scrcpy_bundle(bundle: ToolBundle) -> list[tuple[str, bool, str]]:
    """检查现有 ADB/scrcpy 配套包，系统工具不得掩盖源资源缺失。"""
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


def _check_aapt2_bundle(bundle: Aapt2Bundle) -> list[tuple[str, bool, str]]:
    """校验独立 AAPT2 及其 NOTICE；版本输出可能位于 stderr，不经成功结果归一化。"""
    checks = []
    for name in bundle.required_files:
        present = Path(resource_path(f"{bundle.directory}/{name}")).is_file()
        label = "aapt2-NOTICE" if name == "NOTICE" else name
        checks.append((f"resource:{label}", present, ""))
    if not Path(resource_path(f"{bundle.directory}/{bundle.executable}")).is_file():
        return checks
    executable = bundled_tool_path(bundle.directory, bundle.executable, verify_tree=True)
    permitted = os.name == "nt" or os.access(executable, os.X_OK)
    checks.append((f"executable:{bundle.executable}", permitted, ""))
    if not permitted:
        return checks
    result = native_capture([executable, "version"], 10, lambda: False)
    output = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    marker = rf"^Android Asset Packaging Tool \(aapt\) {re.escape(bundle.runtime_version)}\s*$"
    matched = result.kind == "completed" and result.returncode == 0 and bool(
        re.search(marker, output, re.MULTILINE),
    )
    checks.append((f"runtime:{bundle.executable}", matched,
                   "" if matched else "AAPT2 版本命令执行失败或版本不匹配"))
    return checks
