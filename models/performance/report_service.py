from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict
from datetime import datetime
from typing import Any

from core.settings_manager import AppSettings

from .types import FrameMetrics, MemorySample, StartupMetrics


def sanitize_name(value: str) -> str:
    value = value.strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


class PerformanceReportService:
    """Create per-device performance report artifacts."""

    def __init__(self, save_root: str | None = None):
        self.save_root = save_root or AppSettings.instance().save_directory

    def create_report_dir(self, device_id: str, package_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{sanitize_name(device_id)}_{sanitize_name(package_name)}_{timestamp}"
        report_dir = os.path.join(self.save_root, "performance", name)
        os.makedirs(os.path.join(report_dir, "raw"), exist_ok=True)
        return report_dir

    def write_report(
        self,
        report_dir: str,
        *,
        device_id: str,
        package_name: str,
        startup: StartupMetrics | None = None,
        frames: FrameMetrics | None = None,
        samples: list[MemorySample] | None = None,
        raw_files: dict[str, str] | None = None,
        status: str = "pass",
        findings: list[str] | None = None,
    ) -> dict[str, str]:
        samples = samples or []
        findings = findings or []
        raw_files = raw_files or {}
        summary: dict[str, Any] = {
            "device": device_id,
            "package": package_name,
            "status": status,
            "startup": startup.to_dict() if startup else None,
            "frames": frames.to_dict() if frames else None,
            "memory": {
                "first": samples[0].to_dict() if samples else None,
                "last": samples[-1].to_dict() if samples else None,
                "count": len(samples),
            },
            "findings": findings,
            "raw": raw_files,
        }

        summary_path = os.path.join(report_dir, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)

        metrics_path = os.path.join(report_dir, "metrics.csv")
        self._write_metrics_csv(metrics_path, samples)

        report_path = os.path.join(report_dir, "report.md")
        self._write_markdown_report(report_path, summary)
        return {
            "summary": summary_path,
            "metrics": metrics_path,
            "report": report_path,
        }

    @staticmethod
    def write_raw(report_dir: str, name: str, content: str) -> str:
        raw_dir = os.path.join(report_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        path = os.path.join(raw_dir, name)
        with open(path, "w", encoding="utf-8", errors="ignore") as handle:
            handle.write(content or "")
        return path

    @staticmethod
    def _write_metrics_csv(path: str, samples: list[MemorySample]) -> None:
        fieldnames = list(asdict(MemorySample(timestamp_ms=0)).keys())
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for sample in samples:
                writer.writerow(sample.to_dict())

    @staticmethod
    def _write_markdown_report(path: str, summary: dict[str, Any]) -> None:
        startup = summary.get("startup") or {}
        frames = summary.get("frames") or {}
        memory = (summary.get("memory") or {}).get("last") or {}
        findings = summary.get("findings") or []
        lines = [
            "# ADBLab Performance Report",
            "",
            f"- Device: `{summary.get('device', '')}`",
            f"- Package: `{summary.get('package', '')}`",
            f"- Status: `{summary.get('status', '')}`",
            "",
            "## Startup",
            f"- TotalTime: {startup.get('total_time_ms', 'N/A')} ms",
            f"- ThisTime: {startup.get('this_time_ms', 'N/A')} ms",
            f"- WaitTime: {startup.get('wait_time_ms', 'N/A')} ms",
            f"- Displayed: {startup.get('displayed_ms', 'N/A')} ms",
            f"- Fully drawn: {startup.get('fully_drawn_ms', 'N/A')} ms",
            "",
            "## Frames",
            f"- Total frames: {frames.get('total_frames', 'N/A')}",
            f"- Janky frames: {frames.get('janky_frames', 'N/A')}",
            f"- Jank rate: {frames.get('jank_rate', 0):.2%}" if frames else "- Jank rate: N/A",
            f"- P95: {frames.get('p95_ms', 'N/A')} ms",
            f"- Frozen frames: {frames.get('frozen_frames', 'N/A')}",
            "",
            "## Memory",
            f"- Total PSS: {memory.get('total_pss_kb', 'N/A')} KB",
            f"- Java Heap: {memory.get('java_heap_kb', 'N/A')} KB",
            f"- Native Heap: {memory.get('native_heap_kb', 'N/A')} KB",
            f"- Activities: {memory.get('activities', 'N/A')}",
            f"- Views: {memory.get('views', 'N/A')}",
            "",
            "## Findings",
        ]
        lines.extend(f"- {item}" for item in findings)
        if not findings:
            lines.append("- No threshold findings.")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
