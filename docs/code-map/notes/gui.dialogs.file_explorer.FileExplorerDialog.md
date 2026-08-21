---
kind: class
---

# FileExplorerDialog

- 模块：[[gui.dialogs.file_explorer]]
- 全名：gui.dialogs.file_explorer.FileExplorerDialog

## 方法

- [[gui.dialogs.file_explorer.FileExplorerDialog.__init__]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._init_ui]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._reflow_top_controls]] — 在窄窗口中把路径、搜索和工具按钮重排到多行
- [[gui.dialogs.file_explorer.FileExplorerDialog.resizeEvent]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._create_context_menu]] — 创建跟随当前主题且由窗口托管的上下文菜单
- [[gui.dialogs.file_explorer.FileExplorerDialog._apply_theme]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._connect_worker_ui]] — 连接 worker 的界面回调，并在窗口或关联子窗口销毁后拒绝晚到信号
- [[gui.dialogs.file_explorer.FileExplorerDialog._disconnect_worker_ui]] — 断开指定 worker 的全部界面回调
- [[gui.dialogs.file_explorer.FileExplorerDialog._prune_worker]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._retain_workers_until_stopped]] — 解除窗口所有权后持续持有线程，避免运行中的 QThread 被销毁
- [[gui.dialogs.file_explorer.FileExplorerDialog._run_adb]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._run_transfer]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._root]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._safe_name]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._dpath]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._navigate]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._go_back]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._go_forward]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._go_parent]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._refresh]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._on_ls_result]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._set_file_row]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._file_name_at]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._file_type_at]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._file_type_icon]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._file_type_icon_name]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._parse_ls]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._ext]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._safe_int]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._fmt_size]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._on_double_click]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._filter]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._header_clicked]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._view_or_pull]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._view_file]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._view_image]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_image]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_text_viewer]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._apply_text_dialog_fonts]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._bind_dialog_font_refresh]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._global_save_dir]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._save_as]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._save_to_device]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._on_save_result]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._pull_file]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._finish_root_pull]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._pull_selected]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._push_file]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._on_transfer_done]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._on_file_op_done]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._mkdir]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._touch]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._rename_item]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._delete_item]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._request_delete]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._delete_selected]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._copy_items]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._paste_items]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_chmod]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._context_menu]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._install_apk]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._exec_script]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_script_output]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_props]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_props_file]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog._show_props_done]] — （无 docstring）
- [[gui.dialogs.file_explorer.FileExplorerDialog.register_shutdown_tasks]] — 将仍在运行的文件 worker 作为一组资源注册到监督器
- [[gui.dialogs.file_explorer.FileExplorerDialog.closeEvent]] — 先隔离全部界面回调，再中止并持续持有尚未退出的 worker

