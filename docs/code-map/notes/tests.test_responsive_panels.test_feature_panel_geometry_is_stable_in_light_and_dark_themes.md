---
kind: function
---

# test_feature_panel_geometry_is_stable_in_light_and_dark_themes(qt_application, monkeypatch, panel_name, font_size, theme)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_feature_panel_geometry_is_stable_in_light_and_dark_themes

> 两种主题和常规/最大字号下都由同一语义计划保持有效几何

## 调用

- [[gui.styles.theme.ThemeMixin.switch_theme]]
- [[gui.widgets.responsive_binding.ResponsiveGridBinding.widgets]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.assert_non_overlapping]]
- [[tests.ui_geometry_helpers.assert_positive_geometry]]
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]]

