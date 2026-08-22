---
status: current
last_verified: 2026-08-21
owner: 待确认
related: [ARCHITECTURE.md, MODULE_MAP.md, DATA_FLOW.md]
---

# 风险与技术债

下表保留历次审计顺序，新增项按审计批次追加，因此不严格按严重度排序；应结合“等级”、“状态”
和文末优先顺序判断处理次序。“Open”表示尚未修复，
“Partial”表示代码侧已止血但仍有所有者或实机动作，“Closed”表示本阶段代码与自动测试已闭环，
“待确认”表示影响或运行条件需要额外实测。知识库不记录任何敏感配置具体值。

| 等级 | 风险 | 证据位置 | 影响 | 建议 | 状态 |
| --- | --- | --- | --- | --- | --- |
| High | MobilePerf 遗留 ADB 层直接使用 `shell=True`，含查询和强杀占用 5037 端口进程 | `mobileperf/android/tools/androiddevice.py::get_adb_path/killOccupy5037Process` | 命令注入面、错误杀进程、绕过主应用超时/脱敏/进程管理 | 已按 ADR-0003 Phase 1 重写：`killOccupy5037Process` 改用 `core/process_utils.py`（psutil 端口查找 + 进程树终止），删除三处 `shell=True` 与 netstat/tasklist/taskkill 拼接；`ADBInputSession` 已纳入 ProcessRunner 跟踪；授权设备实机验证待确认 | Closed |
| High | Monkey 设备超时/断线检测与 CommandRunner 语义不匹配，可能无限运行 | `models/adb_testing.py::run_monkey_test_async`；`core/exec.py::CommandRunner.run` | 任务无法结束、进程/线程/日志持续占用，UI 状态错误 | 前台探测失败/超时/空结果 fail-closed，连续 3 次终止并清理；等待阶段用 `_wait_for_monkey_abort` 短轮询探测中止；已补真实结果语义测试 | Closed |
| High | `confirm_dangerous_ops` 曾未接入危险命令入口 | 已删除的 `core/dangerous_ops.py` | 用户误以为已开启保护，高影响动作仍直接执行 | 2026-08-19 按产品决定全局移除弹窗确认：主窗口/App Manager/文件删除/覆盖保存/Monkey 比例/设置重置/关闭采集等确认弹窗全部删除，危险操作直接执行并保留失败校验与日志；`core/dangerous_ops.py` 与 `tests/test_dangerous_ops.py` 已删除，`confirm_dangerous_ops` 键仅兼容保留 | Closed |
| High | 自动清理和 Release 重建可能以过大权限删除 workflow、Release 和 tag | `.github/workflows/Auto-Clean.yaml`；`.github/workflows/Build-exe.yaml` | 供应链或误配置破坏交付资产 | Auto-Clean 保持只读 Retention Audit；Build 发布后保留最新 5 个版本并删除更旧 tag/Release；现存同版本禁止覆盖，但被保留策略删除的历史版本只靠文档规则禁止复用，工作流没有持久版本登记；action SHA 与权限已有契约测试 | Partial |
| High | DeviceStore 写盘非原子且锁范围不覆盖 save | `models/device_store.py::load/save/upsert_devices` | 并发设备刷新/连接可能丢更新或产生损坏 YAML，崩溃可截断文件 | 已实现同锁域快照、临时文件 fsync + `os.replace`、损坏备份恢复和并发/故障测试 | Closed |
| High | AppManagerWorker 多条路径忽略 ADB 失败并继续报告成功 | `models/app_manager_worker.py` 的备份 pull、恢复 install、权限修改、列表/详情路径 | 备份不完整、恢复未发生、权限未修改但用户收到成功提示，可能导致数据丢失 | 已检查关键 CommandResult、失败停止/汇总并使用 staging；manifest/hash 与实机恢复仍待后续 | Partial |
| High | Controller 用共享字段管理同类操作，重叠批次/录屏可能串台 | `controllers/_base.py::_ADBControllerBase.__init__`；`adblab/application/install_batch.py::InstallBatchUseCase`；`adblab/application/device_batch.py::DeviceBatchUseCase`；`adblab/application/screen_record.py::ScreenRecordUseCase` | 多设备或快速重复操作产生错误进度、错误路径、状态覆盖和内存增长 | Screenshot 走 OperationManager；安装批次走 InstallBatchUseCase；卸载/清数据/重启/当前 Activity 走 DeviceBatchUseCase；录屏走 ScreenRecordUseCase；通用 `_pending_ops` 已删除。Controller 仍保留 `_batch_starts`、安装所有权/generation 与 Monkey 停止映射等专用编排状态 | Closed |
| High | MainFrame 关闭链曾同步等待扫描、Remote、Controller 和 tracked processes | `gui/main_frame.py::closeEvent`；`gui/panels/remote_panel.py::shutdown`；`controllers/_base.py::shutdown` | 关闭窗口时事件循环可停顿数秒，多个资源 deadline 叠加 | Gate B2 已实施：两阶段异步关闭（broadcast-first、共享 wall-clock deadline、后台 finalizer、residual snapshot），`test_phase2_mainframe_shutdown_gate.py` 11 项契约测试通过；真实设备 helper 进程树集成验证待确认 | Closed |
| Medium | Remote 动态 `scrcpy_*` 设置写入后不会被白名单加载器恢复 | `core/settings_manager.py::_load`；`gui/panels/remote_panel.py` | 用户重启应用后 Remote 参数丢失，UI 与 JSON 表象不一致 | 已通过 `SCRCPY_SETTING_DEFAULTS` 白名单并入 DEFAULTS 并补持久化测试 | Closed |
| Medium | Release job 曾覆盖同版本 Release/tag，现仍自动清理旧 Release/tag | `.github/workflows/Build-exe.yaml::Create Release/Retain latest 5 version tags` | 重跑可能改写已经发布的版本；回溯性和制品可验证性降低 | 现存同版本存在即失败；发布后自动删除超出最新 5 个的旧 tag 及对应 Release。删除后的历史版本缺少工作流级持久防复用登记，当前仅由版本规则禁止复用 | Partial |
| Medium | README 曾描述多个已不存在的旧性能模块和测试文件 | `README.md` 性能章节/项目结构 | 新成员误判架构、执行无效路径、修改错误模块 | 已修正 README（2026-08-19）：移除 `models/performance/`、`gui/performance_web/`、旧性能对话框、`core/mail/` 条目，目录树与服务拆分表同步 `services/`、`adblab/`；知识库为架构事实来源 | Closed |
| Medium | AppSettings 早期 `_data`/debounce 无锁，Timer 保存可与后续 set/reset 交错 | `core/settings_manager.py::set/reset/_save_atomic` | 丢设置、写入非预期快照；低概率关闭竞态 | 已用 RLock 保护数据/计时器/快照并以独立写锁串行保存，close 时取消计时器并同步 flush；仍有跨进程无文件锁限制 | Closed |
| Medium | `LogService` 曾在初始化时清除 root logger handlers，并把 DEBUG 发送到运行界面 | `core/log_service.py`；`gui/panels/log_panel.py` | 第三方日志丢失，内部诊断污染用户界面 | 已改为命名 logger、源码 stderr DEBUG、界面二次过滤和停止态晚到日志拒绝；新增缓冲溢出丢弃计数治理突发 | Closed |
| Medium | 用户可执行任意设备 shell/intent，输入校验与端口/PID/namespace/value 校验不统一 | `gui/panels/system_panel.py`、`controllers/_input.py/_file.py/_system.py`、`models/adb_system.py` | 误操作设备、注入设备 shell 复合命令、配置非法状态 | 明确高级模式；结构化参数和范围校验；`utils/adb_values.py` 白名单已覆盖包名/dumpsys 服务名等诊断参数；审计日志脱敏（弹窗确认已按产品决定全局移除，误操作防护依赖校验与日志） | Open |
| Medium | `ADBApp.get_current_activity_async()` 在命令失败/无结果时仍可能返回 success | `models/adb_app.py::get_current_activity_async` | UI/上层把未知前台 Activity 当成功，掩盖断线或权限问题 | 传播真实 CommandResult；无解析结果返回明确失败/unknown | Open |
| Medium | 录屏 pull 成功但远端清理失败时整体返回失败 | `models/adb_advanced.py::pull_recorded_video_async` | 用户误以为本地视频无效并重复操作；状态不精确 | 分离 pull 与 cleanup 状态，成功保留 local_path 并给 cleanup warning | Open |
| Medium | MobilePerf 曾使用类级 RuntimeData、多原生线程、`os.chdir` 和 `os._exit`，停止/落盘边界脆弱 | `mobileperf/android/globaldata.py`、`report.py::Report.__init__`、`startup.py::stop` | 报告不完整、线程来不及退出、全局状态污染；当前靠子进程隔离 | 已按 ADR-0004 实例化：RuntimeData 改每运行实例（元类代理兼容既有调用点）、12 处采集线程 daemon 化、移除 `os.chdir`（报告路径显式拼接）与两处 `os._exit`（结构化收口）；长跑/断线故障测试与实机验证待确认 | Closed |
| Medium | 结果目录可能保存设备标识、日志、bugreport、heapdump、截图等，未见加密/保留策略 | `StartUp.save_device_info/pull_*`、各媒体/诊断导出、LogService | 隐私、商业数据和设备数据在本机长期残留 | 数据分类、导出告知、默认保留期/清理、最小日志、目录权限与可选加密 | 待确认 |
| Medium | 响应式重做后 `gui/main_frame.py` 曾约 2,500 行 | `gui/main_frame.py`（拆分前 2,489 行） | 组合根继续膨胀，信号接线/关闭清理难以审查，回归成本高 | 已按 ADR-0003 Phase 2 拆出 `gui/main_frame_toolbar.py`（工具栏）、`gui/secondary_windows.py`（二级窗口托管）、`gui/close_controller.py`（异步关闭状态机），MainFrame 降至约 1,700 行并保留同名委托 wrapper；最近一次历史全量记录为 2026-08-21 的 961 项通过 | Closed |
| Medium | 最近一次全量记录为 961 项、约 6 分钟，门禁时长偏高 | `tests/`；`tests/test_responsive_panels.py` 等几何扫描文件 | 提交/CI 反馈慢，降低门禁执行意愿 | 已把响应式几何扫描防抖降到 1ms（单文件 6min→1.5min）；CI `-m "not ui"` 快速子集在 2026-08-21 collect-only 为 478/961 项，unit marker 当前选择 0 项；`wait_until` deadline 放宽到 6000ms；最近一次历史全量记录用时 350.61 秒，后续工作树仍需重跑验证 | Partial |
| Medium | CI 仅 Windows 跑完整 pytest，macOS/Linux 不验证 GUI/Remote 实际功能 | `.github/workflows/Build-exe.yaml` | 跨平台制品可能构建成功但运行/功能失败 | 至少跑非 GUI 全套单测、启动冒烟和 PATH scrcpy 降级测试；保留平台声明 | Open |
| Low | `BatchOperationTracker` 没有内部锁 | 已删除的 `utils/batch_tracker.py` | 与 Controller 共享 tracker 并发更新时计数可能不一致 | 批次计数与汇总已迁入带锁的 `DeviceBatchUseCase`（OperationManager 之上，ADR-0003 Phase 3），旧 tracker 模块与测试已删除 | Closed |
| Low | `ProcessRunner` 模块说明曾让维护者误以为所有 Popen 已统一 | `core/exec.py`、`README.md`、`core/adb_bridge.py`、`models/file_explorer_worker.py`、MobilePerf | 维护者误以为 shutdown 能覆盖全部进程 | ADR-0005 已把 ProcessRunner 迁入 `core/exec.py` 并统一树杀；ADBInputSession 与文件传输均已进入 ProcessRunner 跟踪，README 已收紧为主应用优先原则。剩余例外仅为 MobilePerf 内核的独立 Popen/ADB 执行边界 | Partial |
| Low | ruff.toml 为 `mobileperf/**` 豁免 E402/UP031、`tests/live_logcat_close_probe.py` 豁免 E402 | `ruff.toml::[lint.per-file-ignores]` | 豁免区域脱离 lint 门禁，违规样式会继续积累 | Phase 1 已删除 14 个文件的 sys.path 引导块（E402 清零）并转换 %-格式化（UP031 清零），`mobileperf/**` 豁免已移除；仅保留探针脚本 E402 豁免 | Closed |
| Low | 本地环境命名和依赖作用域不一致：遗留 `venv` 自行忽略，工具链固定 `.venv`，运行/构建依赖混装且测试目录可被外部同名包遮蔽 | `.gitignore`、`.pre-commit-config.yaml`、`requirements*.txt`、`tests/__init__.py` | 开发者误用系统 Python、测试收集失败、运行环境安装不必要构建包 | 根级忽略 `.venv/venv/env`，统一 `.venv`；拆分 runtime/build/dev 依赖、移除无引用 Pillow、显式声明 shiboken6，并增加测试包标记 | Closed |
| Low | 全量 pytest 偶发"测试全绿但进程退出异常"（退出挂起或 0xC0000005，约 10 次全量中出现 3 次） | `pytest` 全量套件收尾阶段 | 本地/CI 误报失败，浪费重跑时间 | 测试结果本身不受影响（进度条全绿）；怀疑为 Qt 延迟删除在解释器关闭期的环境级竞态；建议后续用 `-p no:cacheprovider` 对照或最小化探针定位后修复 | Open |
| Low | Git 历史作者标识较少，核心热点可能存在知识集中 | 2026-08-21、HEAD `a0344f3`：318 提交、4 个作者标识，近三个月 2 个标识活跃；`main_frame.py` 等 | 维护连续性和评审独立性降低 | 动态指标仅作快照；结合模块所有权确认风险，并使用知识库、CODEOWNERS/双人评审、模块化测试与交接 | 待确认 |
| High | 邮件服务（`core/mail/`、邮件获取入口、邮件/验证码信号、顶层 requests/ruamel 依赖）已整体移除 | `git show 70be33e`；`requirements.txt` | 不再有外部邮箱 API 面、凭据处理或日志扩散面 | 主应用代码侧已闭环，`mobileperf/setup.py` 的 requests/urllib3 遗留声明也已移除。Git 历史中曾跟踪的邮件配置仍须由仓库所有者轮换、停止跟踪并审查历史（保留提醒） | Closed |
| High | 设备 shell 动态值（path/host/uri/package/permission/action/component/ime/settings key/value/text）直接作为 `adb shell` 参数未 quote，任一值含 `;`/`$(…)`/`\|`/`&` 即触发设备端命令注入 | `models/adb_advanced.py:319,344,356,361`；`models/adb_network.py:97`；`models/adb_system.py:23-214,365`；`models/adb_app.py:57,68,78,157`；`controllers/_file.py:42`；`controllers/_system.py:77-293`；`controllers/_input.py:88,168-172` | 设备端命令注入、误操作设备；白名单 `utils/adb_values.py` 仅覆盖 package/dumpsys-service/tcp-port/geo | 专项审计（2026-08-21）I-1：在 model 边界统一 `shlex.quote` 或扩充白名单（path/host/uri/ime/permission/settings-key），对照 `services/file_explorer.py::shell_quote` 已有实现；修复后在授权真机做最小验证 | Open |
| Medium | 全局 `QThreadPool` 的 QRunnable 关闭时不统一等待/取消；Controller `ThreadPoolExecutor(4)` 会取消待运行 future，但 `wait=False` 不等待已运行任务，长命令（install 120s、bugreport 180s）仍可拖慢退出 | `models/adb_model.py::async_command/ADBModelCore.__init__`；`controllers/_base.py::_ADBControllerBase.shutdown` | 进程退出被拖到 timeout 上限 | 专项审计（2026-08-21）T-1/T-2：给 QRunnable 增加可等待句柄或在 shutdown 前 `waitForDone(短超时)`；对已运行 executor 任务增加协作式取消和有界收口 | Open |
| Medium | screenrecord 以 `stderr=PIPE` 启动且无消费线程，stderr 写满 64KB 管道会阻塞录屏进程 | `models/adb_advanced.py:60-71` | 录屏进程死锁 | 专项审计（2026-08-21）P-1：stderr 改 DEVNULL 或起排空线程；需实机验证 screenrecord stderr 量 | Open |
| Low | 设备信息把 `ro.serialno` 与 MAC 以 INFO 落用户日志与 app.log | `controllers/_device.py::_process_device_info_result`；`core/log_service.py::LogService._add_file_handler` | 违反"不记录真实设备唯一标识"约定 | 专项审计（2026-08-21）O-1：序列号/MAC 脱敏后展示，不落文件日志 | Open |
| Low | 专项审计（2026-08-21）A 组低风险 8 项：日志文件无轮转（O-2→RotatingFileHandler 2MiB×3）、设置防抖 Timer 锁外 cancel（T-5）、monkey 最大恢复 wait 无超时（T-7）、传输 EOF 忙等（P-3）、worker `_aborted` 布尔跨线程无同步（T-4→threading.Event）、logcat 导出非原子写（O-3→`utils/atomic_text.py`）、content_insert bind 未校验（I-4→冒号/空值拒绝）、`update_current_package` 闭包捕获 self（R-2→weakref） | `git show b8e2f47` | 命令注入结构破坏、半截文件、退出拖慢、忙等 CPU | 已修复并补测试（`test_atomic_text.py`、content_insert 校验用例）；其余审计项（I-2/I-3/T-3/T-6/C-1/C-2/R-3/P-2）见审计报告留待后续批次 | Closed |
| Medium | 降级版本加载未来 `AppSettings` schema 后，任一后续保存都会丢失未知的未来字段 | `core/settings_manager.py::_load/_save_atomic`；`tests/test_settings_persistence.py::test_future_schema_version_keeps_known_values_and_version` | 用旧版应用修改一项设置即可破坏新版本数据，与 ADR-0006 的降级兼容决策不符 | 已通过 `_future_extra` 在加载时缓存未知字段、保存时合并回写；`future_key` 在 update/save 后仍存在的回归断言已落地 | Closed |
| Medium | 非 Windows 源码运行时，ADB 解析器仍会优先选择仓库内 Windows `adb.exe` | `utils/adb_resolver.py::resolve_adb_path`；`utils/runtime_tools.py::bundled_tool_path`；`tests/test_runtime_tools.py::test_resolve_adb_path_prefers_runtime_tool_path` | macOS/Linux checkout 可能把 Windows PE 当作 adb 执行，设备功能直接失败；现有 CI 自检不覆盖该功能路径 | 在 resolver 中增加平台门控，非 Windows 直接解析 PATH `adb`；补 Linux/macOS 路径优先级契约测试 | Open |

