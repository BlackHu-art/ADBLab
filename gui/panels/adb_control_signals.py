from PySide6.QtCore import QObject, Signal


class ADBControllerSignals(QObject):
    """ADB Controller signal definitions."""

    devices_updated = Signal(list)
    device_info_updated = Signal(str, dict)
    screenshot_captured = Signal(str, str)
    logs_retrieved = Signal(str, str)
    operation_completed = Signal(str, bool, str)
    text_input = Signal(str, str)
    current_package_received = Signal(str, str)

    email_updated = Signal(str)
    vercode_updated = Signal(str)
