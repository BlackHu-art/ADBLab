---
kind: class
---

# CommandRunner

- 模块：[[core.exec]]
- 全名：core.exec.CommandRunner

> 同步短命令的统一 subprocess.run 边界

## 方法

- [[core.exec.CommandRunner.active_count]] — 返回当前仍在执行的同步命令数量
- [[core.exec.CommandRunner.run]] — 执行有超时上限的短命令，并将退出码和输出归一为 ``CommandResult``
- [[core.exec.CommandRunner.run_to_file]] — 执行命令并将二进制标准输出直接写入文件

