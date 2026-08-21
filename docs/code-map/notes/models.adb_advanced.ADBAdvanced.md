---
kind: class
---

# ADBAdvanced

- 模块：[[models.adb_advanced]]
- 全名：models.adb_advanced.ADBAdvanced

> 组合核心、网络和系统级 ADB 操作

## 方法

- [[models.adb_advanced.ADBAdvanced.__init__]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.start_screen_record_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.stop_screen_record_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.pull_recorded_video_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.input_tap_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.input_swipe_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.input_keyevent_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.input_longpress_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.input_drag_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced._send_input]] — 复用持久 adb shell input 通道；失败时 ADBBridge 内部会回退到独立进程
- [[models.adb_advanced.ADBAdvanced._input_bridge]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.close_input_sessions]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.shutdown]] — 关闭高级功能持有的长生命周期进程，防止主窗口退出后残留
- [[models.adb_advanced.ADBAdvanced.dumpsys_meminfo_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.dumpsys_cpuinfo_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.dumpsys_battery_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.logcat_filtered_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.logcat_buffer_sizes_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.settings_list_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.settings_get_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.settings_put_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.run_shell_command_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.reboot_mode_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.shell_ls_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.shell_rm_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.shell_mkdir_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.push_file_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.pull_file_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.shell_df_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.get_device_date_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.get_device_uptime_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.get_cpu_info_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.get_kernel_version_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.getprop_all_async]] — （无 docstring）
- [[models.adb_advanced.ADBAdvanced.backup_app_async]] — （无 docstring）

