---
kind: class
---

# SecondaryWindowHost

- 模块：[[gui.secondary_windows]]
- 全名：gui.secondary_windows.SecondaryWindowHost

> 组合进 MainFrame 的二级窗口托管器，通过 ``self._frame`` 访问主窗口

## 方法

- [[gui.secondary_windows.SecondaryWindowHost.__init__]] — （无 docstring）
- [[gui.secondary_windows.SecondaryWindowHost._show_about_dialog]] — 显示关于对话框
- [[gui.secondary_windows.SecondaryWindowHost._show_app_manager]] — 为每个已选设备打开应用管理窗口
- [[gui.secondary_windows.SecondaryWindowHost._show_file_explorer]] — 为每个已选设备打开文件浏览窗口
- [[gui.secondary_windows.SecondaryWindowHost._show_logcat]] — 为每个已选设备打开实时 Logcat 窗口
- [[gui.secondary_windows.SecondaryWindowHost._show_performance_monitor]] — 打开原生性能采集启动对话框
- [[gui.secondary_windows.SecondaryWindowHost._show_device_dialogs]] — 为选中设备创建由主窗口托管的非模态窗口
- [[gui.secondary_windows.SecondaryWindowHost._register_dialog]] — （无 docstring）
- [[gui.secondary_windows.SecondaryWindowHost._show_fitted_dialog]] — 复用二级窗口前重新限制几何，并将其激活
- [[gui.secondary_windows.SecondaryWindowHost._find_active_dialog]] — （无 docstring）
- [[gui.secondary_windows.SecondaryWindowHost._forget_dialog]] — （无 docstring）
- [[gui.secondary_windows.SecondaryWindowHost._on_dialog_destroyed]] — 移除已销毁窗口并记录二级窗口关闭完成
- [[gui.secondary_windows.SecondaryWindowHost.eventFilter]] — 记录受主窗口托管的二级窗口关闭请求
- [[gui.secondary_windows.SecondaryWindowHost._show_settings]] — 显示或激活非模态的单实例设置窗口
- [[gui.secondary_windows.SecondaryWindowHost._refresh_active_dialog_themes]] — （无 docstring）
- [[gui.secondary_windows.SecondaryWindowHost._refresh_live_settings]] — 让主窗口和已加载页签重新读取可即时生效的设置

