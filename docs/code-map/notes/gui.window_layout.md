---
kind: file
---

# gui.window_layout

> 集中处理主窗口尺寸和左右分栏比例的校验与换算

- 路径：gui/window_layout.py

## 类

- [[gui.window_layout.WorkspaceConstraints]] — 保留用户首选尺寸，并描述当前屏幕实际可采用的窗口约束

## 函数

- [[gui.window_layout._coerce_int]] — （无 docstring）
- [[gui.window_layout.compute_workspace_constraints]] — 计算当前屏幕的有效尺寸，不把临时裁剪写回用户首选尺寸
- [[gui.window_layout.minimum_window_size_for_available]] — 在受限工作区中把窗口最小值降到屏幕真实可用尺寸
- [[gui.window_layout.normalize_panel_ratio]] — 返回安全的左栏比例，异常值回退到默认比例
- [[gui.window_layout.normalize_window_size]] — 把配置尺寸限制在最小值和当前屏幕可用范围内
- [[gui.window_layout.ratio_from_sizes]] — 根据分栏实际宽度计算并校验左栏比例
- [[gui.window_layout.split_sizes_for_constraints]] — 按比例拆分宽度，并以当前两个面板的真实最小宽度为边界
- [[gui.window_layout.split_sizes_for_ratio]] — 按比例拆分可用宽度并保证两个结果均为非负整数

