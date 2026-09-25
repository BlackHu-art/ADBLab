# 2026-09-25 设备页内连接区验收

本记录对应用户批准的紧凑三页签设计及当时工作树，补充此前无线配对实现的界面迁移验收。
现状以 [BUSINESS_FLOW](../../project-knowledge/BUSINESS_FLOW.md) 为准。

## 实施范围

- `gui/widgets/device_connection.py`：真正的 QWidget 连接区，替代原非模态弹窗；默认隐藏，
  显式展开默认扫码。扫码、配对码、IP 连接按当前宽度与字号共享自然高度，窄窗重排。
- `gui/pages/device_hub.py`、`gui/main_frame.py`：连接区位于原工具栏和设备列表之间；保留摘要、
  刷新和卡片，常显“断开”并沿用当前已选设备语义。IP 历史只填入，显式提交才连接。
- `gui/close_controller.py`：保留先清理视图秘密、再交由协调器停止资源的关闭顺序。
- 收起和离页立即清除二维码/配对码并取消，清理屏障未完成前不得重启；隐藏回调不确认二维码。
- 同步三语言资源及架构、业务、数据流和模块索引。原弹窗有效行为测试迁到页内入口，原模块移除。

独立审查发现并关闭两项问题：隐藏页不完整参与测量造成切页高度变化，以及收起期间清理失败后
重新展开显示旧准备文案。补充了大字号英文/繁体换行、停止后晚到二维码和隐藏表单提交回归。

## 验证环境与命令

按既有授权使用本地 Python 3.11，测试工具与 Segno 从隔离的临时目录提供；未创建根目录 `.venv`
或改变系统依赖。Qt 使用 `QT_QPA_PLATFORM=offscreen`，测试设备、命令结果和存储均隔离。

下列 `python` 均指本轮实际使用的本地 Python 3.11 解释器。

| 命令 / 范围 | 结果 |
| --- | --- |
| `python -m pytest -q tests/test_device_connection.py tests/test_wireless_pairing_layout.py tests/test_wireless_pairing_flow.py tests/test_qt_adb_pairing.py` | 47 passed |
| `python -m pytest -q tests/test_global_device_context.py tests/test_phase2_mainframe_shutdown_gate.py tests/test_device_hub_page.py tests/test_shell_workflows.py tests/test_device_context_bar_presentation.py::test_overview_toolbar_fully_contains_disconnect_and_accepts_real_clicks` | 228 passed |
| `python -m pytest -q tests/test_i18n.py` | 49 passed |
| 最后面板修复后，`python -m pytest -q tests/test_global_device_context.py -k connection_panel` | 8 passed，106 deselected |
| `QT_SCALE_FACTOR=1.5` / `2`，分别运行 `python -m pytest -q tests/test_wireless_pairing_layout.py` | 各 13 passed |
| `python main.py --self-check packaging` | 49 项 OK，源码资源与运行依赖自检 |
| 修改文件的 Ruff；面板、MainFrame、DeviceHub、CloseController 的 Pyright；中文注释检查 | 通过 |
| `python scripts/check_doc_links.py`、`git diff --check` | 通过 |

主要关联测试共 324 个用例通过；缩放与最终入口复测为相同契约的额外执行，不重复计入。
Pyright 提示配置的 `.venv` 不存在，但所选生产模块为 0 errors / 0 warnings；测试输出保留第三方
SciPy/QDom 弃用警告。未因本次界面修改触发项目全量测试。

## 视觉与验证边界

使用真实 MainFrame 和合成设备生成深浅主题、常规与窄窗下的收起、扫码、配对码、IP 连接截图；
三组截图探针通过。几何测试覆盖 12/22 字号、三语言、完整二维码可见确认、续连与滚动可达。
初版探针绕过正常关闭后出现延迟回调污染；在对象存活时显式执行面板关闭准备并排空事件后通过，
未为此改动无关生产模块。

离屏截图只能核对控件布局和主题绘制，不能替代 Windows 原生 DWM 云母效果与实机扫码联调。
本轮未连接真实手机、未重新打包产物，也未提交或推送。验收实机时检查：展开扫码、切页后停止旧轮次、
历史填入后显式连接、快速收起/重开、离开概览取消，以及关闭程序后没有新增进程残留。
