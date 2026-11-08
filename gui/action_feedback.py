"""组合根的操作反馈适配：连接来源分区、结果索引和异步文件动作。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QScrollArea

from controllers.action_catalog import ACTION_SIGNALS
from gui.i18n import tr
from gui.notifications import ToastLevel, show_toast
from gui.pages.device_hub import _device_name
from services.tasks.action_results import ActionResult, ActionSpec


class ActionFeedbackPresenter(QObject):
    """由主窗口拥有的唯一结果分发器；不持有设备任务，不解析日志作为结果。"""

    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame
        self._ended: set[str] = set()
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
            if spec.key == "take_screenshot" and not any(
                operation.kind == "screenshot"
                for operation in self.frame.adb_controller.operation_manager.active_snapshot()
            ):
                # 取消已结束业务操作，但旧 worker 尚未回调；拒绝重试时撤销按钮预置的忙碌态。
                apps = self.frame.left_panel.app_panel
                if apps is not None:
                    apps.on_screenshot_submission_rejected()
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
                tr("导出完成"),
                tr("结果文件已保存。"),
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
        self.frame._settings_page.update_diagnostics_summary(content)
        # 运行时 INFO 也会刷新诊断文件，不能据此重复提示之前保留的异常。
        if notify and journal.entries[-1][1] in warning_levels and not self.frame._closing:
            show_toast(
                self.frame,
                tr("发现应用异常"),
                tr("可在设置中查看详情或导出诊断。"),
                level="warning",
                action_text=tr("查看设置"),
                on_action=lambda: self.frame._on_nav_requested("settings"),
            )

    def _export_diagnostics(self) -> None:
        self.export_result("application-diagnostics", self.frame.log_service.diagnostics.text())

    def present(self, result: ActionResult) -> None:
        """原请求进入共享阅读器；后台更新不切页或抢走其他正在阅读的任务。"""
        if self.frame._closing:
            return
        self.frame._task_page.present_action_result(result)
        if result.spec.presentation == "notes":
            return
        if result.spec.section == "apps.diagnostics":
            self._diagnostics.present(result)
        elif result.spec.section == "apps.reports":
            self._reports.present(result)
        if result.state != "running" and result.request_id not in self._ended:
            self._ended.add(result.request_id)
            if len(self._ended) > 160:
                retained = self.frame.adb_controller.action_results.recent()
                # 去重只保留仍在结果存储中的终态请求，不额外延长历史保留。
                self._ended.intersection_update(
                    item.request_id for item in retained if item.state != "running"
                )
            # 成功和过程只更新页面与导航；失败资格由任务页的同一只读边界判断。
            if self.frame._task_page.allows_automatic_details(f"action:{result.request_id}"):
                self.frame._task_feedback.open_request(result.request_id, automatic=True)

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
        if (notify and result is not None
                and self.frame._task_page.allows_automatic_details(f"action:{result.request_id}")):
            self.frame._task_feedback.open_request(result.request_id, automatic=True)

    def open_task(self, request_id: str) -> None:
        """通知只定位提交时的任务，不切换设备、不重复执行命令。"""
        if self.frame._closing:
            return
        page = self.frame._task_page
        result = next((item for item in self.frame.adb_controller.action_results.recent()
                       if item.request_id == request_id), None)
        if result is not None:
            page.present_action_result(result)
        self.frame._task_feedback.open_request(request_id)

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
        elif section in {"devices.files", "devices.remote", "apps.manager", "system.logcat",
                         "system.performance"}:
            owner, feature = section.split(".", 1)
            self.frame._open_workspace_feature(owner, feature)
        else:
            self.frame._open_workspace_feature(section.split(".")[0], "overview")

    def _reveal(self, view) -> None:
        """只纵向定位仍可见的结果，宽内容不能把整页横移到导航下方。"""
        if not view.isVisibleTo(self.frame):
            return

        def reveal() -> None:
            if not view.isVisibleTo(self.frame):
                return
            ancestor = view.parentWidget()
            while ancestor is not None:
                if isinstance(ancestor, QScrollArea):
                    content = ancestor.widget()
                    if content is None or not content.isAncestorOf(view):
                        return
                    center = view.mapTo(content, view.rect().center())
                    # 隐藏横向滚动条仍允许程序滚动；只沿当前水平位置定位纵向中心。
                    ancestor.ensureVisible(
                        ancestor.horizontalScrollBar().value(), center.y(), 0,
                        min(view.height() // 2 + 12, ancestor.viewport().height() // 2),
                    )
                    return
                ancestor = ancestor.parentWidget()

        QTimer.singleShot(0, view, reveal)

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
