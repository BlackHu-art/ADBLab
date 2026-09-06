"""管理性能采集的参数复用与单次运行归档，不持有设备查询或存储文件。"""

from __future__ import annotations

import os
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.i18n import tr
from services.mobileperf_runner import MobilePerfRunConfig

if TYPE_CHECKING:
    from gui.dialogs.performance_launcher import PerformancePage
    from gui.run_library import RunLibraryController


@dataclass
class _ActivePerformanceRun:
    """保存已提交配置，避免运行结束时被页面编辑或历史参数覆盖。"""

    run_id: str
    started_at: float
    package_name: str
    parameters: dict
    device_label: str = ""
    cancelled: bool = False


class PerformanceLibrary:
    """桥接主窗口注入的结果库；所有入口均在页面所属 GUI 线程调用。"""

    def __init__(self, frame: PerformancePage) -> None:
        self._frame = frame
        self._library: RunLibraryController | None = None
        self._active: _ActivePerformanceRun | None = None

    def set_library(self, controller: RunLibraryController) -> None:
        self._library = controller
        self._frame.run_preset_bar.set_library(controller)
        self._frame.run_preset_bar.show()

    def parameters_for(self, config: MobilePerfRunConfig) -> dict:
        """参数只携带基础输出目录，设备身份始终由当前会话重新确定。"""
        parameters = asdict(config)
        parameters.pop("device_id")
        parameters.pop("mailbox")
        path = parameters["save_path"]
        if path and os.path.basename(os.path.normpath(path)) == self._frame._device_tag():
            path = os.path.dirname(os.path.normpath(path))
        parameters["save_path"] = path
        parameters["schema_version"] = 1
        return parameters

    def capture_parameters(self) -> dict | None:
        if self._busy() or not self._frame._commit_numeric_inputs():
            return None
        return self.parameters_for(self._frame.build_config())

    def _busy(self) -> bool:
        frame = self._frame
        return bool(frame._closing or frame._configuration_locked or frame._stopping
                    or frame._runner.is_running())

    def apply_parameters(self, parameters: dict) -> None:
        """先校验整个参数副本，再修改表单；不更新设备、不隐式执行采集。"""
        if self._busy():
            self._frame.log_received.emit("WARNING", tr("采集运行中，无法载入参数。"))
            return
        frame = self._frame
        try:
            if not isinstance(parameters, dict):
                raise ValueError
            version = parameters.get("schema_version", 1)
            if type(version) is not int or version != 1:
                raise ValueError
            numeric = {
                "frequency_seconds": frame.frequency_input,
                "timeout_minutes": frame.timeout_input,
                "dumpheap_minutes": frame.dumpheap_input,
            }
            monkey_numeric = {
                "throttle_ms": frame.monkey_throttle_combo,
                "seed": frame.monkey_seed_edit,
                **frame.monkey_pct_combos,
            }
            monkey = parameters.get("monkey_config", {})
            if not isinstance(monkey, dict):
                raise ValueError
            values = []
            for source, controls in ((parameters, numeric), (monkey, monkey_numeric)):
                for name, control in controls.items():
                    value = source.get(name, control.value())
                    if (type(value) is not int
                            or not control.minimum() <= value <= control.maximum()):
                        raise ValueError
                    values.append((control, value))
            checks = [(frame.monkey_check, parameters.get("monkey_enabled",
                                                         frame.monkey_check.isChecked()))]
            for name in (
                "ignore_crashes", "ignore_timeouts", "ignore_security", "kill_after_error",
            ):
                checkbox = getattr(frame, f"monkey_{name}")
                checks.append((checkbox, monkey.get(name, checkbox.isChecked())))
            if any(type(value) is not bool for _control, value in checks):
                raise ValueError
            texts = []
            for name, control in (("package", frame.package_edit),
                                  ("save_path", frame.save_path_edit)):
                value = parameters.get(name, control.text())
                if not isinstance(value, str):
                    raise ValueError
                texts.append((control, value))
            for name, control in (("exception_keywords", frame.exception_edit),
                                  ("phone_log_paths", frame.phone_log_edit)):
                value = parameters.get(name, control.text().split(";"))
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise ValueError
                texts.append((control, ";".join(value)))
        except ValueError:
            FluentMessageBox.warning(
                frame, tr("无法载入参数"), tr("参数格式或数值无效，当前设置未更改。")
            )
            return
        frame._invalidate_package_query()
        for control, value in values:
            control.setValue(value)
        for control, value in texts:
            control.setText(value)
        for control, value in checks:
            control.setChecked(value)
        frame.package_feedback.hide()
        frame._form_controller._update_monkey_total()
        frame.log_received.emit("INFO", tr("已载入参数，请确认当前设备后开始采集。"))

    def begin(self, config: MobilePerfRunConfig) -> None:
        label = self._frame.property("run_device_label")
        self._active = _ActivePerformanceRun(
            run_id=uuid4().hex,
            started_at=time.time(),
            package_name=config.package,
            parameters=deepcopy(self.parameters_for(config)),
            device_label=label.strip()[:200] if isinstance(label, str) else "",
        )

    def request_cancel(self) -> None:
        if self._active is not None:
            self._active.cancelled = True

    def finish(self, *, start_error: str | None = None) -> None:
        """实际进程退出后至多登记一次；关闭页面也必须经过此边界。"""
        active = self._active
        if active is None or (start_error is None and self._frame._runner.is_running()):
            return
        from services.run_library import RunArtifact, RunRecord

        artifacts = []
        report_file = ""
        artifact_error = False
        if start_error is None:
            runner = self._frame._runner
            # 分别探测附件，保留仍可读取的部分；文件系统故障不能中断关闭归档。
            try:
                result_dir = runner.latest_result_dir() or ""
                if isinstance(result_dir, str) and os.path.isdir(result_dir):
                    artifacts.append(RunArtifact(tr("结果目录"), os.path.abspath(result_dir)))
            except OSError:
                artifact_error = True
            try:
                candidate_report = runner.latest_report_file() or ""
                if (isinstance(candidate_report, str) and os.path.isfile(candidate_report)
                        and os.path.getsize(candidate_report) > 0):
                    report_file = os.path.abspath(candidate_report)
                    artifacts.append(RunArtifact(tr("性能报告"), report_file))
            except OSError:
                artifact_error = True
        if start_error is not None:
            state, message = "failed", tr("性能采集启动失败，请查看运行日志。")
        elif active.cancelled and not artifact_error:
            state, message = "cancelled", tr("采集已停止，已保留可用结果。")
        elif report_file and not artifact_error and self._frame._runner.last_exit_code == 0:
            state, message = "succeeded", tr("采集完成，已生成性能报告。")
        elif artifacts:
            state, message = "partial", tr("采集已结束，结果可能不完整。")
        else:
            state, message = "failed", tr("采集结束，但未生成可用结果。")
        record = RunRecord(
            run_id=active.run_id, kind="performance", package_name=active.package_name,
            started_at=active.started_at, finished_at=max(active.started_at, time.time()),
            state=state,
            parameters=deepcopy(active.parameters), artifacts=tuple(artifacts), message=message,
            device_label=active.device_label,
        )
        self._active = None
        if self._library is not None:
            self._library.record_run(record)
