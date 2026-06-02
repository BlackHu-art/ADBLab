from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PerformanceSamplingSchedule:
    """Tracks independent metric sampling cadence for a monitor session."""

    frame_interval_ms: int
    last_frame_refresh_at: float = 0.0

    @property
    def frame_interval_seconds(self) -> float:
        return max(0.0, self.frame_interval_ms / 1000)

    def reset(self) -> None:
        self.last_frame_refresh_at = 0.0

    def should_refresh_frame(self, now: float, *, force: bool = False) -> bool:
        if force or not self.last_frame_refresh_at:
            return True
        return now - self.last_frame_refresh_at >= self.frame_interval_seconds

    def mark_frame_refresh(self, now: float) -> None:
        self.last_frame_refresh_at = now
