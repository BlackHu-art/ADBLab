"""提供 ADB 工作流共用的安全归档处理能力。"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


def safe_extract_zip(zip_ref: ZipFile, target_dir: str | Path) -> None:
    """仅在所有成员均位于 ``target_dir`` 内时解压 ZIP。"""
    target_root = Path(target_dir).resolve()
    for member in zip_ref.infolist():
        destination = (target_root / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise ValueError(f"Unsafe ZIP member path: {member.filename}")
    zip_ref.extractall(target_root)
