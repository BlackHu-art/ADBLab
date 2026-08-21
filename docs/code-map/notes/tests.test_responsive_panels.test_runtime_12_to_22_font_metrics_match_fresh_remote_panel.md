---
kind: function
---

# test_runtime_12_to_22_font_metrics_match_fresh_remote_panel(qt_application, monkeypatch)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_runtime_12_to_22_font_metrics_match_fresh_remote_panel

> 真实字体配置从 12 切到 22 后，同一实例应与 22 号新实例采用相同计划

## 调用

- [[gui.styles.fonts.FontMixin._sync_legacy_values]]
- [[gui.styles.fonts.FontMixin.current_font_config]]
- [[gui.styles.typography.TypographyManager.apply]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[gui.styles.typography.FontConfig]]

