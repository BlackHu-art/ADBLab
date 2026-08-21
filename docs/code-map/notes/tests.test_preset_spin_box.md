---
kind: file
---

# tests.test_preset_spin_box

> 验证严格整数输入与预设菜单控件

- 路径：tests/test_preset_spin_box.py

## 函数

- [[tests.test_preset_spin_box._region_contains_contrasting_pixel]] — 返回真实渲染区域中是否存在与按钮背景明显不同的像素
- [[tests.test_preset_spin_box._render_spin_subcontrols]] — 按实际 QSS 渲染 spinbox，并返回上下按钮区域
- [[tests.test_preset_spin_box.test_empty_presets_omit_button_and_nonempty_presets_are_immutable]] — 空菜单按钮和可变预设集合会产生无效焦点或运行期配置漂移
- [[tests.test_preset_spin_box.test_focus_out_commits_acceptable_text_once]] — 只处理键盘提交会在鼠标切换焦点时遗失合法新值
- [[tests.test_preset_spin_box.test_focused_valid_text_commits_once_before_value_read]] — 遗漏显式提交会让仍聚焦的新文本被旧业务值覆盖
- [[tests.test_preset_spin_box.test_invalid_enter_and_focus_out_preserve_raw_text_and_old_value]] — Qt 自动纠正非法文本会把旧值伪装成用户已提交的新值
- [[tests.test_preset_spin_box.test_non_integer_preset_is_rejected_at_construction]] — 接受浮点、字符串或布尔值会让菜单文案与业务整数语义不一致
- [[tests.test_preset_spin_box.test_out_of_range_preset_is_rejected_at_construction]] — 越界 QAction 若延迟到点击时处理会把无效配置带入业务层
- [[tests.test_preset_spin_box.test_preset_button_is_keyboard_reachable_and_action_commits_once]] — 预设按钮缺少键盘入口或重复绑定会破坏无障碍和单次提交契约
- [[tests.test_preset_spin_box.test_real_keyboard_commit_emits_value_once]] — 重复解释 Enter 或 Tab 会让一次编辑触发两次业务刷新
- [[tests.test_preset_spin_box.test_set_value_including_same_value_clears_invalid_and_normalizes_text]] — 同值 setValue 若提前返回会留下非法原文和错误样式
- [[tests.test_preset_spin_box.test_spin_arrows_render_and_disabled_buttons_have_visible_state]] — 缺少箭头子控件样式会渲染空白，按钮规则也不能覆盖禁用状态
- [[tests.test_preset_spin_box.test_strict_spin_rejects_noncanonical_or_out_of_range_text]] — 放宽严格词法会让分组符、Unicode 数字或越界值进入业务配置
- [[tests.test_preset_spin_box.test_strict_spin_style_covers_focus_invalid_disabled_and_scoped_button]] — 遗漏状态或使用裸 QToolButton 选择器会造成主题不可见和全局样式污染
- [[tests.test_preset_spin_box.test_strict_spin_validator_and_parser_share_ascii_decimal_rule]] — 校验器与提交解析分叉会造成界面可输入但无法提交的状态
- [[tests.test_preset_spin_box.test_widget_locales_do_not_change_global_locale_or_accept_grouping]] — 控件不得通过修改全局 QLocale 来实现无分组格式
- [[tests.test_preset_spin_box.test_wrapper_forwards_validity_and_exposes_editor_focus]] — 不转发有效性或焦点会让表单无法阻止启动并定位错误字段

