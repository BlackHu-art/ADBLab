
"""探测本机 ADB 客户端候选：只读取版本，不触碰 5037 服务。"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from core.exec import CommandRunner
from utils.adb_resolver import AdbCandidate, list_adb_candidates

VERSION_TIMEOUT_SECONDS = 3.0
_CACHE_LIMIT = 16

_BRIDGE_VERSION = re.compile(r"Android Debug Bridge version ([0-9][0-9.]*)")
_BUILD_VERSION = re.compile(r"^Version ([0-9][0-9A-Za-z.\-]*)", re.MULTILINE)

# 失败分类：界面据此显示可读原因，不把异常文本直接暴露给用户。
ERROR_MISSING = "missing"
ERROR_UNAVAILABLE = "unavailable"
ERROR_TIMEOUT = "timeout"
ERROR_NOT_ADB = "not_adb"
ERROR_CANCELLED = "cancelled"


@dataclass(frozen=True)
class ClientProbe:
    """单个候选的探测结果；version 形如 1.0.41 (37.0.0)。"""

    source: str
    path: str
    exists: bool
    executable: bool = False
    version: str = ""
    error: str = ""


_probe_cache: dict[tuple[str, int, int], ClientProbe] = {}


def parse_client_version(output: str) -> str:
    """从 adb version 输出提取客户端与构建版本；无法识别时返回空串。"""

    bridge = _BRIDGE_VERSION.search(output or "")
    if bridge is None:
        return ""
    build = _BUILD_VERSION.search(output or "")
    if build is None or not build.group(1):
        return bridge.group(1)
    return f"{bridge.group(1)} ({build.group(1).split('-', 1)[0]})"


def clear_client_probe_cache() -> None:
    """清空探测缓存；客户端文件或选择变化时调用。"""

    _probe_cache.clear()


def _cache_key(path: str) -> tuple[str, int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.normcase(os.path.abspath(path)), stat.st_mtime_ns, stat.st_size)


def _store(key: tuple[str, int, int] | None, probe: ClientProbe) -> ClientProbe:
    if key is not None:
        if len(_probe_cache) >= _CACHE_LIMIT:
            _probe_cache.pop(next(iter(_probe_cache)))
        _probe_cache[key] = probe
    return probe


def _probe_one(
    candidate: AdbCandidate,
    *,
    cancelled: Callable[[], bool] | None,
    timeout: float,
    use_cache: bool,
) -> ClientProbe:
    base = ClientProbe(candidate.source, candidate.path, candidate.exists, error=ERROR_MISSING)
    if not candidate.exists:
        return base
    if cancelled is not None and cancelled():
        return replace(base, error=ERROR_CANCELLED)

    key = _cache_key(candidate.path)
    if use_cache and key is not None:
        cached = _probe_cache.get(key)
        if cached is not None:
            return replace(cached, source=candidate.source, exists=True)

    result = CommandRunner.run(
        [candidate.path, "version"],
        timeout=timeout,
        native_only=True,
        cancelled=cancelled,
    )
    if not result.success:
        reason = (result.error or "").strip().lower()
        if "cancel" in reason:
            error = ERROR_CANCELLED
        elif reason.startswith("timeout") or "timed out" in reason:
            error = ERROR_TIMEOUT
        else:
            error = ERROR_UNAVAILABLE
        # 失败结果不入缓存：冷启动超时只是一次性现象，缓存它会让该候选
        # 在整个会话都显示不可用；下次识别应当重新尝试。
        return replace(base, error=error)

    version = parse_client_version(result.output)
    if not version:
        return _store(key, replace(base, error=ERROR_NOT_ADB))
    return _store(key, replace(base, executable=True, version=version, error=""))


def detect_clients(
    candidates: Iterable[AdbCandidate] | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = VERSION_TIMEOUT_SECONDS,
    use_cache: bool = True,
) -> list[ClientProbe]:
    """并发探测候选客户端（上限 2 个），只运行 adb version，不连 5037 服务。"""

    items = list(candidates if candidates is not None else list_adb_candidates())
    if not items:
        return []
    if cancelled is not None and cancelled():
        return [
            ClientProbe(item.source, item.path, item.exists, error=ERROR_CANCELLED)
            for item in items
        ]

    def probe(candidate: AdbCandidate) -> ClientProbe:
        return _probe_one(candidate, cancelled=cancelled, timeout=timeout, use_cache=use_cache)

    # 串行探测：多个 adb.exe 同时冷启动会互相拖慢（首次执行要等加载器与安全扫描），
    # 逐个执行时只有第一个候选付冷启动成本，其余基本是热态。
    return [probe(candidate) for candidate in items]
