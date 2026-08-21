---
kind: class
---

# ADBMediaMixin

- 模块：[[controllers._media]]
- 全名：controllers._media.ADBMediaMixin

> 协调截图、录屏、dumpsys、电池、Logcat、进程和运行时长操作

## 方法

- [[controllers._media.ADBMediaMixin.take_screenshot]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._screenshot_path]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._start_screenshot_process]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_screenshot_result]] — 处理未携带 operation envelope 的旧版兼容结果
- [[controllers._media.ADBMediaMixin._process_screenshot_operation_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._operation_metadata_matches]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._classify_screenshot_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._finish_screenshot_if_complete]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._fail_screenshot_operation]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._fail_operation_protocol]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.cancel_screenshot]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._emit_screenshot_terminal]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._show_screenshot_viewer]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._on_screenshot_viewer_destroyed]] — 移除已销毁截图窗口并记录关闭完成
- [[controllers._media.ADBMediaMixin.start_screen_record]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_start_screen_record_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._submit_recording_pull]] — 每个设备批次只提交一次录屏拉取；提交失败时立即释放终态
- [[controllers._media.ADBMediaMixin._auto_pull]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.stop_screen_record]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_stop_screen_record_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_pull_recorded_video_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.dumpsys_meminfo]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_dumpsys_meminfo_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.dumpsys_cpuinfo]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_dumpsys_cpuinfo_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.dumpsys_battery]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_dumpsys_battery_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.top_snapshot]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_top_snapshot_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.gfxinfo]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_gfxinfo_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.wakelocks]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_wakelocks_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.netstats_detail]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_netstats_detail_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.battery_set]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_battery_set_level_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_battery_set_status_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.battery_reset]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_battery_reset_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.logcat_filtered]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_logcat_filtered_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.list_processes]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_list_processes_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.kill_process]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_kill_process_result]] — （无 docstring）
- [[controllers._media.ADBMediaMixin.device_uptime]] — （无 docstring）
- [[controllers._media.ADBMediaMixin._process_get_device_uptime_result]] — （无 docstring）

