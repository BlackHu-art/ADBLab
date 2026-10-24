"""保留媒体协调的旧组合入口，实际实现按截图、录屏和设备诊断职责归包。"""

from controllers.media.diagnostics import ADBDiagnosticsMixin
from controllers.media.recording import ADBRecordingMixin
from controllers.media.screenshot import ADBScreenshotMixin

__all__ = ["ADBMediaMixin"]


class ADBMediaMixin(ADBScreenshotMixin, ADBRecordingMixin, ADBDiagnosticsMixin):
    """组合三个媒体职责，沿用旧方法入口与基础初始化、协议链。"""
