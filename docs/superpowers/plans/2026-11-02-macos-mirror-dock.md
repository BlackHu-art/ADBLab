# macOS 投屏侧栏跟随 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** macOS 镜像移动、缩放、最小化和恢复时侧栏保持正确位置和可见性。
**Architecture:** macOS 平台叶子实现既有 `_WindowApi`，工厂只在 cocoa 后端加载，复用现有会话跟踪与轮询。
**Tech Stack:** Python 3.11、PySide6、现有 PyObjC、Accessibility/AppKit。
**Spec:** [设计](../specs/2026-11-02-macos-mirror-dock-design.md)。

## Global Constraints

保留未提交的间距调整；不新增依赖，不提交或推送；不修改系统权限，不连接真实设备。

## Task 1: 平台与后端

- [x] 在 `tests/test_window_tracking_platform.py` 增加 cocoa 成功与授权缺失降级用例，先确认失败。
- [x] 新增 `tests/test_macos_window_tracking.py`，覆盖后代进程/精确标题、移动缩放/最小化隐藏、超时、关闭、Retina/副屏坐标与仅定位自有工具窗。
- [x] 实现 `services/remote/windowing/macos.py::MacOSWindowApi` 并接入 `create_window_tracker`；模块导入不打开原生资源。
- [x] 运行直接测试及既有 Windows/X11 跟踪测试，确认平台隔离。

## Task 2: 原生集成与现状文档

- [x] 新增显式 cocoa 的独立合成窗口集成用例，验证侧栏移动、缩放、最小化/恢复、窗口退出和资源清理。
- [x] 运行侧栏、便携降级和模块导入关联测试；运行改动文件 Ruff/Pyright、中文注释与文档检查。
- [x] 更新架构、业务流程和构建文档中的 macOS 能力及辅助功能授权要求。
- [x] 独立只读评审最终改动，并记录验证结果。

## Review Focus

辅助功能未授权、目标无响应、同名无关进程、跨屏比例转换、关闭后的晚到更新均需明确覆盖。

## 实施与证据

- cocoa 工厂原先返回不支持，新平台用例先失败后通过。
- 审阅发现 AX timeout 只作用于当前引用；真实合成镜像阻塞 1 秒时旧查询耗时约 0.98 秒，
  已改为应用与每个窗口引用分别检查 25ms timeout，并补真实阻塞恢复回归。
- 审阅以两个合成应用确认原位置激活镜像不会刷新侧栏层级；先复现失败，再把 macOS 前台身份
  纳入 Dock 定位缓存。Windows/Linux 的前台变化不新增定位调用。
- 隐藏场景使用 macOS 的应用隐藏与恢复；Qt `QWidget.hide()` 会使该合成窗口的 AX 身份失效，
  不能用它模拟保持原窗口身份的 Cmd+H。窗口关闭仍立即终止绑定，不重新选择同名窗口。
- 最终独立只读复核无剩余阻断问题。未连接真实设备，未做物理多屏和全屏 Spaces 验收。
- 源码 packaging self-check 的依赖/翻译/图像均通过，仍缺已有的 `resource:scrcpy-adb-bridge`；
  本次不构建辅助程序或执行正式打包。

## 最终验证

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_remote_dock.py tests/test_remote_toolbar_portable.py tests/test_remote_windowing_imports.py tests/test_macos_window_tracking.py tests/test_window_tracking_platform.py tests/test_remote_window_tracking.py --tb=short
# 108 passed, 1 skipped（Windows 原生窗口测试的平台前提）
QT_QPA_PLATFORM=cocoa QT_SCALE_FACTOR=1 .venv/bin/python -m pytest -q tests/test_remote_dock_macos_native.py --tb=short
# 5 passed，使用当前 macOS 桌面和独立合成进程，无真实设备
```

修改的 Python 文件 Ruff、三个生产模块 Pyright、中文注释检查通过；文档链接/frontmatter 和
`git diff --check` 通过。本轮未触发全量 pytest，不重复验证此前已完成的顶部间距修改。

## 后续内置工具与真实会话复验

用户批准预研方案后，补齐官方 scrcpy 4.1 的 macOS 两架构工具清单，CLI/CI 使用 onedir `.app`，
并修复 `Contents/MacOS` 与 `Contents/Frameworks` 分离时被误判为 onefile 的缓存边界。
Mac 工具包含 ADB、scrcpy、server、许可证、图标和手册；复用现有摘要、安全解压和资源收集。

- 打包直接测试 108 项通过、3 项 Linux 专用测试按平台跳过；CI 关联测试 13 项通过。
- 本机 arm64 实际构建 `ADBLab-macos-arm64-dev.app`，架构、嵌套 codesign、系统动态依赖检查通过。
- 清除外部 ADB/scrcpy/SDK 路径并限制 PATH 后，冻结 packaging、worker help 和 UTF-8 探针通过。
  最小 cocoa GUI 启动退出通过；ZIP 的 CRC 和内置 ADB/scrcpy 文件检查通过。
- 真实会话只读取宿主窗口元数据，并执行一次可恢复的宿主窗口位移；侧栏同步移动且位置恢复。
  用户随后确认新启动的源码镜像已经正常跟随。未发送设备按键，也未读取设备画面。
- 另使用官方 SDL 3.4.12 的独立测试窗复验程序位移及鼠标标题栏拖动，窗口绑定和侧栏跟随正常。
  SDL 仅作临时验证工具，测试完成已卸载只读磁盘映像，未增加生产依赖。
- 两次独立只读审阅均无剩余阻断问题。Intel 产物交由对应 CI runner 实构建，未在本机验收；
  未提交、推送或发布，也未改变应用版本。