## 历史维护热点

全历史高频变更/修复文件包括 `gui/main_frame.py`、`models/adb_model.py`、`gui/dialogs/app_manager.py`、`gui/dialogs/screenshot_viewer.py`、`gui/panels/remote_panel.py`、`resources/app_settings.json`，以及已经删除的旧 `controllers/adb_controller.py`、`gui/widgets/py_panel/left_panel.py` 和 `core/mail/`。修改这些区域时应先追踪现有调用链和测试，避免重新引入旧架构耦合。

## 建议修复优先顺序

以下仅对 Open/Partial/待确认项排序，最终优先级待负责人确认：

1. 统一校验或 quote 设备 shell 动态值，关闭命令注入面。
2. 收口全局 `QThreadPool`/Controller executor 关闭边界，并处理 screenrecord `stderr=PIPE`
   未持续排空的阻塞风险。
3. 补齐 AppManager manifest/hash 和授权实机恢复验证。
4. 为 Release 保留策略增加持久版本登记，避免已清理的历史版本被重新使用。
5. 分离录屏 pull/cleanup 状态，并修正 `get_current_activity_async` 的失败/无结果语义。
7. 完成 MainFrame/helper 进程树、MobilePerf 长跑/断线以及跨类型任务并发的授权
   实机集成验证。
8. 修正非 Windows 源码模式的 ADB 路径优先级，定位全量套件耗时与偶发 Qt
   解释器退出异常，再补齐 macOS/Linux 功能验证。
9. 建立设备标识脱敏及诊断/媒体导出数据的保留与清理策略。
