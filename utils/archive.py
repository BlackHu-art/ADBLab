"""提供 ADB 工作流共用的安全归档处理能力。"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200


def validate_zip_archive(zip_ref: ZipFile, target_dir: str | Path) -> None:
    """按目标路径校验 ZIP 准入，不写入文件；发布与解压共用同一安全边界。"""
    target_root = Path(target_dir).resolve()
    members = zip_ref.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError("ZIP archive has too many members")
    total_size = 0
    for member in members:
        destination = (target_root / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise ValueError(f"Unsafe ZIP member path: {member.filename}")
        total_size += max(0, member.file_size)
        if total_size > MAX_ARCHIVE_BYTES:
            raise ValueError("ZIP archive uncompressed size is too large")
        if (
            member.file_size >= 1024 * 1024
            and member.compress_size > 0
            and member.file_size // member.compress_size > MAX_ARCHIVE_RATIO
        ):
            raise ValueError("ZIP archive compression ratio is suspicious")


def safe_extract_zip(zip_ref: ZipFile, target_dir: str | Path) -> None:
    """校验路径与规模后解压 ZIP；拒绝解压炸弹和异常大的归档。"""
    target_root = Path(target_dir).resolve()
    validate_zip_archive(zip_ref, target_root)
    zip_ref.extractall(target_root)
