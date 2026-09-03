# 第三方代码与许可说明

## PyQt-Fluent-Widgets / PySide6-Fluent-Widgets

ADBLab 的 Fluent UI 直接依赖 `PySide6-Fluent-Widgets`，并根据开发时使用的
PyQt-Fluent-Widgets 参考检出（提交 `356665d9db87090db43305b98ac6cde2071d8f4d`）中的下列
Gallery 示例改写了页面组织：

- `examples/gallery/app/view/home_interface.py`
- `examples/gallery/app/view/gallery_interface.py`
- `examples/gallery/app/view/setting_interface.py`
- `examples/gallery/app/components/sample_card.py`
- `examples/navigation/segmented_widget/demo.py`

对应的 ADBLab 改写集中在 `gui/pages/fluent_pages.py`，包括 Banner、固定页面标题区、
FlowLayout 操作卡片、SegmentedWidget 工作台、颜色选择卡和 SettingCard 设置页；业务动作、
设备上下文、设置存储和 PySide6 信号接线为 ADBLab 适配实现。运行时不会从本地
`reference/` 目录导入代码，该目录也不是源码检出的必需部分。

上游项目采用 GNU General Public License v3.0，并提供商业许可选项。完整许可文本见
[该上游提交的 LICENSE](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/356665d9db87090db43305b98ac6cde2071d8f4d/LICENSE)。
当前工程约束为内部使用、不对外分发；如需分发应用或其构建产物，必须先完成 GPL-3.0
合规开源或取得上游商业许可。
