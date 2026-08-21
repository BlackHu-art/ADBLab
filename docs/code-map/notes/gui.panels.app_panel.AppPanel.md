---
kind: class
---

# AppPanel

- 模块：[[gui.panels.app_panel]]
- 全名：gui.panels.app_panel.AppPanel

> 集中构建应用管理控件，并通过 SidePanelSignals 转发用户操作

## 方法

- [[gui.panels.app_panel.AppPanel.build_ui]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._load_monkey_params]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.reload_from_settings]] — 幂等重载 Monkey 设置，供恢复默认值后的协调层调用
- [[gui.panels.app_panel.AppPanel._collect_monkey_params]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._update_pct_total]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._on_record_start]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._on_record_stop]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.on_recording_target_finished]] — 仅消费当前批次中尚未完成的设备终态
- [[gui.panels.app_panel.AppPanel.on_recording_finished]] — 保留旧接口名称；无批次信息的终态不会改变当前任务
- [[gui.panels.app_panel.AppPanel.on_operation_completed]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._on_screenshot]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._set_screenshot_running]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._on_start_monkey]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.on_monkey_target_finished]] — 按批次和设备去重 Monkey 终态，忽略迟到结果
- [[gui.panels.app_panel.AppPanel._on_kill_monkey]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._set_monkey_running]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel._update_action_states]] — 根据设备、包名和任务状态统一更新应用页操作可用性
- [[gui.panels.app_panel.AppPanel._set_action_enabled]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.package_text]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.add_package_to_history]] — （无 docstring）
- [[gui.panels.app_panel.AppPanel.connect_signals]] — 将本页控件连接到统一的 SidePanelSignals
- [[gui.panels.app_panel.AppPanel._submit_text]] — 让按钮和 Return 路径共享同一必填及设备校验

