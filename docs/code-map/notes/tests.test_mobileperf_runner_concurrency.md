---
kind: file
---

# tests.test_mobileperf_runner_concurrency

> 验证 MobilePerfRunner 双管道排空、回调隔离和连续运行上下文

- 路径：tests/test_mobileperf_runner_concurrency.py

## 类

- [[tests.test_mobileperf_runner_concurrency._CountingStream]] — 记录迭代消费数量的可关闭文本流
- [[tests.test_mobileperf_runner_concurrency._DelayedStream]] — 等待测试放行后再产生内容，用于模拟延迟到达的 stderr
- [[tests.test_mobileperf_runner_concurrency._SnapshotRaceProcess]] — 在旧 stop 完成进程快照后暂停，允许测试线程安装新运行
- [[tests.test_mobileperf_runner_concurrency._StoppableProcess]] — 模拟等待后退出、但 stderr reader 仍可能延迟收口的进程
- [[tests.test_mobileperf_runner_concurrency._TrackingProcessRunner]] — 维护 key 与进程映射，用于检测旧代停止是否误伤新代

## 函数

- [[tests.test_mobileperf_runner_concurrency._completed_process]] — （无 docstring）
- [[tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_callback_failures_do_not_interrupt_pipe_drain]] — 业务与诊断回调异常均不得中断后续管道消费
- [[tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_drains_real_stdout_and_stderr_before_finish]] — 真实子进程的两个高频管道必须全部排空后才能通知完成
- [[tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_old_stderr_uses_its_own_run_context]] — 第二次运行开始后，首轮延迟 stderr 仍使用首轮脱敏值和完成回调
- [[tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_old_stop_never_writes_new_generation_stop_file]] — 旧 stop 已快照 context 后，新运行的停止文件不得被旧线程创建

