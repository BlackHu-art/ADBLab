# 无线 ADB 配对实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review each task. No commits or pushes are authorized in this task.

**Goal:** 完成扫码、手动配对码和既有地址连接的统一入口，并验证身份、取消、窗口关闭和历史兼容性。

**Architecture:** 复用 CommandRunner 的原生执行边界，新增纯 Python 配对服务、Qt 会话协调器和 FluentDialog。
ADB 自带 mDNS 负责发现，GUID 负责关联最终无线 transport，现有监督器负责资源清理。

**Tech Stack:** Python 3.11、PySide6 6.8.1.1、PySide6-Fluent-Widgets 1.11.3、segno 1.6.6、pytest。

**Spec:** [已批准设计](../specs/2026-09-25-wireless-adb-pairing-design.md)。交互细节由专门 agent 对照现有 PySide6 Gallery 移植后补充，不改变协议与资源契约。

## Global Constraints

- 本任务在当前 `ui-redesign` 工作区实现，保留已有方案；不提交、推送、改版本或改 CI/CD。
- 使用用户确认的本地 Python，不创建 `.venv`；测试新增依赖装入任务临时目录，不污染系统 Python。
- 生产依赖仅新增 `segno==1.6.6`，同步 constraints、第三方声明和实际打包许可收集。
- 所有配对命令固定本轮 ADB 绝对路径与环境，口令仅通过 stdin，界面不显示原始命令输出。
- 新增 Qt 测试使用现有 QApplication 与离屏模式，标注 `pytest.mark.ui`；不增加 pytest-qt。
- 配对成功不等于已连接；完整 GUID、连接服务和无线在线状态精确关联，不用同 IP/型号/新增设备数推断。
- 保持历史 schema 和已有操作目标，新增地址历史不能覆盖已有有效元数据。
- 只运行各任务直接与关联测试；最终集成范围由主任务按测试指南确定。

## Review Focus

1. popen 尚未返回时取消：迟到的客户端仍受作用域管理，Task 1 用 Event/Barrier 固定竞态。
2. worker 返回但客户端清理失败：资源不得注销，Task 1 与 Task 3 分别验证底层归属和 Qt 关闭屏障。
3. 旧 ADB 返回码 0 但正文失败：Task 2 固定真实形态响应样本，不误报配对成功。
4. PairedOnly 状态更换客户端：Task 3 撤销不含口令的续连快照，后续点击不执行旧上下文命令。
5. FluentDialog 关闭后重开：Task 3 重建窗口并验证主题、焦点与信号不重复。

## Task 1: 可取消原生命令的输入、环境与资源归属

**Files:** 修改 `core/exec.py`、`core/adb_runtime.py`、`core/native_process.py`；测试 `tests/test_command_outcomes.py`、`tests/test_native_process.py`、`tests/test_adb_runtime.py`，可新增 `tests/test_native_command_scope.py`。

**Interfaces:**

```python
CommandRunner.run(cmd, timeout=30, shell=False, *, cancelled=None,
                  native_only=False, native_tool=False,
                  input_bytes=None, env=None, command_scope=None)
native_capture(cmd, timeout, cancelled, *, stdout_sink=None,
               input_bytes=None, env=None, command_scope=None)
# core.native_process.NativeCommandScope 的对外资源契约
scope = NativeCommandScope()
scope.request_stop()  # 幂等、线程安全、不等待
scope.is_running()    # 包含启动中和未确认退出的客户端
scope.wait(timeout)   # 供后台监督器调用的有界等待/残留收口
```

- [x] 先新增失败测试：stdin 仅首次 communicate 发送、env 不被修改/忽略、有输入/环境时强制原生、shell 组合拒绝；默认调用保持兼容。
- [x] 新增取消与 spawn 交错、清理超时保留句柄、poll 异常保守报告、正常完成移除句柄测试。
- [x] 使用原有 popen_native/取消规则实现最小扩展；scope 在启动前登记、成功后接管，即使取消已发生也不能漏管；不与 worker 并发 communicate，不停止独立 ADB server。
- [x] 运行上述测试及 Ruff/Pyright；记录实际命令、失败到通过的证据；交付实现报告供独立审查。

## Task 2: 配对服务与二维码

**Files:** 新建 `services/adb_pairing.py`、`tests/test_adb_pairing.py`；修改 `requirements.txt`、`constraints.txt`、`THIRD_PARTY_NOTICES.md`，必要时修改现有打包许可收集。

**Interfaces:** 在服务中定义 frozen dataclass：`PairingContext`、`PairingRequest`、`PairingProgress`、`PairingOutcome`、`PairingContinuation`。公开 `PairingService.run(request, context, cancel_event, command_scope, on_progress, on_qr)`，以及 QR/手动/续连请求工厂；最终准确签名在任务报告中交付下一任务。服务不导入 Qt，命令/时钟/等待可注入以测试。

```python
# 注入脚本式命令替身，断言业务结果而非真实网络。
outcome = service.run(request, context, cancelled, scope, events.append, images.append)
assert outcome.connected is False  # rc=0 的 failed pairing 正文不得成功
assert all(secret not in repr(event) for event in events)
```

