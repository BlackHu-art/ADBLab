# 远控和截图库清理复验 — 2026-11-09

[11 月 8 日的清理记录](../2026-11-08/documentation-code-cleanup-memory-2026-11-08.md)
留下三个失败节点。此次从已推送的任务中心提交 `38f91cc5` 核对剩余改动，确认远控表单与截图库
的四组旧辅助代码没有调用者、动态分派或 Qt 回调。现用入口与删除依据见上述记录。

- 亮色、暗色下的悬停失败来自测试把独立遥控器的按键当作主页面按钮。现在分别显示所属窗口，
  在对应滚动区定位按钮，核验命中、悬停像素、键盘焦点与按压前后的几何。测试入口为
  [远控交互测试](../../../tests/test_remote_toggle_layout.py)。
- 离屏截图库把 720×240 横图量成 720×241。上下边缘恰好各覆盖半个像素，旧测量只看 RGB，
  忽略了透明度。现在用实际颜色覆盖计算宽高，沿用原图比例和视口尺寸断言。测试入口为
  [截图库测试](../../../tests/test_screenshot_page.py)。
- Cocoa 组合复验还发现，页头收起时根布局的临时空矩形会导致高度误判，画布尺寸连续相同也可能
  早于缩放标签重排。测试改为从页面实际可用高度核算画布，并等待叠加层重排完成后检查贴边和碰撞。
- [依赖地图](../../project-knowledge/DEPENDENCY_MAP.md) 已核对 GUI 与资源自检、
  启动画面 IPC 和 scrcpy 预检。[模块地图](../../project-knowledge/MODULE_MAP.md)
  记录持续会话的停止资格与实例校验。Qt 分发与跨平台兼容性继续由
  [风险账本](../../project-knowledge/RISKS_AND_DEBT.md) 跟踪。

## 复验结果

在 macOS 上对 `test_remote_compact_form.py`、`test_remote_toggle_layout.py`、
`test_screenshot_page.py`、`test_screenshot_workspace_layout.py` 运行同一组 pytest。
最终版本在 Cocoa 和 offscreen 下各通过 86 项。截图比例节点另以 125% 离屏缩放单独通过。
三个清理文件通过 Pyright 与中文注释检查，五个变更的 Python 文件通过 Ruff。
本轮验证范围是远控和截图库的现有 UI 行为及项目文档。
