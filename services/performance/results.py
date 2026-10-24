"""基于运行终态快照发现性能结果，不依赖采集进程运行器。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from services.performance_metadata import MetadataRead, metadata_filename, read_metadata


def path_key(path: Path) -> str:
    """使用绝对路径和平台大小写规则统一运行基线与结果的路径键。"""
    return os.path.normcase(os.path.abspath(str(path)))


@dataclass(frozen=True)
class PerformanceArtifacts:
    """后台验证过的本次结果快照，GUI 不再重复查询文件系统。"""

    result_dir: str = ""
    report_file: str = ""
    error: bool = False
    metadata_file: str = ""
    app_version: str = ""
    metadata_status: str = "legacy"


@dataclass(frozen=True)
class PerformanceResultQuery:
    """在运行终态冻结归属，延迟读取不会借用下一次运行的配置和基线。"""

    root: str
    baseline_dirs: tuple[tuple[str, tuple[int, int]], ...]
    baseline_reports: tuple[tuple[str, tuple[int, int]], ...]
    finished_at_ns: int = field(default_factory=time.time_ns)
    run_id: str = ""

    def discover(self) -> PerformanceArtifacts:
        """在后台单次遍历目录及报告，保留可确认的部分结果和错误事实。"""
        directories = dict(self.baseline_dirs)
        reports = dict(self.baseline_reports)
        found: list[tuple[int, str, str, MetadataRead]] = []
        error = False
        try:
            root = Path(self.root)
            if not root.exists():
                return PerformanceArtifacts(
                    metadata_status="missing" if self.run_id else "legacy",
                )
            for folder in root.iterdir():
                if not folder.is_dir():
                    continue
                try:
                    folder_stat = folder.stat()
                    signature = folder_stat.st_mtime_ns, folder_stat.st_size
                    metadata = (
                        read_metadata(
                            folder / metadata_filename(self.run_id), expected_run_id=self.run_id,
                            finished_at_ns=self.finished_at_ns,
                        ) if self.run_id else MetadataRead(status="legacy")
                    )
                    current_reports = []
                    for report in folder.glob("summary_*.xlsx"):
                        stat = report.stat()
                        if (report.is_file() and stat.st_size > 0
                                and stat.st_mtime_ns <= self.finished_at_ns
                                and (stat.st_mtime_ns, stat.st_size)
                                != reports.get(path_key(report))):
                            current_reports.append((stat.st_mtime_ns, str(report.absolute())))
                    if ((folder_stat.st_mtime_ns <= self.finished_at_ns
                         and signature != directories.get(path_key(folder)))
                            or current_reports or metadata.path):
                        order = (max(current_reports)[0] if current_reports
                                 else folder_stat.st_mtime_ns)
                        found.append((order, str(folder.absolute()),
                                      max(current_reports)[1] if current_reports else "", metadata))
                except OSError:
                    error = True
        except OSError:
            error = True
        if not found:
            return PerformanceArtifacts(
                error=error, metadata_status="missing" if self.run_id else "legacy",
            )
        # 随机运行标识比目录时间更精确；后续运行即使复用目录也不能抢占旧快照。
        owned = [item for item in found if item[3].path]
        _, folder, report, metadata = max(owned or found, key=lambda item: item[:3])
        return PerformanceArtifacts(
            folder, report, error, metadata.path, metadata.app_version, metadata.status,
        )
