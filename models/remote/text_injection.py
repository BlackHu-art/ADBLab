"""Text injection helpers for Remote mirroring."""

import shlex

from core.adb_bridge import ADBBridge


class TextInjectionEngine:
    """Inject text independently from remote key/gesture controls."""

    def __init__(self, adb: ADBBridge | None = None):
        self.adb = adb or ADBBridge()

    def set_clipboard_text(self, device_id: str, text: str):
        if text == "":
            return None
        return self.adb.shell(
            f"cmd clipboard set text {shlex.quote(text)}",
            device_id=device_id,
        )

    def paste_clipboard(self, device_id: str):
        return self.adb.shell_input("keyevent 279", device_id=device_id)

    def send_text(self, device_id: str, text: str):
        if text == "":
            return None
        result = self.set_clipboard_text(device_id, text)
        if getattr(result, "success", True):
            return self.paste_clipboard(device_id)
        return result
