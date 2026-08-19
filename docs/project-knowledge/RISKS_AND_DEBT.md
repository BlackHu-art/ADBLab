---
status: current
last_verified: 2026-08-19
owner: 待确认
related: [ARCHITECTURE.md, MODULE_MAP.md, DATA_FLOW.md]
---

# 风险与技术债

下表按严重程度和影响排序。前 10 项是本次审计的最高优先级；“Open”表示尚未修复，
“Partial”表示代码侧已止血但仍有所有者或实机动作，“Closed”表示本阶段代码与自动测试已闭环，
“待确认”表示影响或运行条件需要额外实测。知识库不记录任何敏感配置具体值。

| 等级 | 风险 | 证据位置 | 影响 | 建议 | 状态 |
| --- | --- | --- | --- | --- | --- |
| High | MobilePerf 遗留 ADB 层直接使用 `shell=True`，含查询和强杀占用 5037 端口进程 | `mobileperf/android/tools/androiddevice.py::get_adb_path/killOccupy5037Process` | 命令注入面、错误杀进程、绕过主应用超时/脱敏/进程管理 | 已按 ADR-0003 Phase 1 重写：`killOccupy5037Process` 改用 `core/process_utils.py`（psutil 端口查找 + 进程树终止），删除三处 `shell=True` 与 netstat/tasklist/taskkill 拼接；`ADBInputSession` 已纳入 ProcessRunner 跟踪；授权设备实机验证待确认 | Closed |
| High | Monkey 设备超时/断线检测与 CommandRunner 语义不匹配，可能无限运行 | `models/adb_testing.py::run_monkey_test_async`；`models/base/command_runner.py::run` | 任务无法结束、进程/线程/日志持续占用，UI 状态错误 | 前台探测失败/超时/空结果 fail-closed，连续 3 次终止并清理；等待阶段用 `_wait_for_monkey_abort` 短轮询探测中止；已补真实结果语义测试 | Closed |
| High | `confirm_dangerous_ops` 未接入危险命令入口 | `core/dangerous_ops.py`；`gui/main_frame.py`；`gui/dialogs/app_manager.py` | 用户误以为已开启保护，高影响动作仍直接执行 | 已知主面板/Controller 信号和 App Manager 动作已统一确认；未来新增入口必须注册策略并补测试 | Closed |
| High | 自动清理和 Release 重建可能以过大权限删除 workflow、Release 和 tag | `.github/workflows/Auto-Clean.yaml`；`.github/workflows/Build-exe.yaml` | 供应链或误配置破坏交付资产 | 已改只读 Retention Audit、最小权限、固定 action SHA 和不可变 Release，并有契约测试 | Closed |
| High | DeviceStore 写盘非原子且锁范围不覆盖 save | `models/device_store.py::load/save/upsert_devices` | 并发设备刷新/连接可能丢更新或产生损坏 YAML，崩溃可截断文件 | 已实现同锁域快照、临时文件 fsync + `os.replace`、损坏备份恢复和并发/故障测试 | Closed |
| High | AppManagerWorker 多条路径忽略 ADB 失败并继续报告成功 | `models/app_manager_worker.py` 的备份 pull、恢复 install、权限修改、列表/详情路径 | 备份不完整、恢复未发生、权限未修改但用户收到成功提示，可能导致数据丢失 | 已检查关键 CommandResult、失败停止/汇总并使用 staging；manifest/hash 与实机恢复仍待后续 | Partial |
| High | Controller 用共享字段管理同类操作，重叠批次/录屏可能串台 | `controllers/_base.py::_batch_trackers/_pending_ops`；`controllers/_media.py::_record_info` | 多设备或快速重复操作产生错误进度、错误路径、状态覆盖和内存增长 | Screenshot 已通过 OperationManager Gate A；安装批次已通过 InstallBatchUseCase Gate C（提交预留/所有权/generation 边界）；录屏与卸载/清数据/重启/当前 Activity 仍待迁移 | Partial |
| High | MainFrame 关闭链曾同步等待扫描、Remote、Controller 和 tracked processes | `gui/main_frame.py::closeEvent`；`gui/panels/remote_panel.py::shutdown`；`controllers/_base.py::shutdown` | 关闭窗口时事件循环可停顿数秒，多个资源 deadline 叠加 | Gate B2 已实施：两阶段异步关闭（broadcast-first、共享 wall-clock deadline、后台 finalizer、residual snapshot），`test_phase2_mainframe_shutdown_gate.py` 11 项契约测试通过；真实设备 helper 进程树集成验证待确认 | Closed |
| Medium | Remote 动态 `scrcpy_*` 设置写入后不会被白名单加载器恢复 | `core/settings_manager.py::_load`；`gui/panels/remote_panel.py` | 用户重启应用后 Remote 参数丢失，UI 与 JSON 表象不一致 | 已通过 `SCRCPY_SETTING_DEFAULTS` 白名单并入 DEFAULTS 并补持久化测试 | Closed |
| Medium | Release job 删除同版本 Release/tag，并自动清理旧 releases/runs | `.github/workflows/Build-exe.yaml::Create Release` | 重跑可能改写已经发布的版本；回溯性和制品可验证性降低 | 已改为存在 Release/tag 即失败，且没有自动 prune/delete | Closed |
| Medium | README 描述多个已不存在的旧性能模块和测试文件 | `README.md` 性能章节/项目结构；缺失 `models/performance/`、`gui/performance_web/`、旧 dialogs、`tests/test_performance_services.py` | 新成员误判架构、执行无效路径、修改错误模块 | 以本知识库为准并修正 README；提交检查验证文档路径 | Open |
| Medium | AppSettings 早期 `_data`/debounce 无锁，Timer 保存可与后续 set/reset 交错 | `core/settings_manager.py::set/reset/_save_atomic` | 丢设置、写入非预期快照；低概率关闭竞态 | 已用 RLock 保护数据/计时器/快照并以独立写锁串行保存，close 时取消计时器并同步 flush；仍有跨进程无文件锁限制 | Closed |
| Medium | `LogService` 曾在初始化时清除 root logger handlers，并把 DEBUG 发送到运行界面 | `core/log_service.py`；`gui/panels/log_panel.py` | 第三方日志丢失，内部诊断污染用户界面 | 已改为命名 logger、源码 stderr DEBUG、界面二次过滤和停止态晚到日志拒绝；新增缓冲溢出丢弃计数治理突发 | Closed |
| Medium | 用户可执行任意设备 shell/intent，输入校验与端口/PID/namespace/value 校验不统一 | `gui/panels/system_panel.py`、`controllers/_input.py/_file.py/_system.py`、`models/adb_system.py` | 误操作设备、注入设备 shell 复合命令、配置非法状态 | 明确高级模式；危险确认；结构化参数和范围校验；`utils/adb_values.py` 白名单已覆盖包名/dumpsys 服务名等诊断参数；审计日志脱敏 | Open |
| Medium | `ADBApp.get_current_activity_async()` 在命令失败/无结果时仍可能返回 success | `models/adb_app.py::get_current_activity_async` | UI/上层把未知前台 Activity 当成功，掩盖断线或权限问题 | 传播真实 CommandResult；无解析结果返回明确失败/unknown | Open |
| Medium | 录屏 pull 成功但远端清理失败时整体返回失败 | `models/adb_advanced.py::pull_recorded_video_async` | 用户误以为本地视频无效并重复操作；状态不精确 | 分离 pull 与 cleanup 状态，成功保留 local_path 并给 cleanup warning | Open |
| Medium | MobilePerf 使用类级 RuntimeData、多原生线程、`os.chdir` 和 `os._exit`，停止/落盘边界脆弱 | `mobileperf/android/globaldata.py`、`report.py::Report.__init__`、`startup.py::stop` | 报告不完整、线程来不及退出、全局状态污染；当前靠子进程隔离 | 引入实例上下文和结构化 shutdown/join；移除 chdir/_exit；做长跑故障测试 | Open |
| Medium | 结果目录可能保存设备标识、日志、bugreport、heapdump、截图等，未见加密/保留策略 | `StartUp.save_device_info/pull_*`、各媒体/诊断导出、LogService | 隐私、商业数据和设备数据在本机长期残留 | 数据分类、导出告知、默认保留期/清理、最小日志、目录权限与可选加密 | 待确认 |
| Medium | 响应式重做后 `gui/main_frame.py` 曾约 2,500 行 | `gui/main_frame.py`（拆分前 2,489 行） | 组合根继续膨胀，信号接线/关闭清理难以审查，回归成本高 | 已按 ADR-0003 Phase 2 拆出 `gui/main_frame_toolbar.py`（工具栏）、`gui/secondary_windows.py`（二级窗口托管）、`gui/close_controller.py`（异步关闭状态机），MainFrame 降至约 1,700 行并保留同名委托 wrapper；全量 940 项通过 | Closed |
| Medium | 全量 pytest 约 940 项、约 12 分钟，门禁时长偏高 | `tests/`；`tests/test_responsive_panels.py` 等几何扫描文件 | 提交/CI 反馈慢，降低门禁执行意愿 | 已把响应式几何扫描防抖降到 1ms（单文件 6min→1.5min）；已按 ADR-0003 Phase 0 引入 unit/ui/integration marker 与 CI `-m "not ui"` 快速子集（本地约 16 秒/458 项）；`wait_until` deadline 放宽到 6000ms 后全量顺序无关稳定通过；`test_model_execution.py` 已按 Phase 2 拆为 10 个主题文件 | Partial |
| Medium | CI 仅 Windows 跑完整 pytest，macOS/Linux 不验证 GUI/Remote 实际功能 | `.github/workflows/Build-exe.yaml` | 跨平台制品可能构建成功但运行/功能失败 | 至少跑非 GUI 全套单测、启动冒烟和 PATH scrcpy 降级测试；保留平台声明 | Open |
| Low | `BatchOperationTracker` 没有内部锁 | `utils/batch_tracker.py` | 与 Controller 共享 tracker 并发更新时计数可能不一致 | 已加内部锁、一次性 summary 和部分失败整体失败语义；剩余 tracker 路径后续迁入 OperationContext | Closed |
| Low | `ProcessRunner` 模块说明和 README 宣称所有 Popen 统一，实际存在例外 | `models/base/process_runner.py`、`README.md`、`core/adb_bridge.py`、MobilePerf | 维护者误以为 shutdown 能覆盖全部进程 | 修正文档并建立 subprocess lint/例外清单 | Open |
| Low | ruff.toml 为 `mobileperf/**` 豁免 E402/UP031、`tests/live_logcat_close_probe.py` 豁免 E402 | `ruff.toml::[lint.per-file-ignores]` | 豁免区域脱离 lint 门禁，违规样式会继续积累 | Phase 1 已删除 14 个文件的 sys.path 引导块（E402 清零）并转换 %-格式化（UP031 清零），`mobileperf/**` 豁免已移除；仅保留探针脚本 E402 豁免 | Closed |
| Low | Pillow、psutil 已锁定版本但一方源码未发现导入 | `requirements.txt`；导入扫描 | 构建面与供应链面略大于实际需要 | psutil 已由 `core/process_utils.py` 实际使用（ADR-0003 Phase 1），确认可从本条目移除；Pillow 仍需确认间接使用或移除；评估清理 `mobileperf/setup.py` 遗留的 `requests` 描述 | 待确认 |
| Low | Git 历史近期只有一个作者标识活跃，核心热点知识集中 | 244 提交的 author/hotspot 分析；`main_frame.py` 等 | 维护连续性和评审独立性降低 | 使用本知识库、CODEOWNERS/双人评审、模块化测试与交接 | 待确认 |
| Closed | 邮件服务（`core/mail/`、邮件获取入口、邮件/验证码信号、requests/ruamel 依赖）已整体移除 | `git show 70be33e`；`requirements.txt` | 不再有外部邮箱 API 面、凭据处理或日志扩散面 | 代码侧已闭环；Git 历史中曾跟踪的邮件配置仍须由仓库所有者轮换、停止跟踪并审查历史（保留提醒） | Closed |

## 历史维护热点

全历史高频变更/修复文件包括 `gui/main_frame.py`、`models/adb_model.py`、`gui/dialogs/app_manager.py`、`gui/dialogs/screenshot_viewer.py`、`gui/panels/remote_panel.py`、`resources/app_settings.json`，以及已经删除的旧 `controllers/adb_controller.py`、`gui/widgets/py_panel/left_panel.py` 和 `core/mail/`。修改这些区域时应先追踪现有调用链和测试，避免重新引入旧架构耦合。

## 修复优先顺序

1. MobilePerf 执行层重构（shell=True/5037 端口处理）与 E402/UP031 豁免移除。
2. MainFrame 大文件拆分（screen_adapter 之后继续）；Gate B2 异步关闭已完成，剩余真实设备 helper 进程树集成验证。
3. AppManager manifest/hash 与实机恢复验证；Controller 剩余 `_batch_trackers` 路径迁入 operation 边界。
4. 录屏 pull/cleanup 状态分离与 `get_current_activity_async` 结果真实性。
5. README 漂移修正、Pillow/psutil 依赖确认与全量套件耗时预算。
6. MobilePerf 停止协议与 `os._exit`/`os.chdir` 的中期重构。
