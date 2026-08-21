---
kind: class
---

# CloseController

- 模块：[[gui.close_controller]]
- 全名：gui.close_controller.CloseController

> 组合进 MainFrame 的关闭控制器，通过 ``self._frame`` 访问主窗口

## 方法

- [[gui.close_controller.CloseController.__init__]] — （无 docstring）
- [[gui.close_controller.CloseController.handle_close_event]] — 启动异步关闭，只在资源停止和最终状态落盘完成后接受事件
- [[gui.close_controller.CloseController._register_application_shutdown_tasks]] — 按扫描、面板、对话框和 Controller 顺序注册应用级关闭资源
- [[gui.close_controller.CloseController._prepare_ui_for_shutdown]] — 先停止界面定时器并断开生产者信号，再广播资源停止请求
- [[gui.close_controller.CloseController._on_application_stopped]] — 汇总资源停止结果，再启动配置和日志收尾任务
- [[gui.close_controller.CloseController._flush_shutdown_state]] — 在后台原子保存待写配置；日志服务已在 GUI 线程提前关闭
- [[gui.close_controller.CloseController._on_application_finalized]] — 记录收尾结果并重新触发关闭事件，使 Qt 最终销毁窗口

