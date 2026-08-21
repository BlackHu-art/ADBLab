---
kind: class
---

# TypographyManager

- 模块：[[gui.styles.typography]]
- 全名：gui.styles.typography.TypographyManager

> 维护应用唯一字体配置，并按实际变化发送细粒度信号

## 方法

- [[gui.styles.typography.TypographyManager.__init__]] — （无 docstring）
- [[gui.styles.typography.TypographyManager.config]] — 返回当前不可变字体配置
- [[gui.styles.typography.TypographyManager.apply]] — 应用配置到 QApplication，并仅为发生变化的字体角色发送信号
- [[gui.styles.typography.TypographyManager.apply_application_font]] — 把界面字体设为 QApplication 默认字体，使未单独设置的控件自动继承
- [[gui.styles.typography.TypographyManager.font_for_role]] — 按角色创建字体，调用方可为少量特殊场景覆盖字号
- [[gui.styles.typography.TypographyManager.control_height]] — 根据字体度量返回不会裁切文字的最小控件高度

