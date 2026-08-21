---
kind: file
---

# tests.test_performance_responsive

> 验证 Performance 单界面、严格输入和运行状态契约

- 路径：tests/test_performance_responsive.py

## 类

- [[tests.test_performance_responsive._RunnerProbe]] — 记录启动边界收到的配置，不模拟外部进程

## 函数

- [[tests.test_performance_responsive._build_performance_dialog]] — （无 docstring）
- [[tests.test_performance_responsive._editor]] — （无 docstring）
- [[tests.test_performance_responsive.test_direct_action_buttons_share_canonical_actions]] — 直接按钮保留 QAction 状态同步，且每次点击只调用一次业务入口
- [[tests.test_performance_responsive.test_disabled_invalid_monkey_value_does_not_block_and_survives_reenable]] — 关闭 Monkey 后非法子项不阻止启动，也不清除用户原文
- [[tests.test_performance_responsive.test_late_package_callbacks_do_not_mutate_or_unlock_running_configuration]] — 启动后的晚到包名结果不得改写本次运行配置
- [[tests.test_performance_responsive.test_monkey_total_ignores_disabled_invalid_then_restores_invalid_state]] — 禁用 Monkey 只忽略非法值，重新启用后仍恢复原文和错误状态
- [[tests.test_performance_responsive.test_original_dropdown_remains_keyboard_reachable_without_extra_button]] — 数字预设使用原版下拉箭头，并支持键盘直接展开
- [[tests.test_performance_responsive.test_performance_displays_full_group_without_scroll_and_uses_short_log]] — 配置直接完整显示，日志保持较低高度且页面不产生滚动区域
- [[tests.test_performance_responsive.test_performance_numeric_aliases_use_original_dropdown_style_with_strict_values]] — 分页前数字下拉框保留严格整数接口，且不出现上下微调按钮
- [[tests.test_performance_responsive.test_performance_preserves_original_single_group_visual_structure]] — 扩展功能仍沿用最初版的单分组表单，不引入仪表盘卡片
- [[tests.test_performance_responsive.test_performance_restores_visible_previous_version_hints]] — 旧版关键提示不能只藏在 tooltip 中，单界面必须直接展示
- [[tests.test_performance_responsive.test_performance_uses_one_persistent_configuration_group_without_tabs_or_more]] — 窗口缩放不得再切换 compact/wide 宿主或生成无效下拉入口
- [[tests.test_performance_responsive.test_result_availability_updates_canonical_action]] — 结果可用状态由 canonical QAction 发布，并同步到直接按钮
- [[tests.test_performance_responsive.test_running_locks_only_configuration_and_keeps_log_and_actions_available]] — 运行锁只覆盖配置叶区，日志、状态和停止入口保持可用
- [[tests.test_performance_responsive.test_single_layout_preserves_focus_identity_and_signal_count]] — 尺寸往返不得重建输入控件、丢失原文或重复连接信号
- [[tests.test_performance_responsive.test_start_checks_all_enabled_fields_before_committing_any_value]] — 后续字段失败时不得留下前面字段的半提交配置
- [[tests.test_performance_responsive.test_start_commits_focused_valid_number_before_building_config]] — 焦点字段的有效原文必须在 Start 边界统一提交

