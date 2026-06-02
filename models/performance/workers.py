from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .service import PerformanceService


class PerformanceSnapshotWorker(QThread):
    snapshot_ready = Signal(object)
    status_changed = Signal(str)
    device_info_ready = Signal(object)

    def __init__(self, service: PerformanceService, package_name: str = ""):
        super().__init__()
        self.service = service
        self.package_name = package_name

    def run(self):
        try:
            device_info = self.service.device_info()
            if not self.isInterruptionRequested():
                self.device_info_ready.emit(device_info.rows())
            snapshot = self.service.snapshot(self.package_name)
            if not self.isInterruptionRequested():
                self.snapshot_ready.emit(snapshot)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Snapshot failed: {exc}")


class PerformanceFrameWorker(QThread):
    result_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, service: PerformanceService, package_name: str):
        super().__init__()
        self.service = service
        self.package_name = package_name

    def run(self):
        try:
            frames = self.service.frame_metrics(self.package_name)
            if not self.isInterruptionRequested():
                self.result_ready.emit(frames)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Frame refresh failed: {exc}")


class PerformanceQuickCheckWorker(QThread):
    result_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, service: PerformanceService, package_name: str, activity: str = ""):
        super().__init__()
        self.service = service
        self.package_name = package_name
        self.activity = activity

    def run(self):
        try:
            self.status_changed.emit("Running Quick Check...")
            result = self.service.quick_check(self.package_name, self.activity)
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Quick Check failed: {exc}")


class PerformanceAnalyzeWorker(QThread):
    result_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, service: PerformanceService, package_name: str, samples: list, started_at: float):
        super().__init__()
        self.service = service
        self.package_name = package_name
        self.samples = samples
        self.started_at = started_at

    def run(self):
        try:
            self.status_changed.emit("Analyzing monitor session...")
            frames = self.service.frame_metrics(self.package_name)
            report_service = self.service.report_service
            report_dir = report_service.create_report_dir(self.service.device_id, self.package_name or "unknown")
            findings = []
            if frames and frames.jank_rate > 0.05:
                findings.append(f"Jank rate: {frames.jank_rate:.2%}")
            if len(self.samples) >= 2:
                first = self.samples[0].total_pss_kb or 0
                last = self.samples[-1].total_pss_kb or 0
                if first and last - first > 10240:
                    findings.append(f"PSS grew by {last - first} KB")
            status = "warn" if findings else "pass"
            artifacts = report_service.write_report(
                report_dir,
                device_id=self.service.device_id,
                package_name=self.package_name,
                frames=frames,
                samples=self.samples,
                findings=findings,
                status=status,
            )
            result = {
                "success": True,
                "report_dir": report_dir,
                "artifacts": artifacts,
                "frames": frames,
                "samples": self.samples,
                "findings": findings,
                "status": status,
                "duration": int(time.monotonic() - self.started_at),
            }
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Analyze failed: {exc}")
