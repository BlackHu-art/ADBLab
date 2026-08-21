---
kind: file
---

# tests.test_responsive_panels

> 验证 Apps、System 和 Remote 面板在断点切换时仅重排现有控件

- 路径：tests/test_responsive_panels.py

## 函数

- [[tests.test_responsive_panels._assert_device_list_endpoints]] — 验证长设备行纵向完整，且横向滚动首尾与 viewport 对齐
- [[tests.test_responsive_panels._assert_feature_binding_geometry]] — 核对当前 viewport 下所有响应行的几何，并返回真实溢出 binding
- [[tests.test_responsive_panels._assert_near]] — 允许 Qt 栅格在高 DPI 下出现一像素的舍入差
- [[tests.test_responsive_panels._binding_widget_state]] — 冻结所有 binding 直接控件的身份、业务状态和非几何属性
- [[tests.test_responsive_panels._close_device_test_ui]] — 按 popup、detached 根、无父级控制器和 SidePanel 的顺序清理测试对象
- [[tests.test_responsive_panels._close_feature_panel]] — 停止 Remote 资源并回收本测试创建的真实 SidePanel
- [[tests.test_responsive_panels._device_boundary_oracle]] — 仅从测试侧 Qt 度量推导 Devices 三态断点，不读取生产断点实现
- [[tests.test_responsive_panels._fast_responsive_debounce]] — 逐像素几何扫描无需真实防抖等待，缩短到 1ms 以压缩套件耗时
- [[tests.test_responsive_panels._grid_item_position]] — 读取控件在网格中的行、列及跨行列数
- [[tests.test_responsive_panels._grid_position]] — 读取控件在网格中的行列位置
- [[tests.test_responsive_panels._resize_binding_until_mode]] — 测试侧逐像素扫描真实 viewport，不调用生产布局决策 helper
- [[tests.test_responsive_panels._resize_feature_viewport]] — 只经宿主尺寸变化调整真实 viewport，并等待页面计划覆盖最终 Qt 几何
- [[tests.test_responsive_panels._set_scroll_viewport_width]] — 仅调整真实顶层宽度，直到滚动 viewport 达到请求的逻辑宽度
- [[tests.test_responsive_panels._show_device_geometry]] — 直接请求 Devices 根尺寸，等待新代次稳定并拒绝 Qt 静默夹紧
- [[tests.test_responsive_panels._show_device_height]] — 直接请求设备根高度，等待新代次稳定并拒绝 Qt 静默夹紧
- [[tests.test_responsive_panels._show_device_layout]] — 按 Qt 实际视觉根宽度请求一代重排，并等待协调器与子控件几何稳定
- [[tests.test_responsive_panels._show_feature_panel]] — 创建真实 SidePanel、懒加载页和滚动内容，返回实际 viewport 几何
- [[tests.test_responsive_panels._side_panel]] — 构造面板布局测试需要的最小 SidePanel 接口
- [[tests.test_responsive_panels._styled_device_row_height]] — 使用 Qt 样式系统计算带复选框设备项的一行完整高度
- [[tests.test_responsive_panels._validator_signature]] — 把字段 validator 的类型、身份和业务范围冻结为与布局无关的状态
- [[tests.test_responsive_panels._visible_device_layout_members]] — 返回 Devices 视觉根内需要互不覆盖的显式布局成员
- [[tests.test_responsive_panels.test_adaptive_layout_spacing_converges_at_boundaries_in_both_directions]] — 跨临界值正反拖动必须得到同一离散序列，不得因方向产生往返振荡
- [[tests.test_responsive_panels.test_adaptive_layout_spacing_uses_font_aware_discrete_slack_bands]] — 真实最小需求之外的逐缝余量只能映射到稳定的 2/4/6px 档位
- [[tests.test_responsive_panels.test_app_panel_actions_follow_device_and_package_context]] — （无 docstring）
- [[tests.test_responsive_panels.test_apps_real_reflow_preserves_all_binding_state_batches_and_one_signal]] — Apps 真实窄宽往返保持全部绑定控件、validator 与录屏/Monkey 批次
- [[tests.test_responsive_panels.test_compact_device_address_remains_full_width_and_editable_below_240px]] — 极窄视觉根仍保持地址整行，不能被 Connect 的自然宽度挤压为零
- [[tests.test_responsive_panels.test_device_actions_stay_directly_visible_and_long_ip_is_layout_neutral]] — 长 IPv6 不参与断点，动作按钮仍在直接宿主内完整显示
- [[tests.test_responsive_panels.test_device_address_popups_follow_the_shrinkable_input_width]] — 长 IPv6 地址不得撑宽父布局，两个地址弹窗必须随输入框同步收缩
- [[tests.test_responsive_panels.test_device_body_height_boundary_switches_both_directions_without_fallback]] — 高度往返不得改变由宽度决定的 Devices 宿主或动作列
- [[tests.test_responsive_panels.test_device_list_and_last_action_keep_bottom_inset_in_every_body_mode]] — 设备列表和最后一个动作不得随主体模式切换而贴住分组底边
- [[tests.test_responsive_panels.test_device_list_minimum_keeps_a_long_row_visible_after_content_changes]] — 设备项无论先于还是晚于收缩出现，最小高度都必须容纳行和横向滚动条
- [[tests.test_responsive_panels.test_device_manager_keeps_connection_and_device_columns_aligned_after_show]] — 连接区必须在三态中复用设备主体的实际列宽，而不是只复用排列方向
- [[tests.test_responsive_panels.test_device_manager_recalculates_equal_control_heights_for_current_font]] — 地址、Connect 和所有设备动作按钮必须使用同一实际高度
- [[tests.test_responsive_panels.test_device_reflow_preserves_objects_state_and_single_signal_delivery]] — 窄→宽→窄只移动既有控件，不改业务状态且点击仅发出一次信号
- [[tests.test_responsive_panels.test_device_wide_action_rows_keep_declared_gap_and_leave_extra_height_below]] — 宽布局的多余高度不得被 QGridLayout 摊成逐渐变大的按钮间隙
- [[tests.test_responsive_panels.test_device_wide_layout_keeps_connect_visually_separate_from_refresh]] — 连接区与动作区不得在宽布局中以零像素间距黏在一起
- [[tests.test_responsive_panels.test_device_width_scan_only_reflows_for_fitting_columns_or_spacing]] — 正反扫描只采用可容纳的列/间距，且高度变化不改变水平计划
- [[tests.test_responsive_panels.test_devices_real_geometry_never_overlaps_at_restricted_height]] — 四档字号的真实最小高度必须容纳列表和全部动作按钮
- [[tests.test_responsive_panels.test_empty_device_list_minimum_reserves_a_styled_row_and_possible_scrollbar]] — 空列表在最小高度也必须预留完整设备行和未来可能出现的横向滚动条
- [[tests.test_responsive_panels.test_feature_binding_breakpoint_is_stable_at_b_minus_one_b_and_b_plus_one]] — 测试侧有限扫描所得动态边界在 B−1/B/B+1 使用 Qt 最终 viewport 收敛
- [[tests.test_responsive_panels.test_feature_panel_geometry_is_stable_in_light_and_dark_themes]] — 两种主题和常规/最大字号下都由同一语义计划保持有效几何
- [[tests.test_responsive_panels.test_feature_panel_real_geometry_and_scroll_contract]] — 四档字号/292px 下每行使用真实 binding，内容正尺寸且横向溢出可达
- [[tests.test_responsive_panels.test_feature_theme_and_font_events_each_create_one_generation]] — 已加载功能页的主题与字体刷新各合并为单一 coordinator generation
- [[tests.test_responsive_panels.test_grid_plan_fingerprint_includes_spacing]] — 同一响应行只有 spacing 改变时，计划指纹也必须随之改变
- [[tests.test_responsive_panels.test_large_font_static_semantic_labels_are_not_clipped_after_runtime_change]] — 静态参数标签必须按当前字体保留完整文本宽度
- [[tests.test_responsive_panels.test_lazy_feature_rows_share_one_coordinator_and_register_once]] — 懒加载页的每行只注册一次，并统一消费 SidePanel coordinator
- [[tests.test_responsive_panels.test_medium_connect_width_is_independent_of_body_height_and_fallback]] — medium 的 Connect 宽度和宿主只能由宽度计划决定
- [[tests.test_responsive_panels.test_monkey_parameter_and_percentage_pairs_survive_reflow]] — Monkey 参数、九组比例和独立单位/Total 在各模式中保持语义归属
- [[tests.test_responsive_panels.test_package_manager_two_column_tail_spans_full_row]] — Package Manager 的三动作行在 two 模式让尾动作横跨整行
- [[tests.test_responsive_panels.test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once]] — 排队重排中关闭 Remote 时，binding 注销且 worker/executor 只清理一次
- [[tests.test_responsive_panels.test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback]] — 真实顶层缩放只开启一代，内部 viewport 反馈不得排队形成额外代次
- [[tests.test_responsive_panels.test_remote_control_real_viewport_scan_observes_only_four_and_two_columns]] — Remote 三组控制只由真实 applied plan 与 Qt 网格证明可达的四列/两列
- [[tests.test_responsive_panels.test_remote_key_and_action_each_submit_once_after_real_reflow]] — 真实 Remote 按钮连接在往返重排后仍保持一次点击一次 executor 提交
- [[tests.test_responsive_panels.test_remote_overflow_row_constraints_clear_when_viewport_grows]] — 溢出行恢复为可容纳状态时，行宽约束和共享滚动范围必须同步清除
- [[tests.test_responsive_panels.test_remote_reflow_preserves_session_values_identity_and_single_action]] — Remote 292→900→292 只移动既有控件，不改变完整配置与会话状态
- [[tests.test_responsive_panels.test_replaced_address_completer_syncs_its_popup_without_a_resize]] — 历史地址刷新后，直接显示的新补全弹窗仍必须等宽于稳定的输入框
- [[tests.test_responsive_panels.test_responsive_binding_does_not_rewrite_an_identical_grid_plan]] — Applying an identical plan twice must not detach and re-add every widget
- [[tests.test_responsive_panels.test_responsive_spacing_tracks_viewport_without_replacing_widgets]] — BasePanel 行在窄/宽/窄往返中改变间距，但控件身份和业务状态保持
- [[tests.test_responsive_panels.test_runtime_12_to_22_font_metrics_match_fresh_remote_panel]] — 真实字体配置从 12 切到 22 后，同一实例应与 22 号新实例采用相同计划
- [[tests.test_responsive_panels.test_runtime_font_change_refreshes_responsive_auto_minimums]] — 运行时切换字号后，响应项下限必须与当前字体重新度量
- [[tests.test_responsive_panels.test_shrinkable_package_field_ignores_dynamic_text_width]] — 动态包名不得进入 SHRINKABLE 字段的自然宽度或布局指纹
- [[tests.test_responsive_panels.test_side_panel_routes_splitter_width_changes_only_through_coordinator]] — （无 docstring）
- [[tests.test_responsive_panels.test_side_panel_supervised_remote_close_cleans_active_resources_once]] — 排队重排中经 SidePanel 与 supervisor 关闭 Remote，每类资源只清理一次
- [[tests.test_responsive_panels.test_side_panel_width_callback_preserves_device_column_mode_when_only_height_changes]] — SidePanel 宽度回调应生效，控件仅改变高度时不能改写已计算的列宽状态
- [[tests.test_responsive_panels.test_stacked_connect_width_scan_uses_only_supported_geometry]] — 扫描真实可用宽度，验证 stacked 连接区不依赖生产断点常量
- [[tests.test_responsive_panels.test_system_label_field_pair_never_splits_in_narrow_mode]] — System 的 Battery 标签与参数字段在窄模式仍位于同一语义行
- [[tests.test_responsive_panels.test_system_real_reflow_preserves_all_binding_state_validators_and_one_signal]] — System 真实窄宽往返保持字段、动态 validator、原子组及一次业务信号

