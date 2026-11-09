# 代码事实与文档清理计划 — 2026-11-08

用户授权对照真实实现优化文档、移除无效内部代码；保持运行行为和现有未提交资产。
本轮不改依赖、CI、资源、用户数据、公开兼容入口或版本，不提交、不推送。

## 已确认的修改边界

- [x] `gui/panels/remote_panel_form.py`：删除没有调用者的 `_group_title`、`_window_toggle`、
  `_icon_button`，及仅由失效标题 helper 写入的 `_group_titles` 和空刷新循环。
- [x] `gui/panels/remote_panel_controls.py`：删除唯一构造点随失效 helper 移除的
  `RemoteWindowToggle` 和其专用导入；保留在用的 `_toggle_buttons`、`ToolButton` 与开关实现。
- [x] `gui/features/media/ui.py`：删除普通协作者上未使用的 `_theme_color` 包装。
- [x] 文档：模块地图、概览补当前任务/持续会话/共享阅读器入口；依赖地图补启动 IPC 和平台
  scrcpy 输出边界；文档入口与维护约定纳入项目记忆，只引用根规则，不复制授权条款。

## 删除依据与保留项

候选已核查生产、测试、导出、字符串与反射、Qt 回调、spec 和资源清单。
当前标题使用 `RemoteSection`；窗口开关使用 `_switch` → `RemoteSwitchButton`；
按键/手势使用 `_command_button`；截图主题直接使用 BaseStyles 与 Fluent。
没有为删除静态无引用代码而删测试；保留 TaskRow 单元格、Controller MRO 动态分派、
设置迁移及 model worker 兼容入口，这些都有消费者或有效回归。

## 验证与完成

- [x] 清理前运行 Remote compact/toggle 和 screenshot page/workspace layout 四个测试文件，
  再做最小删除并复跑同一组，确认主题、字号、键盘与布局行为保持。
- [x] 三个修改生产文件 Ruff、Pyright、中文注释检查；文档链接/frontmatter、`git diff --check`。
- [x] 独立审阅本轮差异；将实际结果和边界写入新增项目记忆，并更新索引。

不写仅断言私有名称消失的测试；不把依赖当前脏工作树的旧验收数字当成本轮结果。

## 实际结果

生产代码仅删除 45 行；另将风险账本中失效的硬编码 Qt 版本改为引用当前依赖，保留 Partial
状态，未认定安全升级或产物验收完成。清理前后 offscreen 均为 81 passed / 3 failed，Cocoa
对应三节点均为 1 passed / 2 failed，失败节点集合一致；没有修改断言、跳过测试或新增失败。
Ruff、Pyright（0 errors）、中文注释及文档检查通过。失败证据和后续定位边界详见
[本轮记忆](../../memory/2026-11-08/documentation-code-cleanup-memory-2026-11-08.md)。
