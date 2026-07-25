# 风险与技术债

下表按严重程度和影响排序。前 10 项是本次审计的最高优先级；“Open”表示尚未修复，
“Partial”表示代码侧已止血但仍有所有者或实机动作，“Closed”表示本阶段代码与自动测试已闭环，
“待确认”表示影响或运行条件需要额外实测。知识库不记录任何敏感配置具体值。

| 等级 | 风险 | 证据位置 | 影响 | 建议 | 状态 |
| --- | --- | --- | --- | --- | --- |
| Critical | 历史跟踪的邮件配置疑似含敏感请求材料；运行时代码此前还会记录账号、正文、验证码、请求/响应和指纹 | `core/mail/mail.yaml`；`core/mail/email_service.py`；`core/mail/email_task.py` | 凭据/个人数据泄露、第三方服务滥用、日志二次扩散 | 代码已迁移到用户域配置、强制 timeout 并脱敏；仓库所有者仍须轮换材料、停止跟踪并审查 Git 历史 | Partial |
| High | 自动清理和 Release 重建可能以过大权限删除 workflow、Release 和 tag | `.github/workflows/Auto-Clean.yaml`；`.github/workflows/Build-exe.yaml` | 供应链或误配置破坏交付资产 | 已改只读 Retention Audit、最小权限、固定 action SHA 和不可变 Release，并有契约测试 | Closed |
| High | `confirm_dangerous_ops` 未接入危险命令入口 | `core/dangerous_ops.py`；`gui/main_frame.py`；`gui/dialogs/app_manager.py` | 用户误以为已开启保护，高影响动作仍直接执行 | 已知主面板/Controller 信号和 App Manager 动作已统一确认；未来新增入口必须注册策略并补测试 | Closed |
| High | MobilePerf 遗留 ADB 层直接使用 `shell=True`，含查询和强杀占用 5037 端口进程 | `mobileperf/android/tools/androiddevice.py::get_adb_path/killOccupy5037Process` | 命令注入面、错误杀进程、绕过主应用超时/脱敏/进程管理 | 以参数数组和 psutil/系统 API 重写；禁止拼接 PID；接入统一执行抽象 | Open |
| High | Monkey 设备超时/断线检测与 CommandRunner 语义不匹配，可能无限运行 | `models/adb_testing.py::run_monkey_test_async`；`models/base/command_runner.py::run` | 任务无法结束、进程/线程/日志持续占用，UI 状态错误 | 前台探测失败/超时/空结果 fail-closed，连续 3 次终止并清理；已补真实结果语义测试 | Closed |
| High | DeviceStore 写盘非原子且锁范围不覆盖 save | `models/device_store.py::load/save/upsert_devices` | 并发设备刷新/连接可能丢更新或产生损坏 YAML，崩溃可截断文件 | 已实现同锁域快照、临时文件 fsync + `os.replace`、损坏备份恢复和并发/故障测试 | Closed |
| High | AppManagerWorker 多条路径忽略 ADB 失败并继续报告成功 | `models/app_manager_worker.py` 的备份 pull、恢复 install、权限修改、列表/详情路径 | 备份不完整、恢复未发生、权限未修改但用户收到成功提示，可能导致数据丢失 | 已检查关键 CommandResult、失败停止/汇总并使用 staging；manifest/hash 与实机恢复仍待后续 | Partial |
| High | Controller 用共享字段管理同类操作，重叠批次/录屏可能串台 | `controllers/_base.py::_batch_trackers/_pending_ops`；`controllers/_media.py::_record_info` | 多设备或快速重复操作产生错误进度、错误路径、状态覆盖和内存增长 | Screenshot 已通过 OperationManager Gate A；安装批次与录屏继续按 operation id/context 迁移 | Partial |
| High | MainFrame 关闭链仍同步等待扫描、Remote、Controller 和 tracked processes | `gui/main_frame.py::closeEvent`；`gui/panels/remote_panel.py::shutdown`；`controllers/_base.py::shutdown` | 关闭窗口时事件循环可停顿数秒，多个资源 deadline 叠加 | LiveLogcat B1 已移出 GUI wait；B2 需异步 close 状态机和应用级 broadcast-first deadline | Open |
| High | 邮件配置曾位于源码目录且运行时尝试写回 | `core/mail/email_service.py::mail_config_path/_load_mail_config` | 打包功能不可用或只读安装目录写入失败 | 运行时已迁移到用户目录/环境注入且不再写回；真实服务和打包功能路径仍待验证 | Partial |
| Medium | Remote 动态 `scrcpy_*` 设置写入后不会被白名单加载器恢复 | `gui/panels/remote_panel.py::_save_setting/_save_preset`；`core/settings_manager.py::_load` 只遍历 `DEFAULTS` | 用户重启应用后 Remote 参数丢失，UI 与 JSON 表象不一致 | 把合法键加入 schema/defaults 或支持带前缀的受控动态键；补跨实例持久化测试 | Open |
| Medium | README 描述多个已不存在的旧性能模块和测试文件 | `README.md` 性能章节/项目结构；缺失 `models/performance/`、`gui/performance_web/`、旧 dialogs、`tests/test_performance_services.py` | 新成员误判架构、执行无效路径、修改错误模块 | 以本知识库为准并修正 README；提交检查验证文档路径 | Open |
| Medium | Release job 删除同版本 Release/tag，并自动清理旧 releases/runs | `.github/workflows/Build-exe.yaml::Create Release` | 重跑可能改写已经发布的版本；回溯性和制品可验证性降低 | 已改为存在 Release/tag 即失败，且没有自动 prune/delete | Closed |
| Medium | AppSettings debounce 和 `_data` 没有锁，Timer 保存可与后续 set/reset 交错 | `core/settings_manager.py::set/reset/_save_atomic` | 丢设置、写入非预期快照；低概率关闭竞态 | 用 Qt timer 或单写线程；锁/快照；close 时 cancel+同步 flush | Open |
| Medium | `LogService` 曾在初始化时清除 root logger handlers，并把 DEBUG 发送到运行界面 | `core/log_service.py`；`gui/panels/log_panel.py` | 第三方日志丢失，内部诊断污染用户界面 | 已改为命名 logger、源码 stderr DEBUG、界面二次过滤和停止态晚到日志拒绝 | Closed |
| Medium | 用户可执行任意设备 shell/intent，输入校验与端口/PID/namespace/value 校验不统一 | `gui/panels/system_panel.py`、`controllers/_input.py/_file.py/_system.py`、`models/adb_system.py` | 误操作设备、注入设备 shell 复合命令、配置非法状态 | 明确高级模式；危险确认；结构化参数和范围校验；审计日志脱敏 | Open |
| Medium | `ADBApp.get_current_activity_async()` 在命令失败/无结果时仍可能返回 success | `models/adb_app.py::get_current_activity_async` | UI/上层把未知前台 Activity 当成功，掩盖断线或权限问题 | 传播真实 CommandResult；无解析结果返回明确失败/unknown | Open |
| Medium | 录屏 pull 成功但远端清理失败时整体返回失败 | `models/adb_advanced.py::pull_recorded_video_async` | 用户误以为本地视频无效并重复操作；状态不精确 | 分离 pull 与 cleanup 状态，成功保留 local_path 并给 cleanup warning | Open |
| Medium | MobilePerf 使用类级 RuntimeData、多原生线程、`os.chdir` 和 `os._exit`，停止/落盘边界脆弱 | `mobileperf/android/globaldata.py`、`report.py::Report.__init__`、`startup.py::stop` | 报告不完整、线程来不及退出、全局状态污染；当前靠子进程隔离 | 引入实例上下文和结构化 shutdown/join；移除 chdir/_exit；做长跑故障测试 | Open |
| Medium | 结果目录可能保存设备标识、日志、bugreport、heapdump、截图和邮件信息，未见加密/保留策略 | `StartUp.save_device_info/pull_*`、各媒体/诊断导出、LogService | 隐私、商业数据和设备数据在本机长期残留 | 数据分类、导出告知、默认保留期/清理、最小日志、目录权限与可选加密 | 待确认 |
| Medium | Python 依赖部分未固定，Pillow/psutil 在一方源码中未发现使用 | `requirements.txt`；导入扫描 | 构建不可复现、供应链面扩大、升级回归 | 锁定版本/哈希；拆运行/开发依赖；确认并移除未使用包 | Open |
| Medium | CI 仅 Windows 跑完整 pytest，macOS/Linux 不验证 GUI/Remote 实际功能 | `.github/workflows/Build-exe.yaml` | 跨平台制品可能构建成功但运行/功能失败 | 至少跑非 GUI 全套单测、启动冒烟和 PATH scrcpy 降级测试；保留平台声明 | Open |
| Low | `BatchOperationTracker` 没有内部锁 | `utils/batch_tracker.py` | 与 Controller 共享 tracker 并发更新时计数可能不一致 | 已加内部锁、一次性 summary 和部分失败整体失败语义；后续迁入 OperationContext | Closed |
| Low | `ProcessRunner` 模块说明和 README 宣称所有 Popen 统一，实际存在例外 | `models/base/process_runner.py`、`README.md`、`core/adb_bridge.py`、MobilePerf | 维护者误以为 shutdown 能覆盖全部进程 | 修正文档并建立 subprocess lint/例外清单 | Open |
| Low | Git 历史近期只有一个作者标识活跃，核心热点知识集中 | 244 提交的 author/hotspot 分析；`main_frame.py` 等 | 维护连续性和评审独立性降低 | 使用本知识库、CODEOWNERS/双人评审、模块化测试与交接 | 待确认 |

## 历史维护热点

全历史高频变更/修复文件包括 `gui/main_frame.py`、`models/adb_model.py`、`gui/dialogs/app_manager.py`、`gui/dialogs/screenshot_viewer.py`、`gui/panels/remote_panel.py`、`resources/app_settings.json`，以及已经删除的旧 `controllers/adb_controller.py` 和 `gui/widgets/py_panel/left_panel.py`。修改这些区域时应先追踪现有调用链和测试，避免重新引入旧架构耦合。

## 修复优先顺序

1. 邮件敏感配置/日志止血与轮换。
2. CI 清理权限和第三方 action 固定。
3. Monkey 无限运行、危险操作确认、DeviceStore 原子性。
4. AppManager 错误传播、Controller operation context。
5. Remote 设置持久化、README 漂移和依赖锁定。
6. MobilePerf 执行层/停止协议的中期重构。
