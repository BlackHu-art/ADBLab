"""High-level input entrypoint for Remote mirroring."""

from core.adb_bridge import ADBBridge

from .text_injection import TextInjectionEngine
from .window_manager import RemoteWindowManager


class RemoteInputEngine:
    """Coordinates direct-window focus and text injection."""

    def __init__(
        self,
        adb: ADBBridge | None = None,
        text_engine: TextInjectionEngine | None = None,
        window_manager: RemoteWindowManager | None = None,
    ):
        self.adb = adb or ADBBridge()
        self.text_engine = text_engine or TextInjectionEngine(self.adb)
        self.window_manager = window_manager or RemoteWindowManager()

    @staticmethod
    def window_title(device_id: str) -> str:
        return f"ADBLab Remote - {device_id}"

    def focus_window(self, title: str, timeout_seconds: float = 2.5) -> bool:
        return self.window_manager.focus(title, timeout_seconds=timeout_seconds)

    def send_text(self, device_id: str, text: str):
        return self.text_engine.send_text(device_id, text)

    def paste_clipboard(self, device_id: str):
        return self.text_engine.paste_clipboard(device_id)
