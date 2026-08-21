---
kind: class
---

# BasePanel

- 模块：[[gui.panels.base_panel]]
- 全名：gui.panels.base_panel.BasePanel

> 所有标签页的抽象基类。通过 `panel` 属性访问 SidePanel 的共享状态

## 方法

- [[gui.panels.base_panel.BasePanel.__init__]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel.signals]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel.selected_devices]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel.current_package]] — 当前选中的包名（来自 AppPanel 的 program_edit）
- [[gui.panels.base_panel.BasePanel._font_sm]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._font_mono]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._font_base]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._font_tab]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._sh]] — 为当前选中设备发出 Shell 命令请求
- [[gui.panels.base_panel.BasePanel._g]] — 创建统一样式的 QGroupBox
- [[gui.panels.base_panel.BasePanel._label]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._status_text]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._checkbox]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._set_button_help]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._b]] — 创建图标按钮；variant 可指定默认、强调或危险样式
- [[gui.panels.base_panel.BasePanel._db]] — 创建只在双击时触发的图标按钮
- [[gui.panels.base_panel.BasePanel._qb]] — 创建纯文本按钮；variant 可指定默认、强调或危险样式
- [[gui.panels.base_panel.BasePanel._apply_button_variant]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._refresh_button_style]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._set_button_enabled]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._row]] — 创建紧凑的水平控件行
- [[gui.panels.base_panel.BasePanel._add_row]] — 创建水平控件行并追加到已有的垂直或分组布局
- [[gui.panels.base_panel.BasePanel._add_responsive_row]] — 在真实视觉树中创建一行 binding，并注册到面板级协调器
- [[gui.panels.base_panel.BasePanel._refresh_responsive_widget_minimum]] — 按控件当前字体刷新由响应布局托管的稳定最小宽度
- [[gui.panels.base_panel.BasePanel.refresh_responsive_metrics]] — 字体变化后刷新所有自动下限，不直接发起新的布局代次
- [[gui.panels.base_panel.BasePanel.responsive_geometry_is_applied]] — 返回所有响应行的已应用计划是否覆盖当前真实几何与样式上下文
- [[gui.panels.base_panel.BasePanel._responsive_mode_name]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._responsive_modes]] — 从兼容列数声明生成按真实度量选择的严格候选序列
- [[gui.panels.base_panel.BasePanel._responsive_policy]] — 按控件语义选择稳定宽度来源，不读取用户当前输入文本
- [[gui.panels.base_panel.BasePanel._responsive_context]] — 返回 viewport 内该行的真实可用宽度、受限状态和样式代次
- [[gui.panels.base_panel.BasePanel._responsive_horizontal_insets]] — 从父布局内容矩形累加稳定边距，不把行自身限宽后的空白算作边距
- [[gui.panels.base_panel.BasePanel.activate_responsive_bindings]] — 在内容进入 QScrollArea 视觉树后只请求一次初始规划
- [[gui.panels.base_panel.BasePanel._request_responsive_reflow]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel.apply_responsive_width]] — 保留旧宽度门面；实际规划只读取行容器的真实 contentsRect
- [[gui.panels.base_panel.BasePanel._atomic_form_pair]] — 把真实标签与 buddy 字段放进不可拆分的水平语义单元
- [[gui.panels.base_panel.BasePanel._in]] — 创建统一样式的输入框
- [[gui.panels.base_panel.BasePanel._in_int]] — 创建带业务范围约束的整数输入框
- [[gui.panels.base_panel.BasePanel._in_float]] — 创建带业务范围约束的浮点输入框
- [[gui.panels.base_panel.BasePanel._input_widget]] — （无 docstring）
- [[gui.panels.base_panel.BasePanel._link_form_labels]] — 把行内标签与紧随其后的输入控件关联，并补全可访问名称
- [[gui.panels.base_panel.BasePanel._validate_fields]] — 统一验证必填字段和 Qt validator，失败时不进入业务信号层
- [[gui.panels.base_panel.BasePanel._set_combo_int_validator]] — 为可编辑整数下拉框安装范围 validator
- [[gui.panels.base_panel.BasePanel._combo]] — 创建统一样式的下拉框
- [[gui.panels.base_panel.BasePanel._combo_editable]] — 创建样式一致的可编辑下拉框

