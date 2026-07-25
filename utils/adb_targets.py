"""校验并规范化 ADB 设备连接目标。"""

from __future__ import annotations

import ipaddress


CONNECT_TARGET_EXAMPLE = "192.168.1.10:5555"


def normalize_adb_connect_target(value: str) -> tuple[str, str]:
    """为 ``adb connect`` 返回规范化目标和错误消息二元组。"""
    target = (value or "").strip()
    if not target:
        return "", f"Please enter IP and port, e.g. {CONNECT_TARGET_EXAMPLE}"

    host, port_text, split_error = _split_host_port(target)
    if split_error:
        return "", split_error

    try:
        ipaddress.ip_address(host)
    except ValueError:
        return "", f"Please enter a valid IP address, e.g. {CONNECT_TARGET_EXAMPLE}"

    if not port_text.isdigit():
        return "", "Port must be a number between 1 and 65535"
    port = int(port_text)
    if port < 1 or port > 65535:
        return "", "Port must be between 1 and 65535"

    if ":" in host:
        return f"[{host}]:{port}", ""
    return f"{host}:{port}", ""


def _split_host_port(target: str) -> tuple[str, str, str]:
    if target.startswith("["):
        end = target.find("]")
        if end <= 1 or len(target) <= end + 2 or target[end + 1] != ":":
            return "", "", "Please enter IP and port, e.g. [::1]:5555"
        return target[1:end].strip(), target[end + 2:].strip(), ""

    if target.count(":") != 1:
        return "", "", f"Please enter IP and port, e.g. {CONNECT_TARGET_EXAMPLE}"
    host, port_text = target.split(":", 1)
    host = host.strip()
    port_text = port_text.strip()
    if not host or not port_text:
        return "", "", f"Please enter complete IP and port, e.g. {CONNECT_TARGET_EXAMPLE}"
    return host, port_text, ""
