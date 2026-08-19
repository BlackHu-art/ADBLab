# Phase 0 变更账本

## 目标

在不移动目录、不引入 Operation 公共契约、不改变总体 UI 架构的前提下完成：

- CI/Release 破坏性权限止血；
- 邮件配置和日志敏感边界止血；
- 危险操作确认策略 v1；
- Monkey、AppManager、批次和 MobilePerf 的失败语义修复；
- Remote active device 修复；
- DeviceStore 原子持久化；
- 对应 characterization tests；
- 全量门禁与 Go/No-Go 结论。

## 非目标

- 不实现 Task Center。
- 不实现 TaskSupervisor。
- 不迁移 Screenshot。
- 不修改 async signal 契约。
- 不移动现有包。
- 不清理 Git 历史。

## 当前基线

- 分支/提交：`dev@6f7b699def01`
- 已有用户修改：
  - `core/mail/mail.yaml`
  - `docs/project-knowledge/INDEX.md`
  - `docs/project-knowledge/glossary.md`
- 这些文件不得被覆盖、暂存或输出敏感 diff。

## 文件所有权

| Owner | 可写范围 |
| --- | --- |
| 主 agent | 本实施文档、邮件 service/task、危险策略、MainFrame/AppManager 确认接线、DeviceStore、新独立测试、知识文档收口 |
| CI agent | `.github/workflows/Auto-Clean.yaml`、`.github/workflows/Build-exe.yaml`、`tests/test_ci_contracts.py` |
| Failure agent | `utils/batch_tracker.py`、`models/adb_testing.py`、`models/app_manager_worker.py`、`tests/test_phase0_failure_semantics.py` |
| Remote/MobilePerf agent | `gui/panels/remote_panel.py`、`models/mobileperf/runner.py`、`gui/dialogs/performance_launcher.py`、`tests/test_phase0_remote_mobileperf.py` |

## 阶段门禁

- 目标测试通过。
- 既有 229 项测试通过，或所有主动变更的旧契约已被明确审查并更新。
- packaging self-check 通过。
- `git diff --check` 通过。
- 没有意外生成文件。
- 没有敏感值进入代码、测试、文档或日志。
- ADB/Remote/MobilePerf 实机项在无设备时标记“待确认”。

## 回滚点

各专项改动保持文件范围互斥。若单项无法达到门禁，回退该专项实现，不影响其他专项。
不使用 `git reset --hard` 或覆盖用户已有修改。

## 实施结果（2026-07-25）

| 专项 | 结果 | 自动验证 | 剩余外部动作 |
| --- | --- | --- | --- |
| CI/Release | Auto-Clean 改为手动只读 Retention Audit；Actions 固定 SHA；Release 不可变 | `tests/test_ci_contracts.py` | 在真实 GitHub Actions 首次运行时复核权限 |
| 邮件边界 | 只读用户域配置/环境注入；强制 connect/read timeout；账号、正文、验证码、请求/响应和签名不入日志 | `tests/test_email_service.py` | 仓库所有者轮换材料、停止跟踪并审查历史 |
| 危险操作 | 主窗口已知高影响信号与 App Manager 动作接入统一确认策略 | `tests/test_dangerous_ops.py` | 新入口必须注册策略；实机确认文案待 UX 验证 |
| 失败语义 | BatchTracker 线程安全且只汇总一次；Monkey fail-closed；AppManager 关键命令失败不再报成功 | `tests/test_phase0_failure_semantics.py` | 备份 manifest/hash 与实机恢复矩阵 |
| Remote | 输入锁定启动时活动会话；未运行拒绝；多选不记录设备标识 | `tests/test_phase0_remote_mobileperf.py` | 授权设备最小控制验证 |
| MobilePerf | 记录运行前基线与退出码；旧/空报告不再触发 Completed/100 | `tests/test_phase0_remote_mobileperf.py` | 授权设备 5 分钟采集/停止/失败验证 |
| DeviceStore | 同锁域读写、原子替换、损坏备份、返回深拷贝 | `tests/test_device_store_concurrency.py` | 真实断电/磁盘满属于后续故障测试 |
| 关闭 | MainFrame 显式 shutdown LogService | 全量回归中的 MainFrame 生命周期测试 | 全局 QRunnable 统一等待留给 TaskSupervisor |

## 门禁记录

- `py -3.11 -m pytest -q`：**268 passed in 3.85s**。
- `py -3.11 main.py --self-check packaging`：**通过**；PySide6、Requests、MobilePerf、
  icon/resources、Windows 内置 adb/scrcpy 和用户数据目录均为 OK。
- `git diff --check`：**通过**（仅有工作树 LF/CRLF 提示，无 whitespace error）。
- Ruff：环境未安装（`No module named ruff`），未冒充通过；pytest 与现有门禁不依赖 Ruff。
- 实机：当前没有授权设备，Remote/ADB/MobilePerf 实机项标记 **待确认**。
- 用户已有修改：`core/mail/mail.yaml`、`docs/project-knowledge/INDEX.md`、
  `docs/project-knowledge/glossary.md` 均未覆盖、暂存或输出内容。

## Go/No-Go

**自动化门禁结论：Go，可进入 Phase 1 公共 Operation 契约。**

该结论不等同于实机功能验收；Phase 2 的 Screenshot/LiveLogcat/Install Gate 在没有授权设备时，
只能先完成契约与故障注入验证，产品级完成仍需补最小实机验证。
