# 系统字体与自动界面字号实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新安装及恢复默认使用系统界面字体与字号，已有字体、数字字号和日志字号保持。

**Architecture:** 沿用 font_family 空字符串，ui_font_size 扩展为 Auto 或既有 8–22 整数；不增加独立模式键，不根据字体名猜测用户意图。持久化层不依赖 Qt，Typography 负责将 Auto 解析为实际 pt，设置页只读写原始选择。

**Tech Stack:** Python 3.11、PySide6、现有 AppSettings、TypographyManager、Fluent 设置卡与 pytest。

**Spec:** 用户本轮授权：默认跟随系统字体和界面字号，保留已有用户设置，适配 macOS、Windows 与不同显示器。

## 约束与边界

- 保留现有脏工作树，不提交、不推送、不改版本、依赖或 CI。
- ui_font_size 的既有数字保持原值，Auto 不写回为解析出的数字；日志继续独立 9pt 默认与 7–16 手动范围。
- 自动字号保留有效小数 pt，在应用支持范围 8–22 内解析；Qt 无法提供有效系统字号时回退 12pt。
- 不用 DPR 乘字号。像素制系统字体通过 Qt 字体信息解析为 pt，窗口跨屏沿用既有屏幕约束和响应式重排。
- 配置接口返回原始 int/Auto，实际控件从字体管理器取得解析字号；字体角色、Fluent 字体族同步和设置防抖生命周期不变。

## 分工与验收

- [x] 配置与资源：DEFAULTS、规范化、兼容属性及种子支持 Auto；隔离路径验证新装、旧数字/字体保留、重置、持久化往返及异常值。
- [x] 字体解析：读取 Qt GeneralFont 的族和 pointSizeF，像素字体由 QFontInfo 解析；QFont.setPointSizeF 保留分数，兼容旧字体工厂；覆盖未初始化、非法字体信息、信号、手动往返。
- [x] 设置页与词库：新增“跟随系统”字号选项，保存 Auto，已有数字显示和批量保存保持；重置回填 Auto；保留已有关于页改动并同步三语言资源。
- [x] 显示适配：macOS/Windows 字体样本、Qt 缩放子进程与跨屏重排回归，验证 pt 不随 DPR 重复倍增；仅根任务使用 Cocoa，子任务使用独立离屏或纯设置测试。
- [x] 整合：直接与关联字体/设置/屏幕节点，修改文件 Ruff、相关生产模块 Pyright、中文注释、文档检查、源码 packaging self-check；独立审阅后记录实际结果与实机边界。

## 风险核对

- 系统字号不能从已覆盖的 QApplication 字体反向读取，避免 Auto 继承上一次手动字号。
- 不因默认变更改写已存在的字体名或数字；无此字段的旧文件使用当前默认，已有明确值保持。
- 不把系统返回的 pixelSize 当作 pt，也不把显示缩放与系统字号乘两次。
- 自动/手动切换后标题、次级说明、导航、菜单、输出与窄屏动作可达；小数 pt 不被兼容工厂截断。
- 未运行的 Windows 实机及真实双屏切换不能表述为通过；不将本轮范围扩展到此前已验收的整个脏工作树。


## 实施结果与验证

- 保留现有字体名及数字字号；默认与恢复默认使用系统字体和 Auto。系统 pt 在启动或重新应用字体设置时解析，运行期间没有新增操作系统字体变化监听。
- 性能页的字体回退缓存改为保留小数 pt，避免 12pt → 12.5pt 时漏刷。
- Cocoa 实窗首次滚入字体分组时曾出现标题/说明重叠。原生诊断确认正文被加入 59/130/201px 底部安全区边距，网格高度变成负数；正文局部取消重复安全区约束后，13pt/12.5pt 及关于页二维码展开回归通过。
- 独立只读审阅覆盖全部字号消费者、原值保留及 DPR 路径，未发现需修复的问题。

本轮使用项目 `.venv/bin/python` 运行以下增量检查：

| 命令或范围 | 结果 |
| --- | --- |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_typography_core.py tests/test_settings_schema.py tests/test_settings_persistence.py tests/test_system_font_display.py` | 161 passed |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_feature_typography.py tests/test_typography_core.py tests/test_system_font_display.py` | 41 passed；与上一组部分重叠 |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_settings_typography.py tests/test_settings_reflow_efficiency.py tests/test_settings_expand_animation.py -k 'not scroll_margins'` | 140 passed，2 deselected；原生背景节点单独在 Cocoa 运行 |
| Cocoa：设置背景、恢复默认、屏幕绑定和窗口首次绑定节点 | 5 passed |
| Cocoa：`test_home_first_paint_uses_final_navigation_and_card_geometry -k Auto` | 4 passed，10 deselected |
| Cocoa：`test_auto_font_settings_cards_keep_title_and_description_separate_after_scroll` | 2 passed；包含关于卡片和二维码展开 |
| 离屏：词库真实文案、嵌入资源一致性和可见 UI 字面量节点 | 9 passed |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --self-check packaging` | 源码资源与运行工具检查通过 |
| 本轮 Python 文件 Ruff、受影响生产模块 Pyright、生产注释检查、文档链接/frontmatter、`git diff --check` | 通过；Pyright 0 errors |

Qt 缩放测试包含 100%、125%、150%、200%，使用 macOS/Windows 系统字体样本与当前主机已安装字体绘制；屏幕切换测试使用受控屏幕适配器。已完成 macOS 原生实窗预览，未执行 Windows 实机或真实双显示器切换，也未构建 PyInstaller 产物。未触发全量测试条件，未运行整个脏工作树的全量验收。
