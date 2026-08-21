---
kind: class
---

# StrictIntSpinBox

- 模块：[[gui.widgets.preset_spin_box]]
- 全名：gui.widgets.preset_spin_box.StrictIntSpinBox

> 只接受指定范围内 ASCII 十进制文本的整数输入框

## 方法

- [[gui.widgets.preset_spin_box.StrictIntSpinBox.__init__]] — （无 docstring）
- [[gui.widgets.preset_spin_box.StrictIntSpinBox._parse_acceptable]] — 解析完全合法的 ASCII 十进制文本，非法时返回 ``None``
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.validate]] — 按严格词法返回 Qt 校验状态，同时保留可继续编辑的中间态
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.valueFromText]] — 仅转换完全合法的文本；非法文本保持当前业务值
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.textFromValue]] — 使用不受本地分组规则影响的 ASCII 十进制格式
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.input_is_acceptable]] — 返回编辑器当前原文是否可作为业务整数提交
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.commit_value]] — 提交当前合法原文；非法时保留原文和旧业务值
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.focus_editor]] — 把键盘焦点交给内部文本编辑器
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.setValue]] — 设置业务值，并在同值调用时也清除非法编辑状态
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.keyPressEvent]] — 在 Enter 提交前执行严格校验，阻止 Qt 自动纠正非法原文
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.focusOutEvent]] — 失焦时提交合法文本，非法文本保持可见且维持无效状态
- [[gui.widgets.preset_spin_box.StrictIntSpinBox.eventFilter]] — 在内部编辑器失焦前提交，覆盖 Tab 和鼠标切换焦点路径
- [[gui.widgets.preset_spin_box.StrictIntSpinBox._on_editor_text_changed]] — （无 docstring）
- [[gui.widgets.preset_spin_box.StrictIntSpinBox._set_input_validity]] — （无 docstring）

