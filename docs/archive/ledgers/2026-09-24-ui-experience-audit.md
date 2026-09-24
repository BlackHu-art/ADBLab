# 2026-09-24 UI 体验检查与修复

本记录对应当时的本地工作树，保留问题依据和验证边界，不替代当前代码或测试。

## 检查范围

扫描 `gui/` 下 111 个 Python 文件，其中 103 个为非生成、非包初始化实现文件。
按主窗口、页面与面板、功能会话、对话框、共用控件、样式及字体模块检查布局约束、列宽、
字号刷新、长文本、窄窗口、选择状态、异步结果、菜单与关闭路径。
重点路径结合真实 Qt 控件和离屏交互复现；源码检查不代表所有原生桌面、DPI 和真实设备组合均已验收。

此前文件/应用列表的手动列宽与窗口填充、应用默认图标视图、复选框禁排序、设备弹层关闭入口
作为已有工作保留，本轮未重新计为新增修复。

## 已修复问题

| 区域 | 确认的问题与修复 | 主要实现 |
| --- | --- | --- |
| 文件列表 | Fluent 委托默认字号不随设置变化；同步实际绘制字体、表头和行高，保留列宽与选择 | [file_explorer_list.py](../../../gui/dialogs/file_explorer_list.py)、[file_explorer.py](../../../gui/dialogs/file_explorer.py) |
| 文件状态栏 | 长路径会撑宽整个页面；按可用宽度省略绘制，完整路径保留在提示和无障碍文本 | [file_explorer.py](../../../gui/dialogs/file_explorer.py) |
| 离线文件缓存 | 整表禁用导致缓存不能滚动；允许阅读缓存，加载/关闭仍禁用表格，所有设备命令继续校验准入 | [file_explorer.py](../../../gui/dialogs/file_explorer.py) |
| 应用权限 | 权限列表绘制字体和行高未随设置更新；原位刷新，保留选择与权限复选状态 | [app_manager_details.py](../../../gui/dialogs/app_manager_details.py) |
| 任务中心 | 复用的任务行字号未更新，英文大字下状态与取消按钮溢出；刷新字体并换行，在途操作入口按宽度省略且保留完整提示和计数 | [tasks_page.py](../../../gui/pages/tasks_page.py) |
| 工作区空状态 | 等待设备、关闭会话页面字号固定；标题、说明与返回按钮同步设置 | [workspace_features.py](../../../gui/pages/workspace_features.py) |
| 操作结果与报告 | 选择框和按钮字号滞后；原位更新，复制/导出及产物打开按钮可换行，保留正文、查找选择与附件目标 | [action_result_view.py](../../../gui/widgets/action_result_view.py)、[report_artifacts.py](../../../gui/widgets/report_artifacts.py) |
| 归档结果筛选 | 两个筛选框的最小宽度撑出窄主窗口；不足时搜索、类型和状态分别占一行 | [run_results.py](../../../gui/widgets/run_results.py) |
| 输入弹窗 | 大字号输入框和按钮仍固定像素高度；按字体及原生最小尺寸调整，保留提交/取消操作 | [fluent_dialog.py](../../../gui/dialogs/fluent_dialog.py) |
| 长截图缩放 | 适应比例低于 5% 时点击缩小会反向放大；缩放下限考虑当前比例与可视区适应比例 | [screenshot_viewer_nav.py](../../../gui/dialogs/screenshot_viewer_nav.py) |
| 瞬态菜单 | 快速关闭/重开后的迟到焦点可导致原生析构崩溃；在菜单延迟删除或宿主销毁前清理列表焦点 | [transient_menu.py](../../../gui/widgets/transient_menu.py)、[fluent.py](../../../gui/styles/fluent.py) |
| 通知标题 | 整数宽度向下取整导致短标题也被省略；以浮点度量向上取整分配标题宽度 | [notifications.py](../../../gui/notifications.py) |
| 日志页状态 | 设备重新连接或选回后仍显示旧准入提示，采集中失选也会覆盖运行状态；仅更新对应准入提示 | [live_logcat.py](../../../gui/dialogs/live_logcat.py) |
| 性能包名查询 | 迟到结果覆盖手动输入；编辑使旧查询失效，包含清空和重新输入原文，完成提示也校验版本 | [performance_launcher.py](../../../gui/dialogs/performance_launcher.py) |
| 性能表单 | Linux 查询按钮与输入框自然高度不同造成错位；按最终字体统一计划控件高度，同时去除无效负尺寸设置 | [performance_launcher.py](../../../gui/dialogs/performance_launcher.py)、[performance_launcher_form.py](../../../gui/dialogs/performance_launcher_form.py) |

