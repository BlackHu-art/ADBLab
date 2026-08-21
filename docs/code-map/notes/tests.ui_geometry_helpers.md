---
kind: file
---

# tests.ui_geometry_helpers

> 面向真实 Qt 控件的几何、可见性和文本断言

- 路径：tests/ui_geometry_helpers.py

## 函数

- [[tests.ui_geometry_helpers._geometry_snapshot]] — （无 docstring）
- [[tests.ui_geometry_helpers._process_events]] — （无 docstring）
- [[tests.ui_geometry_helpers.assert_contained]] — 断言控件完整位于祖先可用矩形内
- [[tests.ui_geometry_helpers.assert_elided_accessible_text]] — 文本发生省略时，断言完整文本可通过辅助信息获得
- [[tests.ui_geometry_helpers.assert_non_overlapping]] — 断言同一祖先中的控件矩形没有相交
- [[tests.ui_geometry_helpers.assert_positive_geometry]] — 断言控件在其自身或祖先坐标中有正面积
- [[tests.ui_geometry_helpers.assert_scroll_target_reachable]] — 断言普通目标可完整显示，超宽目标的左右边缘均可到达
- [[tests.ui_geometry_helpers.assert_square]] — 断言控件具有相等的宽高
- [[tests.ui_geometry_helpers.assert_text_fits]] — 断言单行可见文本可在控件内容宽度内完整显示
- [[tests.ui_geometry_helpers.mapped_rect]] — 返回控件映射到指定祖先坐标系后的实际矩形
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]] — 等待至少两次连续的控件几何快照一致
- [[tests.ui_geometry_helpers.wait_until]] — 在明确 deadline 内让 Qt 事件循环推进至条件成立

