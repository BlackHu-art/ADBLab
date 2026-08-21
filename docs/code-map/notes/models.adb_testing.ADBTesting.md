---
kind: class
---

# ADBTesting

- 模块：[[models.adb_testing]]
- 全名：models.adb_testing.ADBTesting

> 封装 Monkey、Bugreport、截图、日志获取和 ANR 拉取操作

## 方法

- [[models.adb_testing.ADBTesting.__init__]] — （无 docstring）
- [[models.adb_testing.ADBTesting.shutdown]] — 终止 Monkey/logcat 等测试诊断进程，供应用退出时统一调用
- [[models.adb_testing.ADBTesting._wait_for_monkey_abort]] — 可中断等待监控间隔，并在停止请求到达时立即唤醒
- [[models.adb_testing.ADBTesting._get_current_package]] — （无 docstring）
- [[models.adb_testing.ADBTesting._command_timed_out]] — （无 docstring）
- [[models.adb_testing.ADBTesting._probe_current_package]] — 探测前台包名；超时、断连或解析失败时按失败关闭策略返回
- [[models.adb_testing.ADBTesting.take_screenshot_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting._is_valid_png]] — （无 docstring）
- [[models.adb_testing.ADBTesting.retrieve_device_logs_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting.cleanup_device_logs_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting.run_monkey_test_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting._count_executed_events]] — 统计 monkey log 中已执行的 Sending 事件数，用于断点续跑
- [[models.adb_testing.ADBTesting.kill_monkey_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting.capture_bugreport_async]] — （无 docstring）
- [[models.adb_testing.ADBTesting._extract_bugreport_zips]] — （无 docstring）
- [[models.adb_testing.ADBTesting._scan_and_convert_bugreport_txt]] — （无 docstring）
- [[models.adb_testing.ADBTesting._convert_bugreport_to_html]] — （无 docstring）
- [[models.adb_testing.ADBTesting.pull_anr_files_async]] — （无 docstring）

