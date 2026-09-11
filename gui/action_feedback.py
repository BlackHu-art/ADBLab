"""组合根的操作反馈适配：连接来源分区、结果索引和异步文件动作。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QScrollArea

from adblab.application.action_results import ActionResult, ActionResults, ActionSpec
from controllers.action_catalog import ACTION_SIGNALS
from core.diagnostics import redact_diagnostic
from gui.i18n import tr
from gui.notifications import ToastLevel, show_toast
from gui.pages.device_hub import _device_name


class ActionFeedbackPresenter(QObject):
    """由主窗口拥有的唯一结果分发器；不持有设备任务，不解析日志作为结果。"""

    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame
        self._ended: set[str] = set()
        self._started: set[str] = set()
        self._diagnostics = frame.left_panel._apps_tab.diagnostic_results
        self._reports = frame.left_panel._apps_tab.report_artifacts
        self._reports.artifact_requested.connect(frame.run_library.open_artifact)
        for view in (self._diagnostics, frame._task_page.action_results):
            view.artifact_requested.connect(frame.run_library.open_artifact)
            view.export_requested.connect(self.export_result)
            view.reveal_requested.connect(self._reveal)
        frame.adb_controller.signals.action_result_changed.connect(self.present)
        frame.run_library.exported.connect(self._exported)
        frame.log_service.diagnostics_changed.connect(self._diagnostics_changed)
        frame._settings_page.diagnostics_card.clicked.connect(self._export_diagnostics)
        self._diagnostics_changed(notify=False)

    def bind(self, signals, signal, handler: Callable) -> Callable:
        """每条 Controller 接线必须有声明式归属；遗漏入口在启动时显式失败。"""
        for name, spec in ACTION_SIGNALS.items():
            if getattr(signals, name) == signal:
                return lambda *args, spec=spec, handler=handler: self.dispatch(spec, handler, args)
        raise ValueError("Controller action is missing its result destination")

    def dispatch(self, spec: ActionSpec, handler: Callable, args: tuple) -> None:
        """复制提交目标并通过现有 Controller 入口执行，保留全部准入和确认逻辑。"""
        if self.frame._closing:
            return
        if spec.key == "restart_adb" and self.frame._settings_page.isVisibleTo(self.frame):
            spec = replace(spec, section="settings.maintenance")
        targets = (
            tuple(dict.fromkeys(target for target in args[0] if target))
            if args and isinstance(args[0], list)
            else ((str(args[0]),) if args and spec.key == "connect_device" else ())
        )
        if args and isinstance(args[0], list):
            args = (list(targets), *args[1:])
        journal = self.frame.log_service.diagnostics
        journal.private_values = tuple(dict.fromkeys((*journal.private_values, *targets)))
        store = self.frame.adb_controller.action_results
        pending = next(
            (
                result
                for result in store.recent()
                if result.state == "running" and result.spec.key == spec.key
            ),
            None,
        )
        if pending is not None:
            show_toast(
                self.frame, tr(pending.spec.title), tr("该操作仍在执行，可在任务中心查看进度。"),
                level="info", action_text=tr("查看任务"),
                on_action=lambda: self.open_task(pending.request_id), key=pending.request_id,
            )
            return
        try:
            store.run(
                spec,
                targets,
                lambda: handler(*args),
                target_names=tuple(
                    _device_name(target, self.frame._device_metadata.get(target, {}))
                    for target in targets
                ),
                target_labels=tuple(self.frame._global_device_bar.device_label(t) for t in targets),
            )
        except Exception as exc:
            self.frame.log_service.log("ERROR", f"Action submission failed: {type(exc).__name__}")

    def _exported(self, path: str) -> None:
        """文件队列确认原子写入成功后才显示完成提示。"""
        if not self.frame._closing:
            show_toast(
                self.frame,
                tr("结果已导出"),
                tr("文件已保存，可打开查看。"),
                level="success",
                action_text=tr("打开文件夹"),
                on_action=lambda: self.frame.run_library.open_artifact(path, True),
            )

    def _diagnostics_changed(self, *, notify: bool = True) -> None:
        """所有诊断后台保存；仅警告及以上更新异常摘要并触发异常提示。"""
        journal = self.frame.log_service.diagnostics
        if not journal.entries:
            return
        self.frame._settings_page.diagnostics_card.button.setEnabled(True)
        self.frame.run_library.save_diagnostics(journal.text())
        warning_levels = {"WARNING", "ERROR", "CRITICAL"}
        warnings = [entry for entry in journal.entries if entry[1] in warning_levels]
        content = tr("本次运行尚无应用异常记录")
        if warnings:
            content = tr("本次保留 {count} 条异常摘要；最近：{message}").format(
                count=len(warnings), message=warnings[-1][2][:100],
            )
        self.frame._settings_page.diagnostics_card.setContent(content)
        # 运行时 INFO 也会刷新诊断文件，不能据此重复提示之前保留的异常。
        if notify and journal.entries[-1][1] in warning_levels and not self.frame._closing:
            show_toast(
                self.frame,
                tr("应用提示"),
                tr("应用记录了异常，请在设置中查看摘要或导出诊断。"),
                level="warning",
                action_text=tr("查看设置"),
                on_action=lambda: self.frame._on_nav_requested("settings"),
            )

    def _export_diagnostics(self) -> None:
        self.export_result("application-diagnostics", self.frame.log_service.diagnostics.text())

    def present(self, result: ActionResult) -> None:
        """完整过程只进任务中心；普通页面只收到分级终态提示，两个专用区消费业务产物。"""
        if self.frame._closing:
            return
        self.frame._task_page.present_action_result(result)
        if result.spec.presentation == "notes":
            return
        if result.spec.section == "apps.diagnostics":
            self._diagnostics.present(result)
        elif result.spec.section == "apps.reports":
            self._reports.present(result)
        if result.state == "running" and result.request_id not in self._started:
            self._started.add(result.request_id)
            QTimer.singleShot(500, self, lambda key=result.request_id: self._show_running(key))
        if result.state != "running" and result.request_id not in self._ended:
            self._ended.add(result.request_id)
            if len(self._ended) > 160:
                self._ended = {
                    item.request_id for item in self.frame.adb_controller.action_results.recent()
                }
                self._started.intersection_update(self._ended)
            if result.state == "cancelled" and not result.items:
                return
            levels: dict[str, ToastLevel] = {
                "succeeded": "success", "partial": "warning", "failed": "error",
                "cancelled": "info", "recorded": "info", "warning": "warning",
            }
            labels = {
                "succeeded": tr("操作已完成"), "partial": tr("部分操作失败，请查看任务详情"),
                "failed": tr("操作失败，请查看任务详情"), "cancelled": tr("操作已取消"),
                "recorded": tr("已记录操作说明"), "warning": tr("操作需要注意，请查看详情"),
            }
            message = labels[result.state]
            if result.targets:
                counts = ActionResults.target_outcomes(result)
                if result.state == "partial" and not counts["failed"] and not counts["cancelled"]:
                    # 批次收尾的语义失败没有逐台归属，不能把命令成功数冒充设备最终成功数。
                    message += tr(" · {count} 台目标设备").format(count=len(result.targets))
                else:
                    message += " · " + tr(
                        "成功 {succeeded} 台 · 失败 {failed} 台 · 未完成 {cancelled} 台"
                    ).format(**counts)
            if result.state == "failed":
                reason = next((item.detail for item in result.items if item.detail), result.message)
                if reason:
                    message += " · " + redact_diagnostic(reason.splitlines()[0])[:160]
            show_toast(
                self.frame, tr(result.spec.title), message, level=levels[result.state],
                action_text=tr("查看任务"), on_action=lambda: self.open_task(result.request_id),
                key=result.request_id,
            )

    def _show_running(self, request_id: str) -> None:
        if self.frame._closing:
            return
        result = next((item for item in self.frame.adb_controller.action_results.recent()
                       if item.request_id == request_id), None)
        if result is not None and result.state == "running":
            show_toast(
                self.frame, tr(result.spec.title), tr("正在执行，可在任务中心查看进度。"),
                level="info", action_text=tr("查看任务"),
                on_action=lambda: self.open_task(request_id), key=request_id,
            )

    def record_notice(
        self, source: str, title: str, message: str, level: ToastLevel, target: str = "", *,
        notify: bool = False,
    ) -> None:
        """接收独立页面的显式通知级别；过程记录不触发完成提示。"""
        if self.frame._closing:
            return
        result = self.frame.adb_controller.action_results.record_note(
            ActionSpec("notes:" + source, source, title, "notes"),
            (target,) if target else (), message, level,
            target_labels=(self.frame._global_device_bar.device_label(target),) if target else (),
        )
        if notify and result is not None:
            show_toast(
                self.frame, tr(title), redact_diagnostic(result.items[-1].detail), level=level,
                action_text=tr("查看任务"), on_action=lambda: self.open_task(result.request_id),
                key=result.request_id + ":" + level,
            )

    def open_task(self, request_id: str) -> None:
        """通知只定位提交时的任务，不切换设备、不重复执行命令。"""
        if self.frame._closing:
            return
        page = self.frame._task_page
        self.frame._on_nav_requested("tasks")
        page.history_views.set_current("operations")
        result = next((item for item in self.frame.adb_controller.action_results.recent()
                       if item.request_id == request_id), None)
        if result is not None:
            page.present_action_result(result)
        page.action_results.select_request(request_id)
        self._reveal(page.action_results)

    def open_section(self, section: str, request_id: str = "") -> None:
        """以稳定功能位置返回原分区，使用当次结果而不是当前设备重新执行。"""
        if self.frame._closing:
            return
        if request_id:
            self.open_task(request_id)
            return
        if section == "devices":
            self.frame._on_nav_requested("devices")
        elif section == "settings.maintenance":
            self.frame._on_nav_requested("settings")
        elif section == "apps.media":
            self.frame._open_workspace_feature("apps", "media")
        else:
            self.frame._open_workspace_feature(section.split(".")[0], "overview")

    def _reveal(self, view) -> None:
        """只定位当前可见分区；后台更新和任务中心镜像均不抢夺滚动位置。"""
        if not view.isVisibleTo(self.frame):
            return
        ancestor = view.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                QTimer.singleShot(
                    0, view, lambda area=ancestor: area.ensureWidgetVisible(view, 0, 12)
                )
                break
            ancestor = ancestor.parentWidget()

    def export_result(self, request_id: str, text: str) -> None:
        """系统选择器只获取路径，正文写入交给现有串行后台文件队列。"""
        path, _ = QFileDialog.getSaveFileName(
            self.frame,
            tr("导出结果"),
            f"result-{request_id[:8]}.txt",
            "Text (*.txt)",
        )
        if path:
            self.frame.run_library.export_text(os.path.abspath(path), text)
