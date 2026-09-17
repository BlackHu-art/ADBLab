"""验证功能页的可选能力，避免误把无效声明当成未实现。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def optional_callback(page: object, name: str) -> Callable[..., Any] | None:
    """缺失或 None 表示未实现；显式声明的其他值必须可调用。"""
    callback = getattr(page, name, None)
    if callback is None:
        return None
    if not callable(callback):
        raise TypeError(f"feature capability {name} must be callable or None")
    return callback