## 验证与限制

使用项目 `.venv/bin/python`，Qt 测试采用 `QT_QPA_PLATFORM=offscreen`；设备、进程与存储按既有夹具隔离。
直接及关联测试覆盖字体往返、中文/英文、窄窗口、真实点击、选择保存、迟到回调、缓存阅读和菜单销毁。
新结果展示测试登记到集中 `ui` marker，收集得到 9 个 UI 节点。

修正两处既有测试环境契约：阅读面板通过性能页正式 `activate()` 入口启用日志绘制；
路径期望使用当前平台分隔符。包名线程替身改为未启动的实际 worker，保留运行锁定断言。
以上均未删除或放宽原行为断言。

测试采用 `.venv/bin/python -m pytest -q <下列文件或节点>` 分组运行；失败定位后仅重跑直接与关联节点。
下表的通过数代表该集合各节点的最终验证结果，集合之间有交叉，不累计为一次全量快照。

| 验证集合 | 结果 |
| --- | --- |
| `test_file_explorer_visual.py`、`test_feature_typography.py`、`test_file_explorer_search.py` | 67 通过；另权限批处理、导航失败/迟返关联 9 项通过 |
| `test_file_app_device_admission.py` 及文件工具栏关联节点 | 43 通过 |
| `test_task_center.py`、`test_workspace_feature_host.py` | 10 + 37 通过 |
| `test_session_device_admission.py`、`test_model_performance_launcher.py`、`test_phase2_live_logcat_gate.py` | 29 + 26 + 42 通过 |
| `test_action_result_presentation.py`、`test_action_feedback.py`、`test_run_results.py`、`test_run_results_host.py`、`test_panel_typography.py` | 集成组合 74 通过；增加真实主窗口附件回归后，展示测试文件 9 项全部通过 |
| `test_responsive_layout_controller.py`、`test_adaptive_navigation.py`、`test_adaptive_category_stack.py`、`test_reading_surface.py`、`test_performance_responsive.py` | 49 + 3 + 9 + 39 + 52 个节点完成验证；性能对齐修复后另对 7 个大字/窄窗关联节点复验通过 |
| `test_transient_menu.py`、`test_fluent_dialog_contract.py`、`test_screenshot_page.py` | 9 + 28 + 27 通过；文件菜单关联 15 项通过，应用树/图标两种菜单的实际点击探针通过 |
| `test_notifications.py` | 29 通过，1 项既有 Linux 高度断言失败；原 HEAD 独立复现，详见风险账本 |

对修改的生产代码及测试运行 Ruff；对受影响生产模块运行 Pyright、中文注释检查，均通过。
`scripts/check_doc_links.py` 与 `git diff --check` 通过。性能页构造、显示及销毁的 Qt 消息探针
确认不再产生负尺寸警告。

本轮没有运行全量 pytest、PyInstaller 构建或真实设备操作。更改未触及依赖、打包资源、
持久化数据格式或外部命令协议；Windows/macOS 原生桌面、混合 DPI 及实机断连需另行验收。

## 人工验收入口

1. Linux 和 Windows 原生窗口中切换 100%/150%/200% 缩放，字体由默认调大再恢复。
2. 缩窄主窗口，查看文件路径、任务取消按钮、结果复制/导出与附件打开入口；拖动文件/应用列宽后再次缩放。
3. 文件页缓存较多行后取消设备选择，确认可继续滚动且双击、回车和右键不发起设备命令。
4. 连续打开/关闭文件、应用和截图右键菜单，分别使用鼠标、方向键和 Escape，再关闭页面。
5. 性能页获取包名时立即编辑，确认完成后保留输入；日志页恢复设备选择后检查状态提示。

后续交互统一和平台验证缺口见 [风险账本](../../project-knowledge/RISKS_AND_DEBT.md)，本记录不重复维护待办。
