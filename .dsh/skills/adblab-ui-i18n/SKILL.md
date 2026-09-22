---
name: adblab-ui-i18n
description: >-
  ADBLab 的界面约定与翻译流水线：PySide6/qfluentwidgets 的主线程与 worker 模式、
  dispose/关闭屏障、主题与字体角色、资源与用户数据路径，以及修改 tr() 文案后必须完成的
  .ts → .qm → translations_rc.py 三步再生成与相关测试。Use when editing GUI code, adding a card
  or dialog, changing user-facing text, or adding a settings entry in this repo.
whenToUse: 改动 ADBLab 界面、控件、主题字体、用户可见文案或设置项时。
---

# ADBLab 界面与翻译

## 控件与线程

- 只在 GUI 主线程操作控件；耗时 I/O、ADB、进程等待放后台，结果经信号回槽。
- 沿用现有模式：`QThread`/`QThreadPool` + worker、`TaskSupervisor`/`QtTaskSupervisor`、
  `ProcessRunner`；不要新造并行体系。
- 后台线程不得直接改 UI，也不要在 `QThread`/`QRunnable` 里 `emit` 后继续持有控件引用。
- 释放：页面提供 `request_dispose()` 与 `dispose_ready`；关闭时等待线程、进程、reader、
  QTimer 归零，晚到回调必须被代次或 `isValid` 拒绝。
- 提示只用可操作信息：纯消息走 `gui/notifications.py` 的窗口内 InfoBar（非阻塞），
  输入与文件选择才用瞬态窗口（`gui/dialogs/fluent_dialog.py`）。

## qfluentwidgets 查询顺序

1. 本仓库现有代码与测试；
2. 活动解释器里实际安装的版本（`importlib.util.find_spec("qfluentwidgets")` 后用 rg 定位单个文件）；
3. 上游官方 **PySide6 分支** 的单个文件。

不要用上游默认 PyQt5 分支判断本项目 API；不要克隆或全量扫描上游仓库。`reference/` 是本地参考副本，
不是运行或打包来源。

## 主题、字体与资源

- 字体状态源是 `gui/styles/typography.py::TypographyManager`（角色 `UI/UI_SMALL/MONO/LOG/TITLE`），
  主题与强调色由 `gui/styles/theme.py::BaseStyles` 协调；不要自建第二套字体/颜色来源。
- 卡片文案变化后必须重排（沿用 `reflow`/`SettingsCardPresentation` 模式），否则高度会截断。
- 路径：资源用 `utils/resource_path.py`，用户数据用 `utils/user_data.py`，
  onefile 工具缓存用 `utils/runtime_tools.py`；不要假设源码目录或安装目录可写。

## 翻译三步（改任何 tr() 文案都要做）

先在三语言 `.ts` 的 `ADBLab` context 中更新非空译文，再生成 `.qm` 和
`gui/generated/translations_rc.py`。执行命令以
[构建指南](../../../docs/guides/BUILD_AND_RUN.md)为单一来源；资源必须显式使用 zlib，
避免当前 Windows Qt 无法解压生成器默认使用的 Zstd 资源。

- `tests/test_i18n.py` 要求 `.ts` 每条非空且与 `.qm` 一致，并检查 `gui/` 内每个 `tr()` 字面量都有词条；
  改完必须跑它（以及 `test_application_languages.py`、`test_dialog_languages.py`）。
- 显示文案与稳定业务值必须分离：状态/类型等在数据里保存原文（如 `Enabled`/`User`），
  只在绘制与提示时本地化。
- 新增设置项：键写进 `core/settings_manager.py` 的 `DEFAULTS`，沿用当前 schema 版本，
  不要在未授权时升版本或做迁移。

## 视觉验证

布局、DPI、焦点、空/忙碌/错误态、重复点击都要检查；无法自动断言的视觉项给出人工检查步骤。
相关 Qt 测试见 `tests/test_main_window_layout.py`、`test_settings_typography.py`、
`test_responsive_panels.py`、`test_page_layout.py` 等。
