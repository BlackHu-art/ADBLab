# 提示迁移只读审计（改动前调用快照）

31 处 FluentMessageBox（17 warning、11 critical、3 information），返回值全部未被调用方消费。按用户统一要求，31 处全部迁移为非阻塞 Toast；另外 3 处 InfoBar 接入统一右上角通知。文件属性正文使用可滚动、可选中复制、悬停暂停的长 Toast。未发现生产 QMessageBox 或 question 调用。

| 路径与行号 | 入口 | 当前调用 | 迁移分类 |
| --- | --- | --- | --- |
| gui/dialogs/app_manager_batch.py:187 | `AppManagerBatch._modify_selected` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/app_manager_batch.py:260 | `AppManagerBatch._backup_selected` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/app_manager_batch.py:312 | `AppManagerBatch._show_details` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/app_manager_batch.py:324 | `AppManagerBatch._create_preset` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/app_manager_batch.py:459 | `AppManagerBatch._report_preset_error` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/app_manager_details.py:413 | `AppDetailsPage._mp` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/file_explorer.py:1054 | `FileExplorerPage._show_props_file` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer.py:1080 | `FileExplorerPage._show_props_file` | `FluentMessageBox.information` | 长 Toast：属性正文可滚动/选中复制，悬停暂停 |
| gui/dialogs/file_explorer.py:1084 | `FileExplorerPage._show_props_done` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer.py:1096 | `FileExplorerPage._show_props_done` | `FluentMessageBox.information` | 长 Toast：属性正文可滚动/选中复制，悬停暂停 |
| gui/dialogs/file_explorer_ops.py:63 | `FileExplorerOps._on_save_result` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:119 | `FileExplorerOps._finish_root_pull` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:209 | `FileExplorerOps._on_transfer_done` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:221 | `FileExplorerOps._on_file_op_done` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:236 | `FileExplorerOps._mkdir` | `FluentInputDialog.getText` | 保留：用户输入，返回值依赖 |
| gui/dialogs/file_explorer_ops.py:240 | `FileExplorerOps._mkdir` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:262 | `FileExplorerOps._touch` | `FluentInputDialog.getText` | 保留：用户输入，返回值依赖 |
| gui/dialogs/file_explorer_ops.py:266 | `FileExplorerOps._touch` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:288 | `FileExplorerOps._rename_item` | `FluentInputDialog.getText` | 保留：用户输入，返回值依赖 |
| gui/dialogs/file_explorer_ops.py:292 | `FileExplorerOps._rename_item` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:499 | `FileExplorerOps._show_chmod._on_stat` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:508 | `FileExplorerOps._show_chmod._on_stat` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/file_explorer_ops.py:554 | `FileExplorerOps._show_chmod._apply_permissions._on_chmod` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/live_logcat_stream.py:348 | `LiveLogcatStream._export` | `FluentMessageBox.critical` | Toast 状态提示 |
| gui/dialogs/performance_launcher.py:561 | `PerformancePage.open_result` | `FluentMessageBox.information` | Toast 状态提示 |
| gui/dialogs/performance_launcher_form.py:1063 | `PerformanceLauncherForm._commit_numeric_inputs` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/performance_launcher_run.py:24 | `PerformanceLauncherRun.start_mobileperf` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/performance_launcher_run.py:35 | `PerformanceLauncherRun.start_mobileperf` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/performance_library.py:124 | `PerformanceLibrary.apply_parameters` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/dialogs/screenshot_viewer_actions.py:75 | `ScreenshotViewerActions._delete_file` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/main_frame.py:1843 | `MainFrame._on_run_library_error` | `InfoBar.warning` | 已是通知，统一右上角 |
| gui/main_frame.py:2269 | `MainFrame._on_screenshot_batch_ready` | `InfoBar.success` | 已是通知，统一右上角；截图保留查看结果动作 |
| gui/pages/fluent_pages.py:1355 | `SettingsPage._show_language_restart_hint` | `InfoBar.success` | 已是通知，统一右上角 |
| gui/panels/app_panel.py:956 | `AppPanel._on_start_monkey` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/widgets/run_preset_bar.py:195 | `RunPresetBar._load` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/widgets/run_preset_bar.py:207 | `RunPresetBar._save` | `FluentMessageBox.warning` | Toast 状态提示 |
| gui/widgets/run_preset_bar.py:216 | `RunPresetBar._save` | `FluentInputDialog.getText` | 保留：用户输入，返回值依赖 |
| gui/widgets/run_preset_bar.py:225 | `RunPresetBar._save` | `FluentMessageBox.warning` | Toast 状态提示 |

