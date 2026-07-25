"""技能网关核心实现，提供统一的技能注册与执行能力。"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SkillError(RuntimeError):
    """技能执行异常。"""

    code: str
    details: str | None = None

    def __init__(self, code: str, details: str | None = None):
        super().__init__(details or "")
        object.__setattr__(self, "code", str(code).strip().upper())
        object.__setattr__(self, "details", details)


@dataclass(frozen=True)
class _SkillOutput:
    ok: bool
    result: Mapping[str, Any]


class AgentSkillGateway:
    """管理技能注册与同步/异步执行。"""

    def __init__(self, max_workers: int = 4) -> None:
        self._skills: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def register(self, skill_name: str, handler: Callable[[Any], Any]) -> None:
        """注册技能函数。"""
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError("skill_name must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            self._skills[skill_name.strip()] = handler

    def run_skill(
        self,
        skill_name: str,
        payload: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """同步执行技能并返回统一结果结构。"""
        normalized_name = self._ensure_skill_name(skill_name)
        normalized = self._safe_payload(payload)
        normalized_context = dict(context or {})
        request_id = str(normalized_context.get("request_id", uuid.uuid4()))

        try:
            handler = self._resolve(normalized_name)
            timeout_ms = self._get_timeout_ms(normalized_context)
            future = self._executor.submit(
                self._execute,
                normalized_name,
                handler,
                dict(normalized),
                normalized_context,
            )
            output = self._wait_future(future, timeout_ms)
            return {
                "name": normalized_name,
                "request_id": request_id,
                "ok": output.ok,
                "result": dict(output.result),
            }
        except Exception as exc:
            return self._format_error(normalized_name, request_id, exc)

    def run_skill_async(
        self,
        skill_name: str,
        payload: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None = None,
    ) -> Future[dict[str, Any]]:
        """异步执行技能，返回 Future。"""
        request_id = str((context or {}).get("request_id", uuid.uuid4()))
        context = dict(context or {})
        context["request_id"] = request_id
        return self._executor.submit(self.run_skill, skill_name, self._safe_payload(payload), context)

    def cancel(self, future: Future[Any]) -> bool:
        """尝试取消一个异步任务。"""
        return future.cancel()

    def shutdown(self, *, wait: bool = False, cancel_futures: bool = True) -> None:
        """关闭网关线程池。"""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def _resolve(self, skill_name: str) -> Callable[..., Any]:
        with self._lock:
            handler = self._skills.get(skill_name)
        if handler is None:
            raise KeyError(skill_name)
        return handler

    def _safe_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    def _get_timeout_ms(self, context: Mapping[str, Any]) -> float | None:
        value = context.get("timeout_ms")
        if value is None:
            return None
        timeout = float(value)
        if timeout < 0:
            raise ValueError("timeout_ms must be non-negative")
        return timeout / 1000.0

    def _wait_future(
        self,
        future: Future[Any],
        timeout_seconds: float | None,
    ) -> _SkillOutput:
        try:
            value = future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise SkillError("TIMEOUT") from exc
        if isinstance(value, _SkillOutput):
            return value
        if not isinstance(value, Mapping):
            raise SkillError("INVALID_OUTPUT")
        return _SkillOutput(ok=True, result=dict(value))

    def _execute(
        self,
        skill_name: str,
        handler: Callable[..., Any],
        payload: dict[str, Any],
        context: Mapping[str, Any],
    ) -> _SkillOutput:
        try:
            result = self._call_handler(handler, payload, context)
        except SkillError:
            raise
        except Exception as exc:
            raise SkillError(exc.__class__.__name__.upper(), str(exc)) from exc
        if not isinstance(result, Mapping):
            raise SkillError("INVALID_OUTPUT")
        return _SkillOutput(ok=True, result=dict(result))

    def _call_handler(
        self,
        handler: Callable[..., Any],
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Any:
        try:
            return handler(payload, context)
        except TypeError:
            return handler(payload)

    def _format_error(self, skill_name: str, request_id: str, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, KeyError):
            code = "SKILL_NOT_FOUND"
            message = str(skill_name)
        elif isinstance(exc, SkillError):
            code = exc.code
            message = exc.details or ""
        else:
            code = exc.__class__.__name__.upper()
            message = str(exc)
        return {
            "name": skill_name,
            "request_id": request_id,
            "ok": False,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _ensure_skill_name(skill_name: str) -> str:
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError("skill_name must be a non-empty string")
        return skill_name.strip()

