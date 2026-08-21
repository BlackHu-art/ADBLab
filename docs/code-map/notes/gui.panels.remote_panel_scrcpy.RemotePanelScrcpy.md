---
kind: class
---

# RemotePanelScrcpy

- 模块：[[gui.panels.remote_panel_scrcpy]]
- 全名：gui.panels.remote_panel_scrcpy.RemotePanelScrcpy

> 组合进 RemotePanel 的 scrcpy 控制器，通过 ``self._frame`` 访问面板

## 方法

- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy.__init__]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._start_scrcpy]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._on_launch_ready]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._on_launch_finished]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._read_stderr]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._poll_process]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._stop_scrcpy]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._on_stop_completed]] — 在 GUI 线程收口停止结果，并避免旧进程尚未退出时提前允许再次启动
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._set_session_state]] — 统一应用 Idle/Starting/Running/Stopping 对应的按钮可用状态
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._scrcpy_config]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._focus_scrcpy_window]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._stop_launch_worker]] — （无 docstring）
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._claim_scrcpy_stop]] — 原子取得当前 scrcpy 会话的唯一停止所有权
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._release_scrcpy_stop_claim]] — 仅允许持有者释放自己的停止 token，避免旧会话污染新会话
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._reset_scrcpy_stop_claim]] — 在新 scrcpy 进程成功启动后开放该会话的第一次停止请求
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._request_scrcpy_stop_once]] — 为一个 scrcpy 会话只发送一次异步停止请求
- [[gui.panels.remote_panel_scrcpy.RemotePanelScrcpy._request_launch_worker_interruption_once]] — 同一启动 worker 在多条关闭路径中只接收一次中断请求

