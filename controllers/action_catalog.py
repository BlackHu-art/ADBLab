"""维护通用操作的结果归属；每个接线入口必须有显式的功能分区。"""

from adblab.application.action_results import ActionSpec


def _spec(key: str, section: str, title: str, presentation: str = "status") -> ActionSpec:
    return ActionSpec(key, section, title, presentation)


ACTION_SIGNALS = {
    "system_service_requested": _spec("system_service", "system.services", "系统服务开关"),
    "connect_requested": _spec("connect_device", "devices", "连接设备"),
    "refresh_devices_requested": _spec("refresh_devices", "devices", "刷新设备"),
    "disconnect_requested": _spec("disconnect_devices", "devices", "断开设备"),
    "restart_devices_requested": _spec("restart_devices", "devices", "重启设备"),
    "restart_adb_requested": _spec("restart_adb", "devices", "重启 ADB"),
    "reboot_mode_requested": _spec("reboot_mode", "system.reboot", "重启设备"),
    "tcpip_mode_requested": _spec("tcpip_mode", "system.reboot", "开启 TCP/IP"),
    "screenshot_requested": _spec("take_screenshot", "apps.media", "截图", "artifact"),
    "screen_record_requested": _spec("start_screen_record", "apps.media", "开始录屏"),
    "screen_record_batch_requested": _spec("start_screen_record", "apps.media", "开始录屏"),
    "stop_screen_record_requested": _spec("stop_screen_record", "apps.media", "停止录屏"),
    "stop_screen_record_batch_requested": _spec("stop_screen_record", "apps.media", "停止录屏"),
    "batch_install_requested": _spec("batch_install_apk", "apps.packages", "批量安装"),
    "retrieve_logs_requested": _spec(
        "retrieve_device_logs", "apps.reports", "提取日志", "artifact"
    ),
    "cleanup_logs_requested": _spec("cleanup_device_logs", "apps.reports", "清理设备日志"),
    "send_text_requested": _spec("input_text", "apps.media", "发送文本"),
    "input_tap_requested": _spec("input_tap", "apps.media", "发送点击"),
    "input_swipe_requested": _spec("input_swipe", "apps.media", "发送滑动"),
    "input_keyevent_requested": _spec("input_keyevent", "apps.media", "发送按键"),
    "get_program_requested": _spec("get_current_package", "apps.packages", "获取前台应用", "text"),
    "uninstall_app_requested": _spec("uninstall_apk", "apps.packages", "卸载应用"),
    "clear_app_data_requested": _spec("clear_app_data", "apps.packages", "清除应用数据"),
    "restart_app_requested": _spec("restart_app", "apps.packages", "重启应用"),
    "print_activity_requested": _spec(
        "get_current_activity", "apps.packages", "当前 Activity", "text"
    ),
    "parse_apk_info_requested": _spec("parse_apk_info", "apps.packages", "APK 信息", "text"),
    "disable_app_requested": _spec("disable_app", "apps.packages", "禁用应用"),
    "disable_app_for_user_requested": _spec(
        "disable_app_for_user", "apps.packages", "对当前用户禁用应用"
    ),
    "enable_app_requested": _spec("enable_app", "apps.packages", "启用应用"),
    "force_stop_requested": _spec("force_stop", "apps.packages", "强行停止应用"),
    "send_broadcast_requested": _spec("send_broadcast", "system.intent", "发送广播"),
    "start_activity_requested": _spec("start_activity", "system.intent", "启动 Activity"),
    "open_deep_link_requested": _spec("open_deep_link", "system.intent", "打开链接"),
    "start_monkey_requested": _spec("run_monkey_test", "apps.monkey", "Monkey 测试", "artifact"),
    "start_monkey_batch_requested": _spec(
        "run_monkey_test", "apps.monkey", "Monkey 测试", "artifact"
    ),
    "kill_monkey_requested": _spec("kill_monkey", "apps.monkey", "停止 Monkey"),
    "kill_monkey_batch_requested": _spec("kill_monkey", "apps.monkey", "停止 Monkey"),
    "capture_bugreport_requested": _spec(
        "capture_bugreport", "apps.reports", "生成 Bugreport", "artifact"
    ),
    "pull_anr_file_requested": _spec("pull_anr_files", "apps.reports", "提取 ANR", "artifact"),
    "dumpsys_meminfo_requested": _spec("dumpsys_meminfo", "apps.diagnostics", "内存", "text"),
    "dumpsys_cpuinfo_requested": _spec("dumpsys_cpuinfo", "apps.diagnostics", "CPU 负载", "text"),
    "dumpsys_battery_requested": _spec("dumpsys_battery", "apps.diagnostics", "电池", "text"),
    "top_snapshot_requested": _spec("top_snapshot", "apps.diagnostics", "进程快照", "text"),
    "gfxinfo_requested": _spec("gfxinfo", "apps.diagnostics", "GFX 信息", "text"),
    "wakelocks_requested": _spec("wakelocks", "apps.diagnostics", "唤醒锁", "text"),
    "netstats_detail_requested": _spec("netstats_detail", "apps.diagnostics", "网络统计", "text"),
    "device_uptime_requested": _spec("device_uptime", "apps.diagnostics", "运行时长", "text"),
    "shell_command_requested": _spec("run_shell_command", "system.shell", "Shell 命令", "text"),
    "dumpsys_service_requested": _spec("dumpsys_service", "system.tools", "系统服务", "text"),
    "kernel_version_requested": _spec("kernel_version", "system.tools", "内核版本", "text"),
    "cpu_info_requested": _spec("cpu_info", "system.tools", "CPU 信息", "text"),
    "forward_port_requested": _spec("forward_port", "system.ports", "添加端口转发"),
    "list_forwards_requested": _spec("list_forwards", "system.ports", "端口转发列表", "text"),
    "remove_forwards_requested": _spec("remove_forwards", "system.ports", "移除端口转发"),
    "reverse_port_requested": _spec("reverse_port", "system.ports", "添加反向转发"),
    "list_reverse_requested": _spec("list_reverse", "system.ports", "反向转发列表", "text"),
    "remove_reverse_requested": _spec("remove_reverse", "system.ports", "移除反向转发"),
    "settings_list_requested": _spec(
        "settings_list", "system.settings", "Android 设置列表", "text"
    ),
    "settings_get_requested": _spec("settings_get", "system.settings", "读取 Android 设置", "text"),
    "settings_put_requested": _spec("settings_put", "system.settings", "写入 Android 设置"),
    "content_query_requested": _spec("content_query", "system.tools", "查询内容提供者", "text"),
    "list_processes_requested": _spec("list_processes", "system.tools", "进程列表", "text"),
    "kill_process_requested": _spec("kill_process", "system.tools", "结束进程"),
    "battery_set_requested": _spec("battery_set", "system.battery", "设置电池状态"),
    "battery_reset_requested": _spec("battery_reset", "system.battery", "重置电池状态"),
    "quick_setting_requested": _spec("quick_setting", "system.battery", "快捷设置"),
    "ime_list_requested": _spec("ime_list", "system.input", "输入法列表", "text"),
    "ime_set_requested": _spec("ime_set", "system.input", "设置输入法"),
    "pm_features_requested": _spec("pm_features", "system.tools", "设备功能", "text"),
    "emu_sms_requested": _spec("emu_sms", "system.input", "模拟短信"),
    "emu_call_requested": _spec("emu_call", "system.input", "模拟来电"),
    "emu_geo_requested": _spec("emu_geo", "system.input", "模拟位置"),
}

RECORDING_RESULT = _spec("save_recording", "apps.media", "保存录屏", "artifact")
