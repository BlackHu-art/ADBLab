from PySide6.QtCore import QObject, Signal


class LeftPanelSignals(QObject):
    """All signals emitted by LeftPanel."""

    # ── Device Management ──
    connect_requested = Signal(str)
    refresh_devices_requested = Signal()
    device_info_requested = Signal(list)
    disconnect_requested = Signal(list)
    restart_devices_requested = Signal(list)
    restart_adb_requested = Signal()
    reboot_mode_requested = Signal(list, str)  # (devices, mode)
    pair_device_requested = Signal(str, str, str)  # (ip, port, pairing_code)
    tcpip_mode_requested = Signal(list, str)  # (devices, port)

    # ── Screenshot & Recording ──
    screenshot_requested = Signal(list)
    screen_record_requested = Signal(list, int)  # (devices, duration)
    pull_recording_requested = Signal(list)  # (devices)
    batch_install_requested = Signal(list)  # (devices)

    # ── Logs ──
    retrieve_logs_requested = Signal(list)
    cleanup_logs_requested = Signal(list)
    logcat_filtered_requested = Signal(list, str, str, str, str)  # (devices, buffer, priority, tag, regex)

    # ── Input ──
    send_text_requested = Signal(list, str)
    input_tap_requested = Signal(list, int, int)  # (devices, x, y)
    input_swipe_requested = Signal(list, int, int, int, int, int)  # (devices, x1,y1,x2,y2,dur)
    input_keyevent_requested = Signal(list, str)  # (devices, keycode)

    # ── App Management ──
    generate_email_requested = Signal()
    get_program_requested = Signal(list)
    current_package_received = Signal(str, str)
    install_app_requested = Signal(list)
    uninstall_app_requested = Signal(list, str)
    clear_app_data_requested = Signal(list, str)
    restart_app_requested = Signal(list, str)
    print_activity_requested = Signal(list)
    parse_apk_info_requested = Signal()
    grant_permission_requested = Signal(list, str, str)  # (devices, package, permission)
    revoke_permission_requested = Signal(list, str, str)  # (devices, package, permission)
    disable_app_requested = Signal(list, str)  # (devices, package)
    enable_app_requested = Signal(list, str)  # (devices, package)
    force_stop_requested = Signal(list, str)  # (devices, package)
    open_deep_link_requested = Signal(list, str)  # (devices, uri)

    # ── Broadcast & Activity ──
    send_broadcast_requested = Signal(list, str)  # (devices, action)
    start_activity_requested = Signal(list, str)  # (devices, component/action)

    # ── Performance ──
    dumpsys_meminfo_requested = Signal(list, str)  # (devices, package)
    dumpsys_cpuinfo_requested = Signal(list)
    dumpsys_battery_requested = Signal(list)
    battery_set_requested = Signal(list, str, str)  # (devices, param, value)
    battery_reset_requested = Signal(list)

    # ── Monkey & Testing ──
    kill_monkey_requested = Signal(list)
    pull_anr_file_requested = Signal(list)
    list_installed_packages_requested = Signal(list)
    capture_bugreport_requested = Signal(list)
    start_monkey_requested = Signal(list, str, str, str)

    # ── Shell & File ──
    shell_command_requested = Signal(list, str)  # (devices, command)
    file_list_requested = Signal(list, str)  # (devices, path)
    file_push_requested = Signal(list, str, str)  # (devices, local, remote)
    file_pull_requested = Signal(list, str)  # (devices, remote_path)

    # ── Port Forwarding ──
    forward_port_requested = Signal(list, str, str)  # (devices, local, remote)
    list_forwards_requested = Signal(list)
    remove_forwards_requested = Signal(list)
    reverse_port_requested = Signal(list, str, str)  # (devices, remote, local)
    list_reverse_requested = Signal(list)
    remove_reverse_requested = Signal(list)

    # ── Settings ──
    settings_list_requested = Signal(list, str)  # (devices, namespace)
    settings_get_requested = Signal(list, str, str)  # (devices, namespace, key)
    settings_put_requested = Signal(list, str, str, str)  # (devices, namespace, key, val)

    # ── Process ──
    list_processes_requested = Signal(list)
    kill_process_requested = Signal(list, str)  # (devices, pid)

    # ── Content Provider ──
    content_query_requested = Signal(list, str)  # (devices, uri)

    # ── Quick Actions ──
    quick_setting_requested = Signal(list, str)  # (devices, action)

    # ── Extras ──
    ime_list_requested = Signal(list)
    ime_set_requested = Signal(list, str)  # (devices, ime_id)
    pm_features_requested = Signal(list)
    device_uptime_requested = Signal(list)
    emu_sms_requested = Signal(list, str, str)  # (devices, sender, text)
    emu_call_requested = Signal(list, str)  # (devices, number)
    emu_geo_requested = Signal(list, str, str)  # (devices, lon, lat)
