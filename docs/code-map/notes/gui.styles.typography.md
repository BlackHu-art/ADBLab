---
kind: file
---

# gui.styles.typography

> 提供应用级字体配置、字体角色和变更通知

- 路径：gui/styles/typography.py

## 类

- [[gui.styles.typography.FontConfig]] — 保存已经校验并解析为可用字体族的字体配置
- [[gui.styles.typography.FontRole]] — 定义应用内稳定的字体用途，避免各窗口自行拼装字号和字体族
- [[gui.styles.typography.TypographyManager]] — 维护应用唯一字体配置，并按实际变化发送细粒度信号

## 函数

- [[gui.styles.typography._available_families]] — 返回以不区分大小写名称索引的已安装字体
- [[gui.styles.typography._safe_size]] — 将外部字号转换到安全范围，无法解析时回退到默认值
- [[gui.styles.typography._system_font_family]] — 读取 Qt 系统字体；无图形应用或字体信息缺失时使用平台回退值
- [[gui.styles.typography.font_config_from_mapping]] — 从设置映射创建不可变且经过边界校验的字体配置
- [[gui.styles.typography.font_for_config]] — 根据不可变配置和字体角色创建 QFont
- [[gui.styles.typography.resolve_ui_font_family]] — 解析用户字体设置，不可用或系统默认设置均回退到 Qt 系统字体
- [[gui.styles.typography.system_mono_font_family]] — 返回当前系统建议的等宽字体族
- [[gui.styles.typography.system_ui_font_family]] — 返回当前系统建议的界面字体族

