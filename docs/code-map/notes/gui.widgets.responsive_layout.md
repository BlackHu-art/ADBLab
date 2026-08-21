---
kind: file
---

# gui.widgets.responsive_layout

> 提供可测试的响应式网格规划与兼容重排辅助函数

- 路径：gui/widgets/responsive_layout.py

## 类

- [[gui.widgets.responsive_layout.GridMode]] — 候选网格模式；rank 越大越保守
- [[gui.widgets.responsive_layout.GridPlacement]] — 把一个度量项放入网格中的位置
- [[gui.widgets.responsive_layout.GridPlan]] — 对某次上下文和控件度量作出的完整网格决定
- [[gui.widgets.responsive_layout.ItemMetric]] — 一次布局轮次中单个控件的只读宽度度量
- [[gui.widgets.responsive_layout.LayoutContext]] — 一轮规划使用的本地几何、字体与外部样式代次
- [[gui.widgets.responsive_layout.WidthPolicy]] — 描述控件在网格规划中的最小宽度来源

## 函数

- [[gui.widgets.responsive_layout._generated_placements]] — （无 docstring）
- [[gui.widgets.responsive_layout._required_column_widths]] — （无 docstring）
- [[gui.widgets.responsive_layout._validated_mode]] — （无 docstring）
- [[gui.widgets.responsive_layout.adaptive_layout_spacing]] — 把每行的水平余量映射为稳定的 2/4/6 像素间距档位
- [[gui.widgets.responsive_layout.choose_grid_plan]] — 选择能够放入真实可用宽度的最不保守网格模式
- [[gui.widgets.responsive_layout.paired_mode]] — 创建标签与字段相邻的候选模式，每行容纳指定数量的语义组
- [[gui.widgets.responsive_layout.prepare_responsive_content]] — 让滚动页中的按钮可收缩，并允许长说明在窄宽度换行
- [[gui.widgets.responsive_layout.reflow_widgets]] — 在不重建控件和信号连接的前提下重新排列网格控件
- [[gui.widgets.responsive_layout.responsive_column_count]] — 根据逻辑像素宽度和界面字号返回当前布局列数
- [[gui.widgets.responsive_layout.row_major_mode]] — 创建按行顺序放置控件的候选模式
- [[gui.widgets.responsive_layout.span_tail_mode]] — 创建让最后一个不足整行的行占满全部列的候选模式
- [[gui.widgets.responsive_layout.validate_grid_modes]] — 验证候选严格按宽到窄排列，且 rank 从零逐级递增

