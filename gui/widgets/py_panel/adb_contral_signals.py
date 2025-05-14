from PySide6.QtCore import QObject, Signal


class ADBControllerSignals(QObject):
    """ADB Controller Signal Definitions"""
    devices_updated = Signal(list)  # Device list updated
    device_info_updated = Signal(str, dict)  # Single device info updated (ip, info)
    screenshot_captured = Signal(str, str)  # Screenshot captured (ip, image path)
    logs_retrieved = Signal(str, str)  # Logs retrieved (ip, log content)
    operation_completed = Signal(str, bool, str)  # Operation result (operation name, success, message)
    text_input = Signal(str, str)  # (device_ip, input_text)
    current_package_received = Signal(str, str)  # (device_ip, package_name)
    install_apk_result  = Signal(dict)  # 请求选择APK文件
    uninstall_apk_result = Signal(str, str)  # (device_ip, package_name)
    clear_app_data_result = Signal(str, str)
    restart_app_result = Signal(str, str)
    print_activity_result = Signal(str)
    parse_apk_info_result = Signal()
    kill_monkey_result = Signal(str)
    pull_anr_file_result = Signal(str)
    list_packages_result = Signal(str)
    get_bugreport_result = Signal(str)
    start_monkey_result = Signal(str)
    
    email_updated = Signal(str)      # 设置 email_input 内容
    vercode_updated = Signal(str)    # 设置 vercode_input 内容