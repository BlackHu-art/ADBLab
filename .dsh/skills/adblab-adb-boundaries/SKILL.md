---
name: adblab-adb-boundaries
description: >-
  ADBLab 与设备/外部工具之间的执行边界：ADB 命令构造与 shlex.quote 校验、客户端解析与自动适配
  (auto/fast/native)、长进程与 shell 会话归属、scrcpy 专用 ADB 桥与会话租约、文件路径安全与
  ZIP 解压边界、日志脱敏要求。Use when adding or changing an ADB command, a transfer, a long-running
  device process, or anything that touches device paths in this repo.
whenToUse: 新增/修改 ADB 命令、文件传输、录屏/投屏等长任务，或处理设备端路径与外部工具时。
---

# ADBLab 设备与外部命令边界

## 命令构造

- 一律用参数数组调用（`shell=False` 的 subprocess 或现有 `CommandRunner`/`ADBModelCore._run`），
  不要拼 shell 字符串。
- 设备 shell 内的动态值必须经过既有校验/quote 边界：
  `shlex.quote` / `services/file_explorer.shell_quote` / `_shq` /
  `utils/adb_values.normalize_*`（端口、包名、dumpsys 服务名、geo 坐标、诊断截断）。
  **不要把 UI 传入的值直接拼进复合命令。**
- 校验失败要在进入设备前拒绝（fail closed）；错误文案不要回显真实设备标识。

## 客户端解析与执行模式

- 解析链：`utils/adb_resolver.py`（Windows 内置 → `ADB_PATH` → Android SDK → PATH，进程内缓存）。
  客户端选择来自设置 `adb_client`，切换后要清缓存并重新检测。
- 源码开发控制台与 `utils/adb_debug.py` 只记录命令类别，不记录 serial、命令参数值与本机路径。
- 自动适配：`core/adb_runtime.py` 的后台探测决定 `fast`/`native`；被选中设备的短命令可走直连
  5037（`core/adb_transport.py`）。能力失效、协议不兼容、自定义 server 等情况必须回落原生，
  且**不得重放**已发出的命令。相关文档：`docs/guides/ADB_FAST.md`。

## 长进程、会话与投屏

- 长任务用 `ProcessRunner.start(key, ...)`，键要能唯一标识会话；停止要先 `request_stop`，
  再按预算等待，未确认退出时保留 residual（不要伪造成功）。
- Remote/投屏的进程、端口与输出流归属在 `services/remote/scrcpy_service.py`：
  端口预留是进程内集合，会话目录与 helper 租约由 `core/scrcpy_session.py` 管理；
  direct 模式经随包 CLI `scripts/scrcpy_adb_bridge.py`（构建产物进 `build/runtime-helpers`）。
- 录屏：远端文件只有在**确认录制结束**后才拉取；本地先写临时文件再原子发布，
  失败不得留下半成品或覆盖已有文件；失败重试沿用原批次身份，不重新录制。

## 文件与压缩边界

- 设备路径校验：拒绝 `..`、控制字符与元字符；删除/复制/移动前确认目标是本次操作的对象。
- 外部 ZIP 一律用 `utils/archive.py::safe_extract_zip()`（逐成员解析必须落在目标目录内）。
- 上传/下载经过页面串行传输协调器；取消也要交付生命周期终态，清理义务要 `hold_cleanup()`/
  `release_cleanup()` 成对登记与归还。

## 脱敏

控制台与诊断文件复用 `core/diagnostics.py::redact_diagnostic`（设备标识、凭据、IPv4、MAC、
本机路径）；界面原文保持不脱敏。新增日志点前先确认字段不会进入诊断导出。
