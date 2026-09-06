# 文本与屏幕工具迁移验收

本轮只移动原控件，未创建第二套按钮/处理器，未执行真实设备动作，未写用户设置。

- 应用入口更名为“应用与诊断”，图标 CODE；媒体入口更名为“截图与屏幕”，图标 CAMERA。
- AppPanel 保留设备动作、输入、时长、截图忙碌及录屏批次状态。截图页借用原工具，清除截图时归还 AppPanel 所有的隐藏 QWidget，再进入复用原控件。
- 嵌入时隐藏重复的工具标题；归还时恢复原 headerView 显隐态。全局主题和字体仍经 SidePanel 视觉根更新。
- 只对借用工具的截图页调整 heightForWidth，画布采用 160 逻辑像素最小阅读区并占剩余空间。原独立截图查看器保持原高度契约。
- 工具换行只改变内部 viewport 时刷新适应窗口倍率；仅在 active、未 disposed 且适应模式下排队。手动缩放不被覆盖，清除后停止计时器。

## 测试证据

- 修改前：`test_screenshot_page.py + test_flat_feature_navigation.py + test_workspace_consolidation.py`，50 passed，65.53s，进程退出 0，见 baseline.log。
- 迁移后关联：上述三个文件 + 两个 MainFrame screenshot_batch 节点 + 截图忙碌及发现失败保留停止两个 model_panels 节点，58 passed，96.95s，进程退出 0，见 associated.log。
- 画布 fit 回归：先用固定页面大小下只增大工具高度的真实 Qt 用例复现旧倍率，`test_borrowed_screen_tools_keep_fit_current_and_preserve_manual_zoom` 修前失败，见 fit-before.log。
- 最终标题去重/HFW/fit 后：`pytest -q tests/test_screenshot_page.py tests/test_flat_feature_navigation.py -k 'screenshot or screen_tools'`，18 passed / 26 deselected，18.32s，进程退出 0，见 final-validation.log。
- 9 个修改 Python 文件 Ruff 通过；5 个生产文件 Pyright 0 errors；中文注释检查通过；使用仓库当前 Git 换行配置的 `git diff --check -- <9 files>` 退出 0。
- 未运行全量；主任务执行合并后的共享生命周期关联集成。

## 最终实际 MainFrame 预览

renderer 使用内存设置、模拟控制器、合成 PNG、Windows 中文字体和真实翻译器；CommandRunner 被阻断，无 ADB。

| 场景 | 工具区高 | 画布高 | 纵向 / 横向滚动范围 | 图像 |
| --- | ---: | ---: | --- | --- |
| 中文浅色 1360×900 / 12pt | 94 | 492 | 0 / 0 | screen-tools-light-1360x900-font12-zh_CN.png |
| 中文深色 860×800 / 22pt | 126 | 218 | 0 / 0 | screen-tools-dark-860x800-font22-zh_CN.png |
| 英文浅色 1100×800 / 12pt / 125% DPI | 94 | 392 | 0 / 0 | screen-tools-light-1100x800-font12-en_US.png |

三张最终截图均已实际查看；工具按钮与底栏同屏、不重叠且文字完整。对应 JSON、日志和 render_screen_tools.py 位于本目录，三个渲染进程均退出 0。

额外 500px 宽 / 22pt 真中文字体探针在标题去重前显示：新增工具最小宽 175，但已有截图底栏组最小宽 491，宿主提供 107px 横向滚动。所有按钮仍可通过宿主滚动到达。该非主验收尺寸的“无横滚”探针失败保留在 render-small.log；本轮没有扩大改动既有底栏分组，也不把此探针记作通过。

## 修改范围

生产：gui/panels/app_panel.py、gui/panels/side_panel.py、gui/features/media.py；gui/main_frame.py 仅媒体工厂、导航、相关页面标题/说明及截图完成提示；gui/pages/fluent_pages.py 仅首页应用快捷卡。

测试：tests/test_flat_feature_navigation.py、tests/test_workspace_consolidation.py、tests/test_screenshot_page.py；tests/test_main_window_layout.py 仅截图完成提示文案断言。

全部原有未提交修改保留。翻译及长期文档由主任务维护，本代理没有修改这些文件。
