> 本文为最终独立 Agent 复核原文，由 Lead 汇入；单项复核原文另存 REMEDIATION_EVIDENCE.json。

# 修复包最终独立整体审阅

结论：在下述实际覆盖范围内，规格符合性通过，代码质量通过；没有发现新增 Critical / Important / Minor 必修问题。可以合入这批限定范围的本地修复，不代表已经提交、发布或完成实机与全平台验收。已有失败与受阻检查必须继续在交付报告中单列。

## 对象与执行边界

- 实际核对分支 `ui-design`、HEAD `574f0d2b39ae55ce126cb60db58cfefaa0d64a5e`，读取 `git status --short` 和当前目标差异；原有截图、design/reviews 未跟踪材料保留。
- 冻结包 `FINAL-review.diff` SHA256：`97809B7A0DC0570E939D939CA92AFDFAFF4302FE99CFC0C3D81A7F7A69750D29`；读取其文件索引及 changed-files.json（56 tracked + 4 new 测试），主要审阅依据为当前工作区生产差异、真实消费者和选定回归主体。
- 本席未运行测试、构建、设备命令、网络或安装器；未修改生产/测试/仓库文档，唯一写入本报告。没有派生 agent。
- 本席按所分配的整体最终审阅角色执行，未在工具中切换模型；模型路由由上层运行环境决定，不声称已自行升级模型。

## 实际已读规范和材料

实际读取根 `AGENTS.md`、`docs/README.md`，通过文件枚举未发现更近 AGENTS/override。读取 `.dsh/skills/adblab-architecture/SKILL.md`、`adblab-verify/SKILL.md`、`adblab-adb-boundaries/SKILL.md`、`adblab-ui-i18n/SKILL.md`。using-superpowers 的 SUBAGENT-STOP 明确排除本指定子任务。

读取 `docs/project-knowledge/ARCHITECTURE.md` 的分层、执行/监督、MobilePerf/Logcat 和应用关闭章节；`DATA_FLOW.md` 的设备存储相关内容及差异；`BUSINESS_FLOW.md` 的性能完成、任务归档、关闭与升级交接章节；`docs/guides/TESTING_GUIDE.md` 的增量验证、隔离、线程/Qt 测试与注释规则。长文整批输出有截断，之后对关键关闭/资源章节补充读取，未将未见章节计作完整通读。

读取 REMEDIATION_PLAN、FINDINGS 的对应缺陷与调用链、progress 的裁决记录、validation.json 的记录结构；B1-review-fix1 和 D2-review-fix1 用于对照已有修复意见，结论由源码及测试主体另行核对。未把旧 IMPLEMENTATION 当作验收依据。

## 跨模块核对结果

1. **错误终态与资源活性分开。** `core/tasks/supervision.py:196,292` 的已停止分支先读取 completion error，再决定是否移除；三个 stop 入口和重复 stop 保留 FAILED。`tests/test_task_supervision_completion.py:51,76,95` 分别断言错误保留、不重放停止动作及无错误对照；失败记录数量没有被报告成存活线程数量。

2. **默认 native 残留可达关闭消费者。** `core/native_process.py:146,380` 的应用集合和 run_native 私有 scope，在 finally 交还仍活跃的句柄；`core/adb_runtime.py` 兼容重导出指向同一集合。`core/exec.py:285-305` 的 active_count / wait_for_idle 实际读取它，CloseController 注册的 Controller/命令清理链继续消费该状态。超时不重放命令、不终止独立 ADB server；scope 的 owned/token 防止 communicate 与后续清理争用。

3. **失败 helper 与正常升级分流。** `core/installer_handoff.py:124-169` 的异常清理仅在 poll 确认退出后清句柄，reset_attempt 原先的活进程拒绝仍有效；Qt 适配器 is_running 包含 pending helper，wait 与线程 join 共享预算。`gui/close_controller.py:80-96,254` 确实登记该适配器并先执行 GUI 撤销。prepared/committed 例外保留正常跨父进程交接，失败通知不因活 helper 被无限拖后。COMMIT/nonce/父进程协议未被放松。

