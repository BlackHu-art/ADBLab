from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .providers import PerformanceSampleProvider
from .service import PerformanceService


class PerformanceProviderWorker(QThread):
    snapshot_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        provider: PerformanceSampleProvider,
        target: str,
        *,
        interval_ms: int = 1000,
        max_samples: int | None = None,
    ):
        super().__init__()
        self.provider = provider
        self.target = target
        self.interval_ms = max(100, int(interval_ms))
        self.max_samples = max_samples

    def run(self):
        sample_count = 0
        try:
            self.provider.start(self.target)
            while not self.isInterruptionRequested():
                snapshot = self.provider.sample(self.target)
                if self.isInterruptionRequested():
                    break
                self.snapshot_ready.emit(snapshot)
                sample_count += 1
                if self.max_samples is not None and sample_count >= self.max_samples:
                    break
                if not bool(getattr(self.provider, "paced", False)):
                    self.msleep(self.interval_ms)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Provider failed: {exc}")
        finally:
            try:
                self.provider.stop()
            except Exception as exc:
                if not self.isInterruptionRequested():
                    self.status_changed.emit(f"Provider stop failed: {exc}")

    def stop_provider(self) -> None:
        self.requestInterruption()
        try:
            self.provider.stop()
        except Exception:
            pass


class PerformanceDeviceInfoWorker(QThread):
    device_info_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        service: PerformanceService,
        *,
        refresh_device_info: bool = False,
    ):
        super().__init__()
        self.service = service
        self.refresh_device_info = refresh_device_info

    def run(self):
        try:
            device_info = self.service.device_info(refresh=self.refresh_device_info)
            if not self.isInterruptionRequested():
                self.device_info_ready.emit(device_info.rows())
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Device info failed: {exc}")


class PerformanceCurrentPackageWorker(QThread):
    package_ready = Signal(str)
    status_changed = Signal(str)

    def __init__(self, service: PerformanceService):
        super().__init__()
        self.service = service

    def run(self):
        try:
            package_name = self.service.current_package()
            if not self.isInterruptionRequested():
                if package_name:
                    self.package_ready.emit(package_name)
                else:
                    self.status_changed.emit("Current package unavailable")
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Current package failed: {exc}")


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

    def __init__(
        self,
        service: PerformanceService,
        package_name: str,
        samples: list,
        cpu_samples: list | None,
        started_at: float,
        findings: list[str] | None = None,
    ):
        super().__init__()
        self.service = service
        self.package_name = package_name
        self.samples = samples
        self.cpu_samples = list(cpu_samples or [])
        self.started_at = started_at
        self.initial_findings = list(findings or [])

    def run(self):
        try:
            self.status_changed.emit("Analyzing monitor session...")
            frames = None
            report_service = self.service.report_service
            report_dir = report_service.create_report_dir(self.service.device_id, self.package_name or "unknown")
            findings = list(self.initial_findings)
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
                cpu_samples=self.cpu_samples,
                findings=findings,
                status=status,
            )
            result = {
                "success": True,
                "report_dir": report_dir,
                "artifacts": artifacts,
                "frames": frames,
                "samples": self.samples,
                "cpu_samples": self.cpu_samples,
                "findings": findings,
                "status": status,
                "duration": int(time.monotonic() - self.started_at),
            }
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Analyze failed: {exc}")
