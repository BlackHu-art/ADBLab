"""提供内嵌功能页的稳定会话标识和生命周期注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class FeatureSessionKey:
    """唯一标识一个功能、设备与代次固定的页面会话。"""

    feature: str
    device_id: str = ""
    generation: int = 0

    def __post_init__(self) -> None:
        feature = self.feature.strip()
        device_id = self.device_id.strip()
        if not feature:
            raise ValueError("feature must not be empty")
        if self.generation < 0:
            raise ValueError("generation must not be negative")
        object.__setattr__(self, "feature", feature)
        object.__setattr__(self, "device_id", device_id)


class FeatureSessionRegistry(QObject):
    """持有内嵌页面，统一转发生命周期并防止设备会话串线。

    页面可选择实现 ``activate(payload)``、``deactivate(reason)``、
    ``request_dispose(reason)`` 与 ``register_shutdown_tasks(...)``。若
    ``request_dispose`` 返回 ``True``，会话可立即移除；返回 ``False`` 时，
    页面必须在资源真正停止后发出 ``dispose_ready``。
    """

    session_added = Signal(object, object)
    session_removed = Signal(object, object)
    current_changed = Signal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sessions: dict[FeatureSessionKey, QWidget] = {}
        self._current_key: FeatureSessionKey | None = None
        self._dispose_callbacks: dict[FeatureSessionKey, Callable[..., None]] = {}
        self._disposing: set[FeatureSessionKey] = set()

    @property
    def current_key(self) -> FeatureSessionKey | None:
        return self._current_key

    def keys(self) -> tuple[FeatureSessionKey, ...]:
        return tuple(self._sessions)

    def pages(self) -> tuple[QWidget, ...]:
        return tuple(self._sessions.values())

    def get(self, key: FeatureSessionKey) -> QWidget | None:
        return self._sessions.get(key)

    def is_disposing(self, key: FeatureSessionKey) -> bool:
        return key in self._disposing

    def get_or_create(
        self,
        key: FeatureSessionKey,
        factory: Callable[[FeatureSessionKey], QWidget],
    ) -> tuple[QWidget, bool]:
        page = self._sessions.get(key)
        if page is not None:
            if key in self._disposing:
                raise RuntimeError("feature session is disposing")
            return page, False
        page = factory(key)
        if not isinstance(page, QWidget):
            raise TypeError("feature session factory must return QWidget")
        page.setProperty("feature", key.feature)
        page.setProperty("device_id", key.device_id)
        page.setProperty("session_generation", key.generation)
        self._sessions[key] = page
        self._connect_dispose_ready(key, page)
        self.session_added.emit(key, page)
        return page, True

    def activate(
        self,
        key: FeatureSessionKey,
        payload=None,
        *,
        previous_is_inactive: bool = False,
    ) -> QWidget:
        """选中并激活会话。

        ``previous_is_inactive`` 用于主导航返回时的原子路由：旧会话
        在页面隐藏时已暂停，因此不再重复通知它；目标会话即使
        与原 key 相同也必须恢复一次。
        """

        page = self._sessions[key]
        previous_key = self._current_key
        if (
            not previous_is_inactive
            and previous_key is not None
            and previous_key != key
        ):
            previous = self._sessions.get(previous_key)
            callback = getattr(previous, "deactivate", None)
            if callable(callback):
                callback("navigation")
        self._current_key = key
        callback = getattr(page, "activate", None)
        if callable(callback) and (
            previous_is_inactive or previous_key != key or payload is not None
        ):
            callback(payload)
        if previous_key != key:
            self.current_changed.emit(previous_key, key)
        return page

    def deactivate_current(
        self,
        reason: str = "navigation",
        *,
        current_is_inactive: bool = False,
    ) -> None:
        key = self._current_key
        self._current_key = None
        if key is None:
            return
        page = self._sessions.get(key)
        callback = getattr(page, "deactivate", None)
        if callable(callback) and not current_is_inactive:
            callback(reason)
        self.current_changed.emit(key, None)

    def request_dispose(self, key: FeatureSessionKey, reason: str = "user") -> bool:
        page = self._sessions.get(key)
        if page is None:
            return True
        if key in self._disposing:
            return False
        callback = getattr(page, "request_dispose", None)
        ready = True if not callable(callback) else bool(callback(reason))
        if ready:
            removed = self.remove(key)
            if removed is not None:
                removed.deleteLater()
        elif key in self._sessions:
            self._disposing.add(key)
        else:
            return True
        return ready

    def request_dispose_all(self, reason: str = "application_shutdown") -> None:
        for key in tuple(self._sessions):
            self.request_dispose(key, reason)

    def register_shutdown_tasks(
        self,
        supervisor,
        *,
        owner_id: str,
        task_prefix: str,
    ) -> tuple[str, ...]:
        task_ids: list[str] = []
        failures: list[tuple[FeatureSessionKey, str]] = []
        for index, (key, page) in enumerate(tuple(self._sessions.items())):
            callback = getattr(page, "register_shutdown_tasks", None)
            if not callable(callback):
                continue
            safe_feature = "".join(
                character if character.isalnum() or character in "-_" else "-"
                for character in key.feature
            )
            try:
                result = cast(
                    Any,
                    callback(
                        supervisor,
                        owner_id=owner_id,
                        task_prefix=f"{task_prefix}-{safe_feature}-{index}",
                    ),
                )
            except Exception as exc:
                failures.append((key, type(exc).__name__))
                continue
            if result:
                task_ids.extend(str(task_id) for task_id in result)
        if failures:
            first_key, first_error = failures[0]
            raise RuntimeError(
                "feature shutdown registration failed "
                f"for {len(failures)} session(s); first={first_key.feature}:{first_error}"
            )
        return tuple(task_ids)

    def remove(self, key: FeatureSessionKey) -> QWidget | None:
        page = self._sessions.pop(key, None)
        if page is None:
            return None
        self._disposing.discard(key)
        if self._current_key == key:
            self._current_key = None
            self.current_changed.emit(key, None)
        callback = self._dispose_callbacks.pop(key, None)
        signal = getattr(page, "dispose_ready", None)
        if callback is not None and signal is not None:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self.session_removed.emit(key, page)
        return page

    def _connect_dispose_ready(self, key: FeatureSessionKey, page: QWidget) -> None:
        signal = getattr(page, "dispose_ready", None)
        if signal is None or not hasattr(signal, "connect"):
            return

        def on_dispose_ready(*_args) -> None:
            removed = self.remove(key)
            if removed is not None:
                removed.deleteLater()

        self._dispose_callbacks[key] = on_dispose_ready
        signal.connect(on_dispose_ready)
