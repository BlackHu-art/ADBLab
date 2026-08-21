---
kind: class
---

# DeviceManagerLayout

- 模块：[[gui.panels.device_manager_layout]]
- 全名：gui.panels.device_manager_layout.DeviceManagerLayout

> 组合进 DeviceManager 的布局控制器，通过 ``self._frame`` 访问面板

## 方法

- [[gui.panels.device_manager_layout.DeviceManagerLayout.__init__]] — （无 docstring）
- [[gui.panels.device_manager_layout.DeviceManagerLayout.apply_responsive_width]] — 兼容旧入口；实际宽度始终由 Devices 视觉根在规划轮次中读取
- [[gui.panels.device_manager_layout.DeviceManagerLayout._responsive_context]] — 提供 SidePanel 状态；binding 会用视觉根真实几何和字体覆盖本地字段
- [[gui.panels.device_manager_layout.DeviceManagerLayout._action_viewport_width]] — 优先读取真实动作 frame，首次换态时使用单调的保守估算
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_horizontal_insets]] — 返回 Devices 根到动作 viewport 之间不参与内容分配的横向占位
- [[gui.panels.device_manager_layout.DeviceManagerLayout._build_device_plan]] — 从视觉根和动作 viewport 的真实度量生成单一 Devices 计划
- [[gui.panels.device_manager_layout.DeviceManagerLayout._apply_device_plan]] — 按复合计划同步移动连接、列表、滚动区和既有动作按钮
- [[gui.panels.device_manager_layout.DeviceManagerLayout._finish_device_plan]] — 在动作网格应用后同步等宽约束、最小高度和弹窗宽度
- [[gui.panels.device_manager_layout.DeviceManagerLayout.device_list_minimum_height]] — 返回当前内容下可完整显示一行设备所需的列表高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._empty_device_row_height]] — 通过当前字体和样式估算带复选框设备项的一行完整高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_list_reserves_horizontal_scrollbar]] — 除明确禁用外，预留横向滚动条高度，避免内容出现时顶开 splitter
- [[gui.panels.device_manager_layout.DeviceManagerLayout._update_device_minimum_heights]] — 向祖先传播一行列表和全部动作行的真实安全高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_action_minimum_height]] — 返回完整显示动作网格全部行所需的真实高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_body_minimum_height]] — 返回当前主体形态完整显示列表和动作区所需高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_stacked_height_limit]] — 按当前样式度量计算主体能够安全堆叠的精确高度边界
- [[gui.panels.device_manager_layout.DeviceManagerLayout._sync_device_control_heights]] — 按当前字体统一连接区和设备动作控件的最小高度
- [[gui.panels.device_manager_layout.DeviceManagerLayout._device_layout_limits]] — 按 Qt 控件最小宽度和实际容器 inset 计算三态切换断点
- [[gui.panels.device_manager_layout.DeviceManagerLayout._sync_address_popup_width]] — 让设备地址下拉表格和补全弹窗保持与输入框相同的当前宽度

