"""解析独立的 scrcpy ADB 入口，源码只使用与当前协议一致的本地构建。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from utils.runtime_tools import bundled_tool_path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_NAME = "adblab-adb-bridge"
BRIDGE_SOURCES = (
    "scripts/scrcpy_adb_bridge.py",
    "core/scrcpy_adb_protocol.py",
    "core/scrcpy_session.py",
    "core/adb_transport.py",
)


def bridge_source_digest(root: Path = SOURCE_ROOT) -> str:
    """构建摘要忽略 Git 换行差异，避免协议源码更新后运行旧入口。"""
    digest = hashlib.sha256()
    for relative in BRIDGE_SOURCES:
        digest.update(relative.encode("utf-8"))
        digest.update((root / relative).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def resolve_scrcpy_bridge() -> str | None:
    """返回已随包提供或已在源码中构建的入口；不在 GUI 中隐式打包。"""
    filename = BRIDGE_NAME + (".exe" if sys.platform == "win32" else "")
    if getattr(sys, "frozen", False):
        executable = Path(bundled_tool_path(
            "runtime-helpers", BRIDGE_NAME, filename, verify_tree=True,
        ))
    else:
        folder = SOURCE_ROOT / "build" / "runtime-helpers" / BRIDGE_NAME
        executable = folder / filename
        try:
            stamp = (folder / "source.sha256").read_text(encoding="ascii").strip()
            if stamp != bridge_source_digest(SOURCE_ROOT):
                return None
        except OSError:
            return None
    return str(executable) if executable.is_file() else None
