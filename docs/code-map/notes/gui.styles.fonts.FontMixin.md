---
kind: class
---

# FontMixin

- 模块：[[gui.styles.fonts]]
- 全名：gui.styles.fonts.FontMixin

> 通过 BaseStyles 暴露字体角色、变更信号和旧版字体工厂

## 方法

- [[gui.styles.fonts.FontMixin.reload_from_settings]] — 读取、校验并应用持久化字体设置，不触发主题变更信号
- [[gui.styles.fonts.FontMixin._sync_legacy_values]] — 同步旧属性与 QSS 映射，保证存量模块继续使用同一份配置
- [[gui.styles.fonts.FontMixin.current_font_config]] — 返回当前不可变字体配置
- [[gui.styles.fonts.FontMixin.font_for_role]] — 按统一字体角色创建 QFont
- [[gui.styles.fonts.FontMixin.control_height]] — 返回适配当前字体的安全控件高度
- [[gui.styles.fonts.FontMixin.get_default_font]] — 创建界面字体；保留对旧版可写类属性的兼容
- [[gui.styles.fonts.FontMixin.get_log_font]] — 创建日志等宽字体；保留旧版方法名称

