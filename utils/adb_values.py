"""集中校验会进入 ADB 参数列表的动态值。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_PORT_PATTERN = re.compile(r"[0-9]+", re.ASCII)
_PACKAGE_PATTERN = re.compile(
    r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+",
    re.ASCII,
)
_DECIMAL_PATTERN = re.compile(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", re.ASCII)

DUMPSYS_SERVICES = frozenset(
    {
        "",
        "activity",
        "alarm",
        "audio",
        "battery",
        "connectivity",
        "cpuinfo",
        "display",
        "input",
        "meminfo",
        "netstats",
        "notification",
        "package",
        "power",
        "usb",
        "wifi",
        "window",
    }
)


def normalize_tcp_port(value: object) -> str:
    """返回规范化 TCP 端口；非法值抛出 ``ValueError``。"""

    text = str(value).strip()
    if not _PORT_PATTERN.fullmatch(text):
        raise ValueError("端口必须是 ASCII 十进制整数")
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError("端口必须位于 1 到 65535 之间")
    return str(port)


def normalize_android_package(value: object) -> str:
    """校验只读诊断使用的 Android 包名。"""

    package = str(value).strip()
    if not 1 <= len(package) <= 255 or not _PACKAGE_PATTERN.fullmatch(package):
        raise ValueError("包名格式无效")
    return package


def normalize_dumpsys_service(value: object) -> str:
    """把 dumpsys 服务限制在界面公开的只读白名单内。"""

    service = str(value).strip()
    if service not in DUMPSYS_SERVICES:
        raise ValueError("不支持的 dumpsys 服务")
    return service


def normalize_geo_coordinate(
    value: object,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> str:
    """校验普通十进制坐标并去除无意义的尾零。"""

    text = str(value).strip()
    if not _DECIMAL_PATTERN.fullmatch(text):
        raise ValueError("坐标必须是普通十进制数")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("坐标格式无效") from exc
    if not number.is_finite() or not minimum <= number <= maximum:
        raise ValueError("坐标超出允许范围")
    if number == 0:
        return "0"
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def truncate_diagnostic_output(
    value: object,
    *,
    max_lines: int,
    max_chars: int = 12_000,
) -> tuple[str, bool]:
    """限制诊断输出的行数和字符数，并返回是否发生裁剪。"""

    text = str(value or "")
    lines = text.splitlines()
    truncated = len(lines) > max_lines
    visible = "\n".join(lines[: max(0, max_lines)])
    if len(visible) > max_chars:
        visible = visible[:max_chars].rstrip()
        truncated = True
    return visible, truncated
