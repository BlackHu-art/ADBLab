---
kind: class
---

# _ADBControllerBase

- 模块：[[controllers._base]]
- 全名：controllers._base._ADBControllerBase

> 封装 ADBController 共用的模型、信号和处理器分派基础设施

## 方法

- [[controllers._base._ADBControllerBase.__init__]] — （无 docstring）
- [[controllers._base._ADBControllerBase._connect_model_signals]] — （无 docstring）
- [[controllers._base._ADBControllerBase._build_handler_map]] — （无 docstring）
- [[controllers._base._ADBControllerBase._generate_operation_id]] — （无 docstring）
- [[controllers._base._ADBControllerBase._register_operation_handler]] — 注册 vNext 处理器，同时保持旧处理器签名不变
- [[controllers._base._ADBControllerBase._emit_operation]] — （无 docstring）
- [[controllers._base._ADBControllerBase._attempt_actions_preserving_first]] — 依次尝试所有动作，并在最后传播第一个异常
- [[controllers._base._ADBControllerBase._require_devices]] — 校验设备列表；为空时发出失败结果并返回 False
- [[controllers._base._ADBControllerBase._handle_async_response]] — （无 docstring）
- [[controllers._base._ADBControllerBase._route_operation_response]] — （无 docstring）
- [[controllers._base._ADBControllerBase._claim_operation_response]] — （无 docstring）
- [[controllers._base._ADBControllerBase._release_operation_response]] — （无 docstring）
- [[controllers._base._ADBControllerBase._operation_metadata_matches]] — （无 docstring）
- [[controllers._base._ADBControllerBase._fail_claimed_operation_protocol]] — （无 docstring）
- [[controllers._base._ADBControllerBase._invoke_operation_handler]] — （无 docstring）
- [[controllers._base._ADBControllerBase._fail_operation_protocol]] — （无 docstring）
- [[controllers._base._ADBControllerBase._log_perf_if_slow]] — （无 docstring）
- [[controllers._base._ADBControllerBase._performance_log_threshold_ms]] — （无 docstring）
- [[controllers._base._ADBControllerBase._default_async_handler]] — （无 docstring）
- [[controllers._base._ADBControllerBase._indent_output]] — （无 docstring）
- [[controllers._base._ADBControllerBase._get_screenshot_dir]] — （无 docstring）
- [[controllers._base._ADBControllerBase.shutdown]] — 应用退出时统一收口后台资源，避免 adb/logcat/scrcpy 等子进程残留

