"""协调 Remote 投屏窗口的标题生成和聚焦操作。"""

from .window_manager import RemoteWindowManager


class RemoteInputEngine:
    """协调外部投屏窗口的直接聚焦。"""

    def __init__(
        self,
        window_manager: RemoteWindowManager | None = None,
    ):
        self.window_manager = window_manager or RemoteWindowManager()

    @staticmethod
    def window_title(device_id: str) -> str:
        """生成与 scrcpy 启动参数一致的窗口标题。"""
        return f"ADBLab Remote - {device_id}"

    def focus_window(self, title: str, timeout_seconds: float = 2.5) -> bool:
        """在限定时间内请求聚焦指定外部窗口。"""
        return self.window_manager.focus(title, timeout_seconds=timeout_seconds)
