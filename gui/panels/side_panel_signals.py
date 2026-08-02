"""集中定义 SidePanel 及其子面板发出的 Qt 信号。"""

from contextlib import contextmanager

from PySide6.QtCore import QObject, Signal


@contextmanager
def BlockSignals(widget):
    """上下文管理器：临时阻塞 widget 的所有信号。"""
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)


class SidePanelSignals(QObject):
    """作为面板与 Controller 之间的稳定信号契约。"""

    # ── 日志 ──
    log_message = Signal(str, str)  # 参数：日志级别、消息

    # ── 设备管理 ──
    connect_requested = Signal(str)
    refresh_devices_requested = Signal()
    device_info_requested = Signal(list)
    disconnect_requested = Signal(list)
    restart_devices_requested = Signal(list)
    restart_adb_requested = Signal()
    reboot_mode_requested = Signal(list, str)  # 参数：设备列表、重启模式
    tcpip_mode_requested = Signal(list, str)  # 参数：设备列表、端口

    # ── 截图与录屏 ──
    screenshot_requested = Signal(list)
    screen_record_requested = Signal(list, int)  # 参数：设备列表、录制时长
    stop_screen_record_requested = Signal(list)  # 参数：设备列表
    batch_install_requested = Signal(list)  # 参数：设备列表

    # ── 设备日志 ──
    retrieve_logs_requested = Signal(list)
    cleanup_logs_requested = Signal(list)
    # ── 输入控制 ──
    send_text_requested = Signal(list, str)
    input_tap_requested = Signal(list, int, int)  # 参数：设备列表、横坐标、纵坐标
    input_swipe_requested = Signal(list, int, int, int, int, int)  # 参数：设备列表、起止坐标、时长
    input_keyevent_requested = Signal(list, str)  # 参数：设备列表、键码

    # ── 应用管理 ──
    generate_email_requested = Signal()
    get_program_requested = Signal(list)
    current_package_received = Signal(str, str)
    uninstall_app_requested = Signal(list, str)
    clear_app_data_requested = Signal(list, str)
    restart_app_requested = Signal(list, str)
    print_activity_requested = Signal(list)
    parse_apk_info_requested = Signal()
    disable_app_requested = Signal(list, str)  # 参数：设备列表、包名
    enable_app_requested = Signal(list, str)  # 参数：设备列表、包名
    force_stop_requested = Signal(list, str)  # 参数：设备列表、包名
    open_deep_link_requested = Signal(list, str)  # 参数：设备列表、URI

    # ── 广播与 Activity ──
    send_broadcast_requested = Signal(list, str)  # 参数：设备列表、action
    start_activity_requested = Signal(list, str)  # 参数：设备列表、组件或 action

    # ── 性能诊断 ──
    dumpsys_meminfo_requested = Signal(list, str)  # 参数：设备列表、包名
    dumpsys_cpuinfo_requested = Signal(list)
    dumpsys_battery_requested = Signal(list)
    battery_set_requested = Signal(list, str, str)  # 参数：设备列表、参数名、参数值
    battery_reset_requested = Signal(list)

    # ── Monkey 与测试 ──
    kill_monkey_requested = Signal(list)
    pull_anr_file_requested = Signal(list)
    capture_bugreport_requested = Signal(list)
    start_monkey_requested = Signal(list, dict)

    # ── Shell 与文件 ──
    shell_command_requested = Signal(list, str)  # 参数：设备列表、命令

    # ── 端口转发 ──
    forward_port_requested = Signal(list, str, str)  # 参数：设备列表、本地端口、远端端口
    list_forwards_requested = Signal(list)
    remove_forwards_requested = Signal(list)
    reverse_port_requested = Signal(list, str, str)  # 参数：设备列表、远端端口、本地端口
    list_reverse_requested = Signal(list)
    remove_reverse_requested = Signal(list)

    # ── Android 设置 ──
    settings_list_requested = Signal(list, str)  # 参数：设备列表、命名空间
    settings_get_requested = Signal(list, str, str)  # 参数：设备列表、命名空间、键
    settings_put_requested = Signal(list, str, str, str)  # 参数：设备列表、命名空间、键、值

    # ── 进程 ──
    list_processes_requested = Signal(list)
    kill_process_requested = Signal(list, str)  # 参数：设备列表、PID

    # ── 内容提供程序（Content Provider）──
    content_query_requested = Signal(list, str)  # 参数：设备列表、URI

    # ── 快捷操作 ──
    quick_setting_requested = Signal(list, str)  # 参数：设备列表、操作

    # ── 扩展能力 ──
    ime_list_requested = Signal(list)
    ime_set_requested = Signal(list, str)  # 参数：设备列表、输入法标识
    pm_features_requested = Signal(list)
    device_uptime_requested = Signal(list)
    emu_sms_requested = Signal(list, str, str)  # 参数：设备列表、发送方、文本
    emu_call_requested = Signal(list, str)  # 参数：设备列表、号码
    emu_geo_requested = Signal(list, str, str)  # 参数：设备列表、经度、纬度
