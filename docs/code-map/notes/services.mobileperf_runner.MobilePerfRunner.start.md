---
kind: method
---

# start(self, config, *, on_log=None, on_finished=None)

- 定义于：[[services.mobileperf_runner.MobilePerfRunner]]
- 全名：services.mobileperf_runner.MobilePerfRunner.start

> 创建临时配置并启动子进程，同时分别消费业务输出和开发诊断

## 调用

- [[services.mobileperf_runner.MobilePerfRunConfig.write_config]]
- [[services.mobileperf_runner.MobilePerfRunner._build_command]]
- [[services.mobileperf_runner.MobilePerfRunner._capture_result_baseline]]
- [[services.mobileperf_runner.MobilePerfRunner._resolve_adb_path]]
- [[services.mobileperf_runner.MobilePerfRunner._safe_write_diagnostic]]
- [[services.mobileperf_runner.MobilePerfRunner._sensitive_runtime_values]]
- [[services.mobileperf_runner.MobilePerfRunner.expected_result_root]]
- [[services.mobileperf_runner.MobilePerfRunner.is_running]]
- [[utils.user_data.user_data_root]]

## 实例化

- [[services.mobileperf_runner._MobilePerfRunContext]]

