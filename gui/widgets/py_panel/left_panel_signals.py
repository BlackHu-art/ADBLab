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
    generate_email_requested = Signal()  # 邮箱和验证码
    get_program_requested = Signal(list)
    current_package_received = Signal(str, str)  # (device_ip, package_name)
    install_app_requested = Signal(list)  # (devices, apk_path)
    uninstall_app_requested = Signal(list, str)
    clear_app_data_requested = Signal(list, str)
    restart_app_requested = Signal(list, str)
    print_activity_requested = Signal(list)
    parse_apk_info_requested = Signal()
    kill_monkey_requested = Signal(list)
    pull_anr_file_requested = Signal(list)
    list_installed_packages_requested = Signal(list)
    capture_bugreport_requested = Signal(list)
    start_monkey_requested = Signal(list, str, str, str)
