---
kind: file
---

# services.file_explorer

> File Explorer 的纯逻辑层：路径、命令构建和列表解析

- 路径：services/file_explorer.py

## 类

- [[services.file_explorer.FileEntry]] — （无 docstring）

## 函数

- [[services.file_explorer._is_size_token]] — （无 docstring）
- [[services.file_explorer._looks_iso_date]] — （无 docstring）
- [[services.file_explorer._looks_month]] — （无 docstring）
- [[services.file_explorer._looks_time_or_year]] — （无 docstring）
- [[services.file_explorer._split_modified_name]] — （无 docstring）
- [[services.file_explorer.cat_command]] — （无 docstring）
- [[services.file_explorer.chmod_command]] — （无 docstring）
- [[services.file_explorer.copy_command]] — （无 docstring）
- [[services.file_explorer.copy_for_root_pull_command]] — （无 docstring）
- [[services.file_explorer.delete_command]] — （无 docstring）
- [[services.file_explorer.device_path]] — （无 docstring）
- [[services.file_explorer.extension_label]] — （无 docstring）
- [[services.file_explorer.folder_size_command]] — （无 docstring）
- [[services.file_explorer.format_size]] — （无 docstring）
- [[services.file_explorer.install_apk_command]] — （无 docstring）
- [[services.file_explorer.ls_command]] — （无 docstring）
- [[services.file_explorer.mkdir_command]] — （无 docstring）
- [[services.file_explorer.mode_from_permissions]] — （无 docstring）
- [[services.file_explorer.move_command]] — （无 docstring）
- [[services.file_explorer.normalize_mode]] — （无 docstring）
- [[services.file_explorer.parse_ls_line]] — 解析 toybox、busybox 或 coreutils 产生的一行 ls -la 输出
- [[services.file_explorer.parse_ls_output]] — 解析 adb shell `ls -la` 输出，并保持文件夹优先、名称升序
- [[services.file_explorer.parse_mode]] — 解析设备返回的权限模式；无法确认时不伪造默认权限
- [[services.file_explorer.root_command]] — （无 docstring）
- [[services.file_explorer.safe_int]] — （无 docstring）
- [[services.file_explorer.safe_name]] — 校验单个文件名，阻止路径穿越和 shell 元字符进入命令字符串
- [[services.file_explorer.save_text_command]] — （无 docstring）
- [[services.file_explorer.script_command]] — （无 docstring）
- [[services.file_explorer.shell_quote]] — 用单引号包裹远端 shell 参数，避免空格、$、双引号等字符被二次解释
- [[services.file_explorer.stat_mode_command]] — （无 docstring）
- [[services.file_explorer.touch_command]] — （无 docstring）

