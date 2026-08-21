---
kind: file
---

# core.exec

> core 层统一执行契约与短命令执行入口（ADR-0005）

- 路径：core/exec.py

## 类

- [[core.exec.CommandResult]] — 统一的命令执行结果
- [[core.exec.CommandRunner]] — 同步短命令的统一 subprocess.run 边界
- [[core.exec.ExecHandle]] — 进程句柄协议：描述 ``subprocess.Popen`` 与测试替身共同满足的结构面
- [[core.exec.ProcessRunner]] — 统一管理后台子进程，支持按 key 启动/停止/轮询

## 函数

- [[core.exec._adb_summary]] — （无 docstring）
- [[core.exec._command_summary]] — （无 docstring）
- [[core.exec._is_adb]] — （无 docstring）
- [[core.exec._log_if_slow]] — （无 docstring）
- [[core.exec._mark_finished]] — （无 docstring）
- [[core.exec._mark_started]] — （无 docstring）
- [[core.exec._program_name]] — （无 docstring）
- [[core.exec._slow_threshold_ms]] — （无 docstring）
- [[core.exec.resolve_adb_program]] — 解析并缓存 ADB 可执行文件路径（唯一解析入口）
- [[core.exec.resolve_command]] — 返回解析后的命令副本：首位 ``"adb"`` token 替换为 ADB 可执行路径

