"""定义持续会话的只读展示边界，并把停止请求路由回原资源所有者。"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Protocol

from shiboken6 import isValid


@dataclass(frozen=True, slots=True)
class SessionTaskSnapshot:
    """资源义务独立于显示状态；busy 仅表示阶段推进，不改变资源及停止归属。"""

    key: str
    revision: str
    kind: str
    state: str
    resource_owned: bool
    stop_enabled: bool
    target_labels: tuple[str, ...]
    detail: str = ""
    run_id: str | None = None
    busy: bool = False


class SessionTaskOwner(Protocol):
    """在 GUI 线程公开快照与原版本停止准入，不向展示层暴露执行资源。"""

    def task_snapshot(self) -> SessionTaskSnapshot | None:
        """返回当前资源义务或最近终态；从未启动的 owner 返回 None。"""
        ...

    def request_task_stop(self, expected_revision: str) -> bool:
        """仅停止仍匹配的原会话；返回受理，不表示资源已经退出。"""
        ...


class SessionTaskRegistry:
    """只保留弱路由；停止前重新枚举，防止旧实例或旧版本按钮操作新会话。"""

    def __init__(
        self,
        owners: Callable[[], Iterable[SessionTaskOwner]],
        labels: Callable[[SessionTaskOwner], tuple[str, ...] | None] | None = None,
    ) -> None:
        self._owners = owners
        self._labels = labels
        self._routes: dict[str, weakref.ReferenceType[SessionTaskOwner]] = {}
        self._closed = False

    def collect(self) -> tuple[SessionTaskSnapshot, ...]:
        """枚举全部现存 owner；显示标签覆盖不改变资源身份或停止归属。"""
        if self._closed:
            return ()
        routes = {}
        snapshots = []
        for owner in self._owners():
            if not isValid(owner):
                continue
            refresh = getattr(owner, "refresh_task_snapshot", None)
            if callable(refresh):
                refresh()
            snapshot = owner.task_snapshot()
            if snapshot is None:
                continue
            if snapshot.key in routes:
                raise ValueError("duplicate session task owner key")
            routes[snapshot.key] = weakref.ref(owner)
            if self._labels is not None:
                labels = self._labels(owner)
                if labels is not None:
                    snapshot = replace(snapshot, target_labels=labels)
            snapshots.append(snapshot)
        self._routes = routes
        return tuple(snapshots)

    def request_stop(self, key: str, revision: str) -> bool:
        """核对当前枚举仍包含同一个 owner，再由它复核版本和停止准入。"""
        if self._closed:
            return False
        reference = self._routes.get(key)
        original = reference() if reference is not None else None
        if original is None or not isValid(original):
            return False
        for owner in self._owners():
            if owner is not original:
                continue
            snapshot = owner.task_snapshot()
            if (snapshot is None or snapshot.key != key or snapshot.revision != revision
                    or not snapshot.resource_owned or not snapshot.stop_enabled):
                return False
            return owner.request_task_stop(revision)
        return False

    def shutdown(self) -> None:
        """封闭后续查询及停止请求，不接管或停止业务资源。"""
        self._closed = True
        self._routes.clear()
