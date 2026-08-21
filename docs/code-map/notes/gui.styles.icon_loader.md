---
kind: file
---

# gui.styles.icon_loader

> 提供跟随主题变化的 SVG 图标加载器

- 路径：gui/styles/icon_loader.py

## 类

- [[gui.styles.icon_loader._ThemedIconEngine]] — 每次 paint() 时渲染 SVG，并注入当前主题颜色

## 函数

- [[gui.styles.icon_loader._load_svg]] — （无 docstring）
- [[gui.styles.icon_loader.clear_svg_cache]] — 清空 SVG 文件缓存，供磁盘图标更新后调用
- [[gui.styles.icon_loader.get_themed_icon]] — 返回始终使用当前主题颜色绘制的 QIcon

