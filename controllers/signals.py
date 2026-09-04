"""定义 Controller 向界面发布状态和业务结果的 Qt 信号。

位于 controllers 包内，避免 controllers → gui 的包级循环依赖（ADR 分层）。
"""

from PySide6.QtCore import QObject, Signal


class ADBControllerSignals(QObject):
    """集中维护 ADB Controller 的界面输出信号契约。"""

    devices_updated = Signal(list)
    device_info_updated = Signal(str, dict)
    screenshot_captured = Signal(str, str)  # 兼容信号：设备、单张截图路径
    screenshot_batch_ready = Signal(list)  # 一次操作终态中的有序成功路径
    logs_retrieved = Signal(str, str)
    operation_completed = Signal(str, bool, str)
    text_input = Signal(str, str)
    current_package_received = Signal(str, str)

    record_finished = Signal()
    record_target_finished = Signal(str, str)  # 参数：批次标识、设备
    monkey_target_finished = Signal(str, str)  # 参数：批次标识、设备