## 必须保留的其他交互

- `gui/dialogs/app_manager_batch.py:375`：创建应用预设表单。`accepted = bool(dlg.exec())` 决定是否读取名称/作者/说明并进入保存。
- `gui/dialogs/file_explorer_ops.py:583`：chmod 权限编辑表单。包含读取、复原、应用、关闭以及 worker 完成回调，不属于信息提示。
- `gui/dialogs/screenshot_viewer_actions.py:54-70`：删除截图沿用二次点击确认，不转换其确认流程。
- 12 处 QFileDialog 文件/目录选择调用，以及 5 处菜单 exec 不在本次通知迁移范围。

## 已核实的语义和线程边界

- 所有 31 处 FluentMessageBox 调用在 AST 中都是独立 Expr，没有 if/赋值/return 对提示框结果的依赖。
- Monkey 事件合计不为 100% 的警告之后原本也继续准备运行，不是真正确认。性能输入错误后继续恢复焦点并返回 False，这两步必须保留。
- 文件浏览器的 worker 错误经 `_connect_worker_ui`（file_explorer.py:678-692）以 QueuedConnection 返回 GUI，并检查页面存活/代次。未发现 worker.run 内直接调用提示框。
- chmod 表单内 3 处错误（file_explorer_ops.py:499/508/554）传入 dlg；Toast 必须以该可见模态窗口为 owner，不能被强制主窗 owner 遮住。
- 现有消息正文使用 PlainText 且允许选择复制。部分错误直接包含 ADB 输出或 OSError 字符串，通知正文需要保留纯文本和可获取完整内容的能力。
- 属性查看共 2 处是用户主动请求的 4-8 行数据。按用户决策迁为长 Toast，必须提供正文滚动、选择复制和悬停暂停，避免完整数据不可读。

## 建议直接验证边界

- 共享提示：三种级别、非模态立即返回、TOP_RIGHT、单次/连续提示、窄窗/22pt、正文纯文本、关闭/定时器释放与晚到回调。
- 继续保留真实 FluentInputDialog exec 接受/取消与 WA_DeleteOnClose 回归。
- 文件属性转长 Toast 后验证完整正文可滚动/复制；chmod 操作表单保留输入、业务回调和模态生命周期。
- 当前旧测试 `tests/test_fluent_dialog_contract.py` 内静态消息返回 1 和创建模态 `_FluentMessageDialog` 的断言应按新通知契约迁移，不改输入语义断言。
- 关联入口：`test_session_device_admission.py`、`test_performance_library.py`、`test_performance_responsive.py` 中准入和无效数字节点；`test_model_media_adb.py` 文件错误节点；`test_main_window_layout.py` 截图结果通知节点；`test_settings_typography.py` 语言重启提示。

审计阶段仅写 .tmp；后续按授权仅将 `gui/pages/fluent_pages.py:_show_language_restart_hint` 接入公共 `gui.notifications.show_toast`，文案保持原样。未运行全量或实机。

## 文案去重核查

- 未发现 title 与 body 完全相同的固定文本。没有依据对所有提示统一删除标题或正文。
- 应用批处理 `app_manager_batch.py:187/260/324` 重复使用“未选择应用 / 请先选择应用”，`:312` 为“请先选择一个应用”；这是不同入口复用同一准入提示，不是单次调用发出多条通知。正文提供操作建议，可保留。
- 文件属性 `file_explorer.py:1080/1096` 的标题带文件名，正文首行也带名称；长 Toast 里存在一次名称重复，但正文应保持独立可复制的完整属性，建议保留。
- 文件操作 `file_explorer_ops.py:63/119/209/221` 仅用通用“Error”标题，正文携带具体错误，标题信息量低但没有完全重复；若根任务要最小文案优化，可分别改为保存/传输/文件操作失败，需统一翻译。此代理未改文案。
- 设置成功通知“设置已保存 / 语言设置将在重启应用后生效”分别说明保存状态与生效时机，无重复，保持原文。
