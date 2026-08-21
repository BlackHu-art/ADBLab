---
kind: function
---

# isolated_ui_state(qt_application, isolated_ui_state_probe)

- 定义于：[[tests.conftest]]
- 全名：tests.conftest.isolated_ui_state

> 恢复每个用例改动过的全局 UI 状态并清理其顶层窗口

## 调用

- [[gui.styles.fonts.FontMixin._sync_legacy_values]]
- [[gui.styles.fonts.FontMixin.current_font_config]]
- [[gui.styles.theme.ThemeMixin.current_theme]]
- [[gui.styles.theme.ThemeMixin.switch_theme]]
- [[gui.styles.typography.TypographyManager.apply]]

