---
kind: method
---

# start(self, key, cmd, stdout=None, stderr=None, *, stdin=None, cwd=None, text=False, encoding=None, errors=None, bufsize=-1, creationflags=None, env=None)

- 定义于：[[core.exec.ProcessRunner]]
- 全名：core.exec.ProcessRunner.start

> 启动子进程，同名 key 会先停止旧进程

## 调用

- [[core.exec.ProcessRunner._register_global]]
- [[core.exec.ProcessRunner._stop_proc]]
- [[core.exec.ProcessRunner._unregister_global]]
- [[core.exec.ProcessRunner.spawn]]

