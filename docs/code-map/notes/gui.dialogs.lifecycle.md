---
kind: file
---

# gui.dialogs.lifecycle

> 提供对话框信号断开、对象存活检查和 worker 清理辅助能力

- 路径：gui/dialogs/lifecycle.py

## 类

- [[gui.dialogs.lifecycle.QThreadGroupShutdownTask]] — 将一组已捕获的 QThread 适配为应用资源监督协议
- [[gui.dialogs.lifecycle.WorkerSignalBinding]] — （无 docstring）

## 函数

- [[gui.dialogs.lifecycle.alive_callback]] — （无 docstring）
- [[gui.dialogs.lifecycle.alive_forwarding_callback]] — 仅在 QObject 存活时把信号参数原样转发给指定方法
- [[gui.dialogs.lifecycle.alive_signal_emitter]] — 创建不持有窗口强引用的安全 Qt 信号发射回调
- [[gui.dialogs.lifecycle.configure_independent_secondary_window]] — 将受代码托管的二级窗口配置为可独立切换的非模态顶层窗口
- [[gui.dialogs.lifecycle.fit_secondary_window_to_owner_screen]] — 把二级窗口尺寸和位置限制在主窗口所在屏幕的可用区域内
- [[gui.dialogs.lifecycle.is_qobject_alive]] — （无 docstring）
- [[gui.dialogs.lifecycle.safe_disconnect]] — （无 docstring）
- [[gui.dialogs.lifecycle.wait_for_thread_later]] — 后台等待线程结束，并在真正结束前持续保留 Qt 包装对象
- [[gui.dialogs.lifecycle.wait_for_threads_later]] — 异步等待一组 QThread；单次超时不会释放仍在运行的对象

