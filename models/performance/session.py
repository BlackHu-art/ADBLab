from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PerformancePoint:
    timestamp_ms: int
    values: dict[str, float | int | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineMarker:
    timestamp_ms: int
    label: str
    kind: str = "marker"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricSummary:
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    last_value: float | None = None
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceSession:
    device_id: str
    package_name: str = ""
    activity: str = ""
    started_at_ms: int = 0
    status: str = "Idle"
    points: list[PerformancePoint] = field(default_factory=list)
    markers: list[TimelineMarker] = field(default_factory=list)
    metrics_enabled: list[str] = field(
        default_factory=lambda: ["fps", "cpu", "memory"]
    )

    def add_point(self, timestamp_ms: int, values: dict[str, float | int | None]) -> None:
        self.points.append(PerformancePoint(timestamp_ms=timestamp_ms, values=values))

    def update_latest_point(self, values: dict[str, float | int | None]) -> bool:
        if not self.points:
            return False
        self.points[-1].values.update(values)
        return True

    def add_marker(self, timestamp_ms: int, label: str, kind: str = "marker") -> None:
        self.markers.append(TimelineMarker(timestamp_ms=timestamp_ms, label=label, kind=kind))

    def metric_series(self, metric_name: str) -> list[tuple[int, float | int | None]]:
        return [
            (point.timestamp_ms, point.values.get(metric_name))
            for point in self.points
            if metric_name in point.values
        ]

    def latest_values(self) -> dict[str, float | int | None]:
        latest: dict[str, float | int | None] = {}
        for point in self.points:
            latest.update(point.values)
        return latest

    def summarize(self, metric_name: str) -> MetricSummary:
        values = [
            float(value)
            for _, value in self.metric_series(metric_name)
            if value is not None
        ]
        if not values:
            return MetricSummary()
        return MetricSummary(
            min_value=min(values),
            max_value=max(values),
            avg_value=sum(values) / len(values),
            last_value=values[-1],
            count=len(values),
        )

    def duration_ms(self, now_ms: int | None = None) -> int:
        if not self.started_at_ms:
            return 0
        if now_ms is None:
            now_ms = self.points[-1].timestamp_ms if self.points else self.started_at_ms
        return max(0, now_ms - self.started_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "package_name": self.package_name,
            "activity": self.activity,
            "started_at_ms": self.started_at_ms,
            "status": self.status,
            "metrics_enabled": self.metrics_enabled,
            "points": [point.to_dict() for point in self.points],
            "markers": [marker.to_dict() for marker in self.markers],
        }
