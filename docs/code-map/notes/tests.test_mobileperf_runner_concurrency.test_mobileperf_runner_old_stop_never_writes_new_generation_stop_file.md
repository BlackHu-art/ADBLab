---
kind: function
---

# test_mobileperf_runner_old_stop_never_writes_new_generation_stop_file(tmp_path)

- 定义于：[[tests.test_mobileperf_runner_concurrency]]
- 全名：tests.test_mobileperf_runner_concurrency.test_mobileperf_runner_old_stop_never_writes_new_generation_stop_file

> 旧 stop 已快照 context 后，新运行的停止文件不得被旧线程创建

## 实例化

- [[services.mobileperf_runner.MobilePerfRunConfig]]
- [[services.mobileperf_runner.MobilePerfRunner]]
- [[tests.test_mobileperf_runner_concurrency._CountingStream]]
- [[tests.test_mobileperf_runner_concurrency._DelayedStream]]
- [[tests.test_mobileperf_runner_concurrency._SnapshotRaceProcess]]
- [[tests.test_mobileperf_runner_concurrency._StoppableProcess]]
- [[tests.test_mobileperf_runner_concurrency._TrackingProcessRunner]]

