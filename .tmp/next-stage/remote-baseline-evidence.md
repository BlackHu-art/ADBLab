# Remote 主窗既存失败证据

- 基线 commit：`a90b3e2e599cd7c06343a2ff151cd695e3b76ff1`。
- 当前工作树和完整 `git archive HEAD` 快照均在相同节点、相同断言失败。
- 当前结果：1 failed，2.54 秒。HEAD 快照结果：1 failed，2.83 秒。
- 失败节点：`tests/test_main_window_layout.py::test_remote_workspace_requires_an_explicit_session_device_when_multiple_online`。
- 相同断言：第 1025 行 `remote.selected_devices == ["device-2"]`，实际 `[]`。

基线导出命令：

```powershell
git archive --format=zip --output=.tmp/next-stage/remote-head-baseline.zip HEAD
Expand-Archive -LiteralPath '.tmp/next-stage/remote-head-baseline.zip' -DestinationPath '.tmp/next-stage/remote-head-baseline'
```

测试工作目录分别为当前仓库根、`.tmp/next-stage/remote-head-baseline`，使用同一活动项目解释器：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_SCALE_FACTOR = '1'
& 'D:/Program Files (x86)/JetBrains/PyStation/ADBLab/.venv/Scripts/python.exe' -m pytest -q tests/test_main_window_layout.py::test_remote_workspace_requires_an_explicit_session_device_when_multiple_online
```

已确认调用链：`WorkspaceFeatureHost._on_device_changed` 只切换会话设备；
`MainFrame._activate_remote_workspace` 将 `device_id in left_panel.selected_devices`
投影给 Remote；`RemotePanel.selected_devices` 在 `_device_selected=False` 时返回空。
这两处准入逻辑已存在于上述 HEAD。测试只调用 `host.set_device_context([], 两台在线设备)`
并选择会话，没有通过全局勾选授权设备操作，因此旧断言与既存准入契约冲突。

本轮结果库、性能页工厂和 DeviceContextBar 隐藏按钮清理没有修改这条调用链。
未修改生产或既存测试。导出目录和 ZIP 已按主任务要求精确清理；本文保留执行证据。
