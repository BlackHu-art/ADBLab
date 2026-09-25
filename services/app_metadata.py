"""通过现有临时 helper 批量读取应用名称和版本，不逐包启动 dumpsys。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from services.app_icons import run_app_helper
from utils.adb_values import normalize_android_package

MAX_BATCH_SIZE = 30
_MAX_RECORD_BYTES = 16 * 1024
_MAX_ENCODED_BYTES = 4 * ((_MAX_RECORD_BYTES + 2) // 3)
MAX_OUTPUT_BYTES = MAX_BATCH_SIZE * (_MAX_ENCODED_BYTES + 270)
_FIELDS = {"user", "label", "version_name", "version_code", "installed", "updated",
           "source", "configuration"}
_ERRORS = {"NOT_FOUND", "CONTEXT_UNAVAILABLE", "READ_FAILED", "TOO_LARGE", "USER_CHANGED"}


@dataclass(frozen=True)
class AppMetadata:
    """单包展示数据；缓存身份为摘要，不向 GUI 暴露设备用户和安装路径。"""

    package: str
    label: str
    version: str
    installed: str
    fingerprint: str


@dataclass(frozen=True)
class MetadataBatch:
    """保留有效部分结果；仅明确不支持的环境允许调用方使用兼容查询。"""

    records: dict[str, AppMetadata]
    unsupported: bool = False


def _decode_record(package: str, encoded: str) -> AppMetadata:
    """限制编码、UTF-8 和字段大小；日期由设备按本地时区生成，不由主机换算。"""
    if len(encoded) > _MAX_ENCODED_BYTES:
        raise ValueError("元数据过大")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > _MAX_RECORD_BYTES:
        raise ValueError("元数据过大")
    fields = json.loads(raw.decode("utf-8"))
    if not isinstance(fields, dict) or set(fields) != _FIELDS:
        raise ValueError("元数据字段无效")
    for key in ("user", "updated"):
        if type(fields[key]) is not int or not 0 <= fields[key] <= 2**63 - 1:
            raise ValueError("元数据数值无效")
    for key in _FIELDS - {"user", "updated"}:
        if not isinstance(fields[key], str) or len(fields[key]) > 8192:
            raise ValueError("元数据文本无效")
        fields[key].encode("utf-8")
    code = fields["version_code"]
    installed = fields["installed"]
    if not re.fullmatch(r"[0-9]{1,19}", code) or int(code) > 2**63 - 1:
        raise ValueError("版本号无效")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", installed):
        raise ValueError("安装日期无效")
    date.fromisoformat(installed)
    # 包身份、用户和资源配置变化都会使旧图标失效；安装日期和名称不影响图标内容。
    identity = [package, fields["user"], fields["version_name"], code, fields["updated"],
                fields["source"], fields["configuration"]]
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()
    name = fields["version_name"]
    return AppMetadata(package, fields["label"] or package.rsplit(".", 1)[-1].capitalize(),
                       f"{name} ({code})" if name else "", installed, fingerprint)


def _parse_output(output: str, packages: Sequence[str]) -> MetadataBatch:
    """协议污染整批拒绝；单包缺失不伪造成功，也不触发重复设备查询。"""
    empty = MetadataBatch({})
    if len(output) > MAX_OUTPUT_BYTES or not output.isascii():
        return empty
    expected = set(packages)
    seen: set[str] = set()
    unsupported: set[str] = set()
    records: dict[str, AppMetadata] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            return empty
        kind, package, payload = parts
        if package not in expected or package in seen:
            return empty
        seen.add(package)
        if kind == "META_ERROR" and payload in _ERRORS:
            if payload == "CONTEXT_UNAVAILABLE":
                unsupported.add(package)
        elif kind == "META":
            try:
                records[package] = _decode_record(package, payload)
            except (ValueError, UnicodeError, binascii.Error, RecursionError):
                return empty
        else:
            return empty
    return MetadataBatch(records, unsupported=bool(expected) and unsupported == expected)


def load_app_metadata(
    device_id: str, packages: Sequence[str], cancelled: Callable[[], bool],
) -> MetadataBatch:
    """后台一次读取最多 30 包；超时、取消、坏协议和清理失败均禁止兼容重试。

    仅 helper 缺失或完整 CONTEXT_UNAVAILABLE 响应表明本环境不支持新路径。
    禁用和没有启动入口的应用按包名直接查询，不按 launcher 能力过滤。
    """
    requested = list(dict.fromkeys(packages))
    empty = MetadataBatch({})
    if not requested or len(requested) > MAX_BATCH_SIZE or cancelled():
        return empty
    if not device_id or len(device_id) > 1024 or any(
        char.isspace() or ord(char) < 32 for char in device_id
    ):
        return empty
    try:
        for package in requested:
            if package != "android" and normalize_android_package(package) != package:
                return empty
    except ValueError:
        return empty
    result = run_app_helper(device_id, requested, cancelled, metadata=True,
                            output_limit=MAX_OUTPUT_BYTES)
    if cancelled():
        return empty
    if result.error:
        return MetadataBatch({}, unsupported=result.error == "MISSING")
    return _parse_output(result.output, requested)
