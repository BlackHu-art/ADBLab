---
kind: class
---

# ToolbarController

- 模块：[[gui.main_frame_toolbar]]
- 全名：gui.main_frame_toolbar.ToolbarController

> 组合进 MainFrame 的顶部工具栏控制器，通过 ``self._frame`` 访问主窗口

## 方法

- [[gui.main_frame_toolbar.ToolbarController.__init__]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._create_toolbar]] — 创建包含功能入口、主题切换和窗口控制的顶部工具栏
- [[gui.main_frame_toolbar.ToolbarController._create_toolbar_action]] — 创建业务入口唯一持有的 QAction
- [[gui.main_frame_toolbar.ToolbarController._create_toolbar_action_button]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._create_toolbar_btn]] — 创建带图标和提示文本的扁平工具栏按钮
- [[gui.main_frame_toolbar.ToolbarController._sync_toolbar_action_button]] — 把 QAction 的展示状态投射到兼容 QToolButton
- [[gui.main_frame_toolbar.ToolbarController._set_toolbar_action_state]] — 优先写 canonical QAction，并兼容只构造旧按钮的轻量调用方
- [[gui.main_frame_toolbar.ToolbarController._setup_shortcuts]] — 注册不占用 Remote 启停组合键的主窗口快捷操作
- [[gui.main_frame_toolbar.ToolbarController._refresh_toolbar_metrics]] — 按当前界面字体更新工具栏高度和图标按钮点击区域
- [[gui.main_frame_toolbar.ToolbarController._toggle_theme]] — 记录工具栏主题切换请求并交给主题服务执行
- [[gui.main_frame_toolbar.ToolbarController._minimize_window]] — 记录工具栏最小化动作
- [[gui.main_frame_toolbar.ToolbarController._toggle_maximize_restore]] — 切换最大化状态，并同步窗口控制按钮的图标和说明
- [[gui.main_frame_toolbar.ToolbarController._refresh_maximize_button]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._request_application_close]] — 记录工具栏退出动作，实际资源清理由 closeEvent 接管
- [[gui.main_frame_toolbar.ToolbarController._refresh_toolbar_icons]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._sync_save_path_action]] — 让默认按钮公开当前完整保存路径
- [[gui.main_frame_toolbar.ToolbarController._refresh_save_path]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._update_toolbar_path_display]] — 按工具栏扣除其余控件后的真实剩余宽度省略保存路径
- [[gui.main_frame_toolbar.ToolbarController._on_save_path_clicked]] — （无 docstring）
- [[gui.main_frame_toolbar.ToolbarController._is_toolbar_drag_target]] — （无 docstring）

