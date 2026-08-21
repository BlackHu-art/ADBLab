---
kind: file
---

# gui.styles.theme

> 提供 ADBLab 主题颜色、变化信号和主题切换能力

- 路径：gui/styles/theme.py

## 类

- [[gui.styles.theme.ThemeMixin]] — 通过 BaseStyles 提供主题切换和颜色访问能力
- [[gui.styles.theme.ThemeSignal]] — 发布主题变化信号

## 函数

- [[gui.styles.theme._tc]] — 读取当前主题颜色，缺失时依次回退到浅色主题和黑色
- [[gui.styles.theme.apply_dark_title_bar]] — 使 Windows 标题栏与当前深色或浅色主题一致

