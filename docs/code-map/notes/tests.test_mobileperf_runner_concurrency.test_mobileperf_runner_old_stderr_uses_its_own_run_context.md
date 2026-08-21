---
kind: function
---

# test_mobileperf_runner_old_stderr_uses_its_own_run_context(tmp_path, monkeypatch)

- 定义于：[[tests.test_mobileperf_runner_concurrency]]
- 全名：tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_old_stderr_uses_its_own_run_context

> 第二次运行开始后，首轮延迟 stderr 仍使用首轮脱敏值和完成回调

## 调用

- [[tests.test_mobileperf_runner_concurrency._completed_process]]

## 实例化

- [[services.mobileperf_runner.MobilePerfRunConfig]]
- [[services.mobileperf_runner.MobilePerfRunner]]
- [[tests.test_mobileperf_runner_concurrency._CountingStream]]
- [[tests.test_mobileperf_runner_concurrency._DelayedStream]]
- [[tests.test_mobileperf_runner_concurrency._StoppableProcess]]

