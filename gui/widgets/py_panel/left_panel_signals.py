from PySide6.QtCore import QObject, Signal

class LeftPanelSignals(QObject):
    """LeftPanel的所有信号定义"""
    connect_requested = Signal(str)  # IP地址
    refresh_devices_requested = Signal()
    device_info_requested = Signal(list)  # 选中设备列表
    disconnect_requested = Signal(list)
    restart_devices_requested = Signal(list)
    restart_adb_requested = Signal()
    screenshot_requested = Signal(list)
    retrieve_logs_requested = Signal(list)
    cleanup_logs_requested = Signal(list)
    send_text_requested = Signal(list, str)  # 设备列表和文本
    generate_email_requested = Signal(str)  # 邮箱和验证码
    get_program_requested = Signal(list)
    current_package_received = Signal(str, str)  # (device_ip, package_name)