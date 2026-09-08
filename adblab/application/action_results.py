"""保存用户操作的结果快照，并把提交身份显式带过异步命令边界。

本模块不拥有 Qt 对象或执行资源。提交与结果归并由 Controller 所在线程调用；
ContextVar 只在同步提交或回调作用域内生效，worker 必须携带独立的 ActionJob。
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ActionSpec:
    """定义功能的稳定标识、来源分区和呈现方式。"""

    key: str
    section: str
    title: str
    presentation: str = "status"


@dataclass(frozen=True)
class ActionItem:
    """一台目标的一次命令结果；正文与产物不从日志字符串解析。"""

    job_id: str
    target: str
    label: str
    state: str
    detail: str = ""
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    """跨页面保留的不可变操作快照，设备归属固定在提交时。"""

    request_id: str
    spec: ActionSpec
    targets: tuple[str, ...]
    started_at: float
    state: str = "running"
    items: tuple[ActionItem, ...] = ()
    message: str = ""
    finished_at: float | None = None
    target_names: tuple[str, ...] = ()
    target_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionJob:
    """异步任务携带的请求身份；不引用页面，也不改变原有 operation 信封。"""

    request_id: str
    job_id: str
    target: str
    method: str


@dataclass(frozen=True)
class ActionEnvelope:
    """将原有业务载荷与页面结果身份一起送回 Controller。"""

    payload: Any
    job: ActionJob


@dataclass
class _Request:
    result: ActionResult
    jobs: dict[str, ActionJob] = field(default_factory=dict)
    sealed: bool = False


_scope: ContextVar[tuple[ActionResults, str, ActionJob | None] | None] = ContextVar(
    "action_result_scope",
    default=None,
)


def capture_action_job(method: str, target: object = "") -> ActionJob | None:
    """在异步提交点登记任务；未由用户操作作用域提交的后台查询保持原协议。"""
    scope = _scope.get()
    if scope is None:
        return None
    store, request_id, _job = scope
    return store.add_job(request_id, method, str(target))


def report_action_message(success: bool, message: str) -> bool:
    """兼容 handler 的语义失败；过程成功消息只更新说明，不生成终态。"""
    scope = _scope.get()
    if scope is not None:
        store, request_id, job = scope
        store.message(request_id, success, message, job)
        return True
    return False


class ActionResults:
    """管理本次应用会话的有界结果；同类在途请求幂等，已结束结果不被晚到消息覆盖。"""

    def __init__(self, publish: Callable[[ActionResult], None], *, capacity: int = 80):
        self._publish = publish
        self._capacity = max(1, capacity)
        self._requests: OrderedDict[str, _Request] = OrderedDict()
        self._failures: dict[str, str] = {}
        self._messages: dict[str, str] = {}
        self._closed = False
        self._target_labels: dict[str, str] = {}

    def set_target_labels(self, labels: dict[str, str]) -> None:
        """接收组合根的会话设备名称；只影响后续提交，不改写历史快照。"""
        if not self._closed:
            self._target_labels.update(labels)

    @contextmanager
    def scope(self, request_id: str, job: ActionJob | None = None) -> Iterator[None]:
        """恢复同步回调的归属，使其续发命令仍进入同一次操作。"""
        token = _scope.set((self, request_id, job))
        try:
            yield
        finally:
            _scope.reset(token)

    def run(
        self,
        spec: ActionSpec,
        targets: tuple[str, ...],
        callback: Callable[[], Any],
        *,
        target_names: tuple[str, ...] = (),
        target_labels: tuple[str, ...] = (),
    ) -> Any:
        """先发布运行态，再调用现有提交入口；异常及文件选择取消均有明确终态。"""
        if self._closed:
            return None
        for request in self._requests.values():
            if request.result.state == "running" and request.result.spec.key == spec.key:
                # 同一功能仅允许一批在途目标，避免重复点击与参数编辑争用结果。
                self._publish(request.result)
                return None
        request_id = uuid.uuid4().hex
        unique_targets = tuple(dict.fromkeys(targets))
        names = dict(zip(targets, target_names))
        labels = dict(zip(targets, target_labels))
        result = ActionResult(
            request_id,
            spec,
            unique_targets,
            time.time(),
            target_names=tuple(names.get(target, "") for target in unique_targets),
            target_labels=tuple(labels.get(target) or self._target_labels.get(target, "")
                                for target in unique_targets),
        )
        result = replace(
            result,
            target_names=tuple(self.safe_text(result, name) for name in result.target_names),
        )
        self._requests[request_id] = _Request(result)
        self._publish(result)
        try:
            with self.scope(request_id):
                return callback()
        except Exception as exc:
            self.message(request_id, False, str(exc))
            raise
        finally:
            request = self._requests.get(request_id)
            if request is not None:
                request.sealed = True
                self._settle(request_id)

    def add_job(self, request_id: str, method: str, target: str) -> ActionJob:
        """登记尚未执行的命令，异常结果也能通过此处的目标快照归属设备。"""
        request = self._requests[request_id]
        job = ActionJob(request_id, uuid.uuid4().hex, target, method.removesuffix("_async"))
        request.jobs[job.job_id] = job
        self._update(request_id)
        return job

    def accepts(self, job: ActionJob) -> bool:
        """仅接受当前仍在途且身份一致的任务，重复和淘汰结果均拒绝。"""
        request = self._requests.get(job.request_id)
        return bool(
            not self._closed
            and request
            and request.result.state == "running"
            and request.jobs.get(job.job_id) == job
            and all(item.job_id != job.job_id for item in request.result.items)
        )

    def message(
        self,
        request_id: str,
        success: bool,
        message: str,
        job: ActionJob | None = None,
    ) -> None:
        """更新可读说明；只记语义失败，不从成功文案判断任务完成。"""
        request = self._requests.get(request_id)
        if request is None or request.result.state != "running" or self._closed:
            return
        text = self.safe_text(request.result, message)
        if not success:
            self._failures[job.job_id if job else request_id] = text
        if job is not None:
            self._messages[job.job_id] = text
        request.result = replace(request.result, message=text)
        self._publish(request.result)

    def complete(self, job: ActionJob, payload: Any) -> None:
        """合并 handler 已处理的原始载荷，保留正文；最终状态等待全部续发任务结束。"""
        if not self.accepts(job):
            return
        request = self._requests[job.request_id]
        data = payload if isinstance(payload, dict) else {"output": payload, "success": True}
        failed = self._failures.pop(job.job_id, "")
        if data.get("_validated_unit"):
            # 已有 Operation 协议是单元终态的事实来源，批次摘要不能改写最后一个单元。
            failed = ""
        successful = bool(data.get("success", False))
        state = (
            "cancelled"
            if data.get("cancelled")
            else "succeeded"
            if successful and not failed
            else "failed"
        )
        label = self.target_label(request.result, job.target)
        detail = self._detail(request.result, data, failed)
        message = self._messages.pop(job.job_id, "")
        if not detail and not data.get("_validated_unit"):
            detail = message
        artifact_keys = (
            "bugreport_path",
            "log_path",
            "local_path",
            "screenshot_path",
            "artifact_path",
            "monkey_log",
            "logcat_log",
        )
        artifacts = tuple(
            dict.fromkeys(
                (
                    *(str(data[key]) for key in artifact_keys if successful and data.get(key)),
                    *map(str, data.get("available_artifacts", ())),
                )
            )
        )
        item = ActionItem(job.job_id, job.target, label, state, detail, artifacts)
        request.result = replace(request.result, items=(*request.result.items, item))
        self._settle(job.request_id)

    def progress(self, job: ActionJob, message: str) -> None:
        """主线程接收 worker 的阶段消息；旧任务进度不能复活已结束结果。"""
        if self.accepts(job):
            self.message(job.request_id, True, message, job)

    def _detail(self, result: ActionResult, data: dict, failure: str) -> str:
        fields = (
            "output",
            "error",
            "current_focus",
            "resumed_activity",
            "package_name",
            "packages",
            "duration",
            "seed",
            "cleanup_error",
        )
        pieces = [failure] if failure else []
        for key in fields:
            value = data.get(key)
            if value is None or value == "":
                continue
            text = "\n".join(map(str, value)) if isinstance(value, list) else str(value)
            if key not in ("output", "error"):
                text = f"{key}: {text}"
            if text not in pieces:
                pieces.append(text)
        if not pieces and data.get("message"):
            pieces.append(str(data["message"]))
        return self.safe_text(result, "\n\n".join(pieces))

    @staticmethod
    def target_label(result: ActionResult, target: str) -> str:
        """优先使用提交时的全局显示标签；兼容未提供显示上下文的后台结果。"""
        if target in result.targets:
            index = result.targets.index(target)
            if index < len(result.target_labels) and result.target_labels[index]:
                return result.target_labels[index]
            return f"设备 {index + 1}"
        return "本机" if not target or not result.targets else "设备"

    @staticmethod
    def target_outcomes(result: ActionResult) -> dict[str, int]:
        """终态按设备汇总；同一设备多个命令只计一次，有任一失败即归为失败设备。"""
        counts = {"succeeded": 0, "failed": 0, "cancelled": 0}
        for target in result.targets:
            states = {item.state for item in result.items if item.target == target}
            if "failed" in states or (not states and result.state == "failed"):
                state = "failed"
            elif "cancelled" in states or not states:
                state = "cancelled"
            else:
                state = "succeeded"
            counts[state] += 1
        return counts

    @classmethod
    def safe_text(cls, result: ActionResult, text: str) -> str:
        """在显示边界替换本次真实目标，文件产物通过独立控件提供入口。"""
        for target in sorted(result.targets, key=len, reverse=True):
            if target:
                text = text.replace(target, cls.target_label(result, target))
        return text

    def _settle(self, request_id: str) -> None:
        request = self._requests[request_id]
        if request.sealed and len(request.result.items) == len(request.jobs):
            states = {item.state for item in request.result.items}
            if request_id in self._failures:
                states.add("failed")
            state = (
                "cancelled"
                if not states or states == {"cancelled"}
                else "succeeded"
                if states == {"succeeded"}
                else "partial"
                if "succeeded" in states
                else "failed"
            )
            request.result = replace(request.result, state=state, finished_at=time.time())
            self._failures.pop(request_id, None)
        self._update(request_id)
        ended = [key for key, item in self._requests.items() if item.result.state != "running"]
        for key in ended[: -self._capacity]:
            del self._requests[key]

    def _update(self, request_id: str) -> None:
        if not self._closed:
            self._publish(self._requests[request_id].result)

    def recent(self, section: str | None = None) -> tuple[ActionResult, ...]:
        """读取最新快照；正文由结果控件按需呈现，不使用全局日志缓存。"""
        return tuple(
            request.result
            for request in reversed(self._requests.values())
            if section is None or request.result.spec.section == section
        )

    def record_note(
        self, spec: ActionSpec, targets: tuple[str, ...], message: str, level: str,
        *, target_labels: tuple[str, ...] = (),
    ) -> ActionResult | None:
        """独立页面的过程说明按来源汇集，不从文案推断任务成功或创建执行资源。"""
        if self._closed:
            return None
        request = next(
            (entry for entry in self._requests.values()
             if entry.result.spec.key == spec.key and entry.result.targets == targets), None,
        )
        if request is None:
            result = ActionResult(
                uuid.uuid4().hex, spec, targets, time.time(), state="recorded",
                target_labels=target_labels,
            )
            request = _Request(result, sealed=True)
            self._requests[result.request_id] = request
        result = request.result
        state = {"success": "succeeded", "error": "failed", "warning": "warning"}.get(
            level, "recorded",
        )
        text = self.safe_text(result, message)
        item = ActionItem(uuid.uuid4().hex, targets[0] if targets else "", spec.title,
                          state, text[:64000])
        request.result = replace(result, items=(*result.items[-199:], item),
                                 message=text[:200], finished_at=time.time())
        self._update(result.request_id)
        ended = [key for key, entry in self._requests.items() if entry.result.state != "running"]
        for key in ended[:-self._capacity]:
            del self._requests[key]
        return request.result

    def close(self) -> None:
        """封闭结果准入并释放正文；实际任务仍由已有 supervisor 停止。"""
        self._closed = True
        self._requests.clear()
        self._failures.clear()
        self._messages.clear()
        self._target_labels.clear()


def artifact_name(path: str) -> str:
    """展示产物文件名，避免在摘要中暴露不必要的本机绝对路径。"""
    return Path(path).name or path
