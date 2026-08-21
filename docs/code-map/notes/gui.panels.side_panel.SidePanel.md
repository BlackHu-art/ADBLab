---
kind: class
---

# SidePanel

- 模块：[[gui.panels.side_panel]]
- 全名：gui.panels.side_panel.SidePanel

> 创建并管理功能标签页，同时保持 MainFrame 使用的兼容接口

## 方法

- [[gui.panels.side_panel.SidePanel.__init__]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._create_fonts]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._create_ui]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._create_tab_scroll_area]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._ensure_tab_loaded]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.eventFilter]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._connect_lazy_tab_signals]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._refresh_tab_action_states]] — 刷新一个功能页公开的动作可用状态
- [[gui.panels.side_panel.SidePanel._refresh_loaded_action_states]] — 设备选择变化时同步刷新所有已加载功能页
- [[gui.panels.side_panel.SidePanel.selected_devices]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.ip_address]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.device_widget]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.update_device_list]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.set_device_discovery_state]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.set_restricted_width_mode]] — 受限工作区允许右侧页签缩小，并由滚动条保证内容可达
- [[gui.panels.side_panel.SidePanel.request_responsive_reflow]] — 把所有设备布局事件合并到本面板唯一的响应式协调器
- [[gui.panels.side_panel.SidePanel._poll_responsive_settled]] — 在协调器真实收口后，为测试和诊断发布一次稳定代次
- [[gui.panels.side_panel.SidePanel.refresh_device_choices]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.apply_device_theme]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.apply_responsive_widths]] — 刷新分栏布局；功能页始终以各自 viewport 实际宽度为准
- [[gui.panels.side_panel.SidePanel.current_package_text]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.update_current_package]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.on_recording_finished]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.on_recording_target_finished]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.on_monkey_target_finished]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.on_operation_completed]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel.refresh_from_settings]] — 只通知已加载且声明了设置刷新钩子的功能页
- [[gui.panels.side_panel.SidePanel.shutdown]] — 依次关闭已加载标签页拥有的后台资源
- [[gui.panels.side_panel.SidePanel.register_shutdown_tasks]] — 将已加载标签页的异步关闭任务注册到统一监督器
- [[gui.panels.side_panel.SidePanel._apply_tab_style]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._apply_completer_style]] — 为 Devices/Apps 标签页的 QCompleter 弹窗应用样式
- [[gui.panels.side_panel.SidePanel._on_theme_changed]] — （无 docstring）
- [[gui.panels.side_panel.SidePanel._on_fonts_changed]] — 字体配置变化时更新已创建控件，不借用主题刷新路径
- [[gui.panels.side_panel.SidePanel._connect_all_signals]] — 委托各标签页连接各自的信号

