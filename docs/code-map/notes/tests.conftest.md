---
kind: file
---

# tests.conftest

- 路径：tests/conftest.py

## 函数

- [[tests.conftest.drain_qt_deferred_deletes]] — 保留兼容夹具名称；窗口清理由 isolated_ui_state 按安全边界处理
- [[tests.conftest.isolated_ui_state]] — 恢复每个用例改动过的全局 UI 状态并清理其顶层窗口
- [[tests.conftest.isolated_ui_state_probe]] — 为隔离夹具提供可重复的 teardown 断言入口
- [[tests.conftest.pytest_collection_modifyitems]] — 按文件把测试标记为 ui / integration，其余保持默认（计入快速子集）
- [[tests.conftest.qt_application]] — 在整个测试进程中保留同一个 QApplication 包装对象

