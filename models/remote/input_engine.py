"""Window helpers for Remote mirroring."""

from .window_manager import RemoteWindowManager


class RemoteInputEngine:
    """Coordinates direct-window focus."""

    def __init__(
        self,
        window_manager: RemoteWindowManager | None = None,
    ):
        self.window_manager = window_manager or RemoteWindowManager()

    @staticmethod
    def window_title(device_id: str) -> str:
        return f"ADBLab Remote - {device_id}"

    def focus_window(self, title: str, timeout_seconds: float = 2.5) -> bool:
        return self.window_manager.focus(title, timeout_seconds=timeout_seconds)
