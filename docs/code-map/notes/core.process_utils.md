---
kind: file
---

# core.process_utils

> 纯 Python 进程工具：TCP 端口占用查找与进程树终止

- 路径：core/process_utils.py

## 函数

- [[core.process_utils._deadline]] — 把可选总时限换算为绝对截止时间；``None`` 表示无截止时间
- [[core.process_utils._expired]] — （无 docstring）
- [[core.process_utils._kill_children]] — 递归终止子进程，先处理最深层后代
- [[core.process_utils._kill_one]] — 终止单个进程；已退出视为成功
- [[core.process_utils._remaining_or]] — 无截止时间时返回默认等待；有截止时间时返回剩余秒数（不足 0 返回 0）
- [[core.process_utils.find_pids_listening_on]] — 返回监听指定 TCP 端口的进程 PID 列表（去重、保序）
- [[core.process_utils.kill_process_tree]] — 终止指定进程及其子进程（先子后父），返回 (是否已确认退出, 说明)
- [[core.process_utils.process_name]] — 返回进程名；进程不存在或不可读时返回空字符串

