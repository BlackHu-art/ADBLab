"""定义独立升级交接包的源码摘要与解析入口，不在运行时隐式构建。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from core.installer_update_protocol import HELPER_NAME
from utils.resource_path import resource_path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
HELPER_RUNTIME_SOURCES = (
    "scripts/installer_update_handoff.py",
    "core/__init__.py",
    "core/installer_update_protocol.py",
    "core/installer_update_process.py",
    "services/__init__.py",
    "services/app_update.py",
    "utils/__init__.py",
    "utils/app_metadata.py",
    "utils/user_data.py",
    "utils/resource_path.py",
)
HELPER_SOURCES = (
    *HELPER_RUNTIME_SOURCES,
    "scripts/build_installer_update_handoff.py",
    "scripts/build_scrcpy_adb_bridge.py",
    "utils/installer_update_helper.py",
)


def helper_source_digest(root: Path = SOURCE_ROOT) -> str:
    """覆盖入口、协议与纯服务依赖及构建约束，忽略 Git 的换行转换。"""

    digest = hashlib.sha256()
    for relative in HELPER_SOURCES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_installer_update_helper() -> Path | None:
    """只返回已提供的 Windows helper；源码运行拒绝旧摘要，安装交接仍须核对安装清单。"""

    if sys.platform != "win32":
        return None
    relative = f"runtime-helpers/{HELPER_NAME}/{HELPER_NAME}.exe"
    if getattr(sys, "frozen", False):
        path = Path(resource_path(relative))
    else:
        path = SOURCE_ROOT / "build" / relative
        try:
            if path.with_name("source.sha256").read_text(encoding="ascii").strip() != (
                helper_source_digest(SOURCE_ROOT)
            ):
                return None
        except (OSError, UnicodeError):
            return None
    return path if path.is_file() else None
