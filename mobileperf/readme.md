# ADBLab MobilePerf 移植说明

本目录包含 Alibaba [mobileperf](https://github.com/alibaba/mobileperf) 的项目内移植版本，
用于 Android CPU、内存、FPS、日志、流量、进程和 Monkey 等性能采集。许可文本见
[`LICENSE`](LICENSE)。

## 当前运行边界

- GUI 通过 `services/mobileperf_runner.py` 生成每次运行独立的临时配置并启动受控子进程。
- 打包后，worker 复用主可执行文件的 `--mobileperf-worker --config <path>` 入口；源码运行时，
  runner 使用当前 Python 解释器调用 `mobileperf.android.startup --config <path>`。
- ADB 路径、结果目录、日志批量回传、停止和清理均由 ADBLab 适配层管理。
- `config.conf` 只保留为内核默认配置样例；正常 GUI 流程不会原地修改它。

本目录不再提供上游旧版 `run.bat`、`run.sh` 或 `setup.py` 入口。这些脚本绕过 ADBLab 的
进程、配置和用户数据边界，不能用于验证当前应用行为。构建、运行和测试命令统一见
[`docs/guides/BUILD_AND_RUN.md`](../docs/guides/BUILD_AND_RUN.md) 与
[`docs/guides/TESTING_GUIDE.md`](../docs/guides/TESTING_GUIDE.md)。