4. **Logcat 导出从准入到父树销毁闭环。** `gui/features/logcat/stream.py:551-646` 在模态前后复核对象与关闭状态、在 start 前登记同一 supervisor，并以 wait(0) 而非 finished 信号释放归属；`page.py:352` 经真实 registry 的 `gui/features/base.py:194` 注册消费者接入全局关闭。`lifecycle.py:238` 的页面释放同样等待 join。`gui/close_controller.py:472-550` 在停止/finalizer 后仅对真正的 QThread 继续非阻塞轮询，不重复 finalizer，不清除曾有 residual/失败，也不提前授权升级。该行为符合明确批准的 deadline 例外；不可合作 QThread 可让窗口保持 Closing，是已接受代价。

   实际读取 `tests/logcat_export_close_probe.py`：受控 QThread 隶属真实主窗口/页面，先确认 deadline 后仍未销毁，放行并 join 后观察两个 destroyed；外层测试 `tests/test_phase2_mainframe_shutdown_gate.py:653` 检查子进程退出码及 fatal Qt 输出。它证明的范围是合成导出与离屏本机窗口，不等于真实原生文件框或全平台。

5. **MobilePerf 三种状态没有混用。** `services/mobileperf_runner.py:151,177,188,200,421` 保留原 is_running，全部代次资源由 resource_contexts/residual 管理，最新报告由 latest_context 的真实线程活性决定。stop/读线程 join 使用共同剩余预算，未提交线程的义务在 start 异常时明确撤回；已提交线程仍有 owner。`gui/features/performance/page.py:783-940` 的监督和 dispose 使用全部资源谓词；`run.py:329` 对完成回调尾部恢复轮询，关闭时交由 dispose 轮询。已读双代 reader、当前代回调尾部门闩、零预算和提交失败回归主体；旧代未结束不污染新代报告，通知事件不替代线程 join。

6. **数据与归档兼容。** `models/device_store.py:57-100,229` 在持久化锁下建立路径保护，成功读/备份才解除；解析后取消重新保护且原样重抛，未发布的旧内存不能随后覆盖磁盘。`tests/test_device_store_concurrency.py:566` 的严格/容错 × 冷/热反例保留原字节断言。旧 YAML/IP 筛选和公开入口保持。`utils/archive.py:13` 抽出同一准入函数，`services/apps/archives.py:93` 在 staged 发布前使用它并再次检查取消；原大小、成员、比率及路径边界未放宽。

7. **局部用户行为与工程边界。** 实际读取数值 validator 工厂及 battery 动态重建差异，C locale + 字符白名单与后端 ASCII 格式一致；Monkey 单设备完成仅刷新剩余展示；非 Windows topmost 增加 Qt flag 更新并保存窗口状态，Windows 仍走原生分支。焦点解析兼容可选 u数字字段。Actions gate 先通过 YAML 结构枚举 jobs/steps 的 uses，再拒绝未支持引用和验证 SHA，不依赖版本注释来发现引用。构建 helper 用同一私有源码快照供编译和摘要，仍经过 staged verify/replace，ABA 不会把另一份编译输入认作原源码。

## 验证证据及 declined-to-judge

已实际读取 `LEAD-integrated-lifecycle-v2-1793204022248838000.log` 尾部：283 passed、110 warnings、58.35s。执行者是 Lead，不是本席；Lead 报告 exit 0。也读取 pristine HEAD 的 `LEAD-pyright-baseline.log`，看到 main_frame 两条和 androiddevice 三条共 5 个诊断。本席未重跑，也不把 Pyright 写成零错误。

Lead 报告本轮 Ruff、中文注释、source-text、diff 检查为零退出；六个旧 UI 断言已在 pristine HEAD 复现；CI 文件的环境受阻检查仍单列。这些执行结果部分来自 Lead 汇报，未在本席逐份重读全部日志。

明确不判断/不扩大结论：

- 没有逐行重读全部 60 文件约 195K 补丁，测试侧主要审查关键资源/取消/ABA/准入回归及夹具变化；未重新独立执行所有 A/E/F 单项验证。生产变更差异均已阅读，深层未改模块只沿上述消费者定点阅读。
- 未审完每一份 agent brief/report/review，未重复全仓审查；本报告是整包交互复核，不冒充全仓穷尽审计。
- 未验证真实 Android 多用户 FPS、备份安装、长时采集远端租约、真实失败升级 helper、原生文件框或 Linux/macOS 窗口管理器；受控替身和 Windows 离屏不能替代这些结论。
- packaging self-check 会触发真实外部 ADB 探测，与本轮禁止真实工具边界冲突，因此保留未执行/受阻；没有正式构建、产物验收或发布证据。
- 窗口树之外的 QThread 和普通 Python/process 残留仍遵循原有 owner/截止语义；本次末尾 QThread 屏障不是所有资源无条件归零的保证。

Critical：无新增确认项。Important：无新增确认项。Minor：无必须修改项。无需为风格、遗留私有辅助函数或已经批准的关闭代价追加改动；合入判断限于本地修复与如实保留上述验证限制。