- [x] 先实现失败测试，覆盖设计第 5 节的解析/身份链、重复/冲突服务、IPv6 手动地址、提示同行、既有连接、USB 与无线并存、无关设备上线、配对成功待连接。
- [x] 实现 QR 生成与内存 PNG，安全 ASCII 随机名/24 位口令、标准 QR 和白色静区；只有二维码显示阶段保留载荷。
- [x] 实现本轮固定上下文的 mdns→pair→GUID→connect→devices 流程。准备/扫码/配对/确认连接预算分别 15/120/15/30 秒，总预算 180 秒；查询最多 5 秒，connect 最多 10 秒，读轮询间隔约 1 秒；写操作不自动重放。
- [x] 实现 PairedOnly 续连与不含口令的恢复快照；手动配对不要求 mDNS 成功；未知配对结果明确分类，原始输出不向 UI/日志传递。
- [x] 补单轮取消、截止时间、恶意回显口令、固定路径/env、服务端变更和明确清理失败测试；运行直接测试和静态检查后交付报告。

## Task 3: Qt 协调器、界面与主窗口集成

**Files:** 新建 `adblab/presentation/qt_adb_pairing.py`、`gui/dialogs/device_connection.py`、三者的测试；修改 `gui/main_frame.py`、`gui/close_controller.py`、`gui/pages/fluent_pages.py`、`controllers/_device.py` 及相关测试。沿用 `gui/widgets/device_context_bar.py::DeviceConnectionForm`。

**Interfaces:** `QtAdbPairing(QObject)` 提供开始扫码/提交配对码/续连/取消/失效/关闭准备与监督器资源注册；通过结构化信号交付状态、PNG 与 verified outcome。MainFrame 持有协调器和单实例对话框，控制器提供 `accept_wireless_connection(verified_outcome)`。

```python
coordinator.invalidate("client_changed")
coordinator.continue_connection(endpoint)
assert commands == []  # 旧 PairedOnly 续连资格已撤销
```

- [x] 先按交互规格补 Qt 测试：默认地址页不发现、点击扫码再启动、单实例、焦点、忙碌态、反复刷新与晚到回调。
- [x] 实现一个活动 QThread、独立 request_id/context_revision、原线程结束且scope归零后才接收下一轮，监督器注册幂等；应用与窗口关闭共用清理而不阻塞主线程。
- [x] 按专门交互规格实现 Gallery 风格三页窗口、扫码指引、状态/倒计时/可操作错误、PairedOnly 补填端口、Escape关闭和高DPI二维码。
- [x] 接主窗口入口、设置客户端前/重检前/重启提交前失效；性能模式变化和普通发现状态不误取消。
- [x] 连接结果只刷新列表，不自动选设备；历史通过已有后台执行器写盘，使用有效缓存属性并保留已有字段，拒绝失效结果和配对端口。
- [x] 测试覆盖取消/关闭/清理失败/重开主题、旧地址连接、历史及已有选择；运行直接与相关 Qt 测试、静态检查，交付报告与离屏截图供审查。

## Task 4: 翻译、文档与验收

**Files:** 同步 `resources/i18n/` 与 `gui/generated/translations_rc.py`；更新 `docs/project-knowledge/ARCHITECTURE.md`、`BUSINESS_FLOW.md`、`DEPENDENCY_MAP.md`、相关模块/测试索引；形成验收记录。

- [x] 补完整三种语言的新增界面文案，沿用 Qt lrelease/rcc zlib 生成流程；执行现有翻译契约测试。
- [x] 将当前事实同步到知识库，保留方案状态与未验收的兼容性边界；执行文档链接、中文注释、文本与 diff 检查。
- [x] 运行新功能全部直接测试及变更关联集，对共享核心接口实施 Pyright；独立最终审查后修复有效问题并重跑对应测试。
- [x] 运行源码 packaging self-check。检查现有构建工具和资源，在可用条件下验证冻结原生 stdin/env/取消及 Segno 收集；缺少外部工具或实机时明确记录，不伪造通过。
- [x] 用模拟设备输出驱动实际窗口做成功/失败/取消交互验收；真实手机扫码、多设备与网络兼容按实机条件验收。用户未授权的真实设备操作不自行执行。

## 执行记录

任务明细、审查和命令结果记录在本任务临时工作目录，最终汇总到验收记录。用户已明确要求开始实现，
本计划细化已批准方案，不重新发起重复实施确认。当前工作区仅有本任务方案文件；沿用当前分支避免
迁移用户已有上下文，所有改动保留为可审查的未提交差异。

2026-09-25 收口：四项任务的实现、独立评审、直接与关联验证已完成；最终冻结产物通过 packaging
49 项、离屏 GUI 和真实 native 成功/取消/超时检查。条件性手机验收尚未执行，不计为已通过。
完整结果、唯一既有平台模拟断言失败及人工验收步骤见
[无线 ADB 配对验收记录](../../archive/ledgers/2026-09-25-wireless-pairing.md)。
