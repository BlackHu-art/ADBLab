---
kind: class
---

# MobilePerfRunner

- 模块：[[services.mobileperf_runner]]
- 全名：services.mobileperf_runner.MobilePerfRunner

> 在与 Qt 应用隔离的子进程中启动、停止并跟踪 MobilePerf

## 方法

- [[services.mobileperf_runner.MobilePerfRunner.__init__]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.config_path]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.last_config]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.last_exit_code]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.is_running]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.start]] — 创建临时配置并启动子进程，同时分别消费业务输出和开发诊断
- [[services.mobileperf_runner.MobilePerfRunner.stop]] — 请求生成报告并等待退出，超过报告时限后强制停止进程
- [[services.mobileperf_runner.MobilePerfRunner.request_stop]] — 写入停止文件，让采集内核在自身清理流程中结束
- [[services.mobileperf_runner.MobilePerfRunner._request_stop_context]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.force_stop]] — 在调用方给定的总时限内强制停止被跟踪的 MobilePerf 进程
- [[services.mobileperf_runner.MobilePerfRunner.expected_result_root]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.latest_result_dir]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner.latest_report_file]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._read_logs]] — 排空所属运行的 stdout，并按批次转发业务输出
- [[services.mobileperf_runner.MobilePerfRunner._read_diagnostics]] — 持续排空子进程 stderr，源码模式转发到 IDE，打包模式直接丢弃
- [[services.mobileperf_runner.MobilePerfRunner._safe_write_diagnostic]] — 隔离诊断输出异常，避免写入失败终止管道 reader
- [[services.mobileperf_runner.MobilePerfRunner._write_diagnostic]] — 仅在源码模式把脱敏诊断信息写入当前进程 stderr
- [[services.mobileperf_runner.MobilePerfRunner._sensitive_runtime_values]] — 返回本次运行禁止出现在诊断输出中的动态值
- [[services.mobileperf_runner.MobilePerfRunner._redact_runtime_values]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._mark_reader_done]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._maybe_notify_finished]] — 仅在同一运行的两个管道均排空且进程结束后发送完成通知
- [[services.mobileperf_runner.MobilePerfRunner._release_process_tracking]] — 按运行代次解除进程跟踪，避免旧停止流程命中新进程
- [[services.mobileperf_runner.MobilePerfRunner._join_context_readers]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._notify_finished]] — 保留旧测试和直接调用方使用的无上下文完成通知
- [[services.mobileperf_runner.MobilePerfRunner._cleanup_run_context]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._cleanup_config_dir]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._capture_result_baseline]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._result_baseline_for]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._contains_current_report]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._is_current_valid_report]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._package_result_root]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._path_key]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._path_signature]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._resolve_adb_path]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._build_command]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._default_project_root]] — （无 docstring）
- [[services.mobileperf_runner.MobilePerfRunner._is_frozen]] — （无 docstring）

