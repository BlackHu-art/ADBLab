"""生成短诊断产物名称，不把原始设备连接标识写入文件名。"""

from __future__ import annotations

import base64
import hashlib
import uuid
from typing import Literal


def diagnostic_prefix(
    kind: Literal["log", "logcat", "bugreport"], device_id: str, timestamp: str,
) -> str:
    """用产物类型、调用方生成的日期时间和设备短摘要构造目录或文件前缀。

    短摘要只用于区分设备，不提供唯一性；调用方须追加任务身份或使用独占目录。
    """
    device_tag = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:8]
    return f"{kind}_{timestamp}_{device_tag}_"


def diagnostic_log_filename(
    kind: Literal["log", "logcat"], device_id: str, timestamp: str,
) -> str:
    """保留完整 UUID 的任务身份且不创建占位文件，避免采集失败留下空产物。"""
    # 小写 Base32 保留 UUID 全部位，同时适配大小写不敏感文件系统并缩短名称。
    nonce = base64.b32encode(uuid.uuid4().bytes).decode("ascii").rstrip("=").lower()
    return f"{diagnostic_prefix(kind, device_id, timestamp)}{nonce}.txt"
