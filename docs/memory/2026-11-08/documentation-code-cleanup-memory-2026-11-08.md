# 文档与失效内部代码清理 — 2026-11-08

## 本轮结果

用户授权对照真实代码优化文档、移除无效代码。生产清理涉及此前没有本地差异的 3 个文件，
校准 6 份现状/入口文档；另追加本记录和执行计划、更新记忆索引。保持现有任务中心、持续
会话、PTY、依赖升级及其他未提交资产；没有提交或推送。
删除前核查了运行入口、继承/Qt 回调、字符串分派、导出、测试、spec 与资源清单。

| 删除内容 | 当前替代入口与保留理由 |
| --- | --- |
| RemotePanelForm 的 `_group_title`、`_group_titles` 及其空刷新循环 | 标题已由 RemoteSection 构建和刷新；旧列表只能由没有调用者的 helper 写入 |
| RemotePanelForm 的 `_window_toggle`、唯一构造类 RemoteWindowToggle 及专用导入 | 当前窗口设置走 `_switch` → RemoteSwitchButton；诊断按钮仍使用 `_toggle_buttons`，该列表保留 |
| RemotePanelForm 的 `_icon_button` | 现有按键和手势统一经 `_command_button`；ToolButton 仍参与样式类型判断，导入保留 |
| ScreenshotViewerUI 的 `_theme_color` | 普通 Python 协作者上无调用/动态代理的包装；实际主题处理直接使用 BaseStyles 与 Fluent |

共删除 45 行，文件为 [Remote 表单](../../../gui/panels/remote_panel_form.py)、
[Remote 控件](../../../gui/panels/remote_panel_controls.py)、[截图 UI](../../../gui/features/media/ui.py)。
没有重构布局或信号，没有为私有名称删除新增镜像断言测试，也没有删除有效测试。

文档更新：

- [模块地图](../../project-knowledge/MODULE_MAP.md) 和[概览](../../project-knowledge/PROJECT_OVERVIEW.md)
  补齐持续会话、主窗共享单任务阅读器和导航投影；细节继续指向操作结果指南。
- [依赖地图](../../project-knowledge/DEPENDENCY_MAP.md) 补内部启动显示入口与本机 IPC、
  POSIX stdout PTY / Windows PIPE 边界及就绪判定，避免误把内部入口当死代码。
- [知识库入口](../../README.md) 与[文档约定](../../CONTRIBUTING_DOCS.md) 纳入 memory 分区，
  自动维护仍以根 AGENTS.md 为单一来源。
- [风险账本](../../project-knowledge/RISKS_AND_DEBT.md) 不再把旧 Qt 版本写成当前依赖；
  改为引用 requirements.txt，并保留升级兼容/产物/安全验收的 Partial 状态，没有关闭风险。

## 必须保留的疑似候选

TaskRow、标题和省略标签仍被真实 TableWidget 的单元格使用；不能删除。
设置迁移包装、model worker 同对象入口有兼容回归；Controller 的处理器由 MRO 表和 getattr
动态绑定；`_fail_install_operation` 还覆盖旧 generation 竞态，均保留。
没有消费者的公开 API 尚不能证明契约退役，本轮没有删除。

## 实际验证

本机运行时为 PySide6 / Qt 6.9.1；requirements.txt、constraints.txt 的升级差异在本轮前已
存在，没有修改。历史记忆里的 6.8.1.1 是日期快照，不代表当前环境。

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_remote_compact_form.py tests/test_remote_toggle_layout.py \
  tests/test_screenshot_page.py tests/test_screenshot_workspace_layout.py
```

清理前后均为 **81 passed / 3 failed**，失败节点集合完全一致：

- `test_remote_actions_show_native_hover_and_focus_without_changing_geometry[Light]`
- `test_remote_actions_show_native_hover_and_focus_without_changing_geometry[Dark]`
- `test_screenshot_flip_view_preserves_mixed_image_aspect_ratios`

前两项为原有 `underMouse()` 命中断言失败，第三项为像素宽高比误差 3px 超过 2px。
对这三个节点在删除前后分别用 `QT_QPA_PLATFORM=cocoa` 复核，均为 **1 passed / 2 failed**：
截图比例节点通过，两项悬停节点仍失败。没有放宽断言、跳过测试或将这些结果表述为整组通过；
测试根因尚未完整定位，当前证据仅说明没有本轮新增失败，不能据此断言实际产品存在相同问题。

三个生产文件的 Ruff、Pyright（0 errors）、中文注释检查，以及文档链接/frontmatter、
`git diff --check` 通过。独立只读复核未发现误删或文档事实越界。
未触及启动、打包或持久化边界，没有运行全量 pytest、打包自检、PyInstaller 或设备操作。
后续若处理悬停和离屏比例失败，应从上述原节点复现，不应删除有效回归或用旧验收数字替代。

执行边界与删除证据见[本轮计划](../../superpowers/plans/2026-11-08-code-documentation-cleanup.md)，
后续接续仍先读 [AGENTS.md](../../../AGENTS.md) 和[项目记忆索引](../README.md)。
