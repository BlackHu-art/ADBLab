# AppSettings 保存生命周期设计

日期：2026-10-24。状态：已完成实施、独立任务审阅与最终综合审阅。用户已授权自主持续重构与并行工作，不重复请求批准。

## 目标与边界

修复已经确定性复现的资源归属缺口：旧 Timer 进入保存后被新 Timer 替换，关闭收尾只取消最新引用，返回后旧线程仍可能写入。AppSettings 必须拥有全部未退出 Timer 和已准入同步写入；关闭返回表示这些工作都已结束。保存失败不覆盖原文件，不丢弃待重试快照。

只修改保存生命周期、关闭消费者及对应测试隔离。不搬 schema/migrations，不改变默认值、schema 版本、JSON 格式、迁移顺序、用户路径、原子替换、未来版本字段保留或 UI 外观。不新增依赖、线程池、Qt Timer、跨进程锁或后台常驻 writer；不提交、不推送、不访问真实用户数据或设备。

## 改造前的真实依据

- [manager](../../../core/settings_manager.py) 的 `_schedule_save()` 只持有 `_save_timer`，在锁外启动；`cancel()` 不等待已进入回调。`_save_atomic()` 的写锁后快照规则有效，必须保留。
- [关闭协调器](../../../gui/close_controller.py) 的 `_flush_shutdown_state()` 当前直接访问上述私有字段，finalizer 看不到旧 Timer。
- [ThreadedShutdownTask](../../../adblab/application/supervision.py) 的 `_run()` 忽略回调返回值，只记录异常。真实代码在 `adblab/application/`，没有 `adblab/tasking/` 目录。
- [共享 fixture](../../../tests/conftest.py) 已取消并 join 最新 Timer，且先销毁主题订阅者、投递 DeferredDelete，再恢复主题；不能描述为所有 fixture 都没有 join。缺口是被替换的旧 Timer 和局部 fixture。
- [MainFrame](../../../gui/main_frame.py) 将 `BaseStyles.theme_changed` 长连接到 `_on_theme_changed()`；该槽当前无 `_closing` guard，关闭协调器也未断开它。实际关闭先保存布局，再设置 `_closing=True`，停止 UI 生产者，最后后台保存。系统主题信号在窗口销毁前仍有到达机会。
- SettingsPage `prepare_shutdown()` 停止强调色 Timer 并在 finalizer 前保存最后 pending 值；不能把 owner 关闭提前到 UI 准备前。启动 writeback 由 [StartupTask](../../../gui/startup_task.py) 持有，取消不等于 I/O 退出。

当前审计记录在 `.superpowers/sdd/2026-10-23-project-refactor/settings-core-audit.md`，包含真实 Timer 和合成路径复现及当时 72 项设置测试基线。本设计重新核对代码，但不把历史测试数当成本轮通过结果。

## 方案比较与裁定

1. **保留 Timer，完善 owner 和终止屏障（选定）**：保留 500ms 防抖、daemon 属性及现有锁后快照；登记全部 Timer，保存准入计数和关闭串行锁。范围最小，现有线程模型不变。
2. 单一常驻 writer：所有权直观，但新增唤醒、空闲退出、启动失败和排队协议，扩大本次缺陷修复，暂不采用。
3. 只给最新 Timer 加 join：不能等待已被替换的旧线程，不能解决同步写入排队和 start/close 竞争，排除。

关闭后策略也比较了两种：允许更新内存但禁止自动保存，可以避免槽异常，却使复用 owner 看似成功而不持久化，并引入代次和重复 close 保存新值的复杂性；本阶段不采用。主任务裁定采用**严格终止**：关闭后的修改显式失败，并在已确认的主题槽补关闭 guard。正常 fixture 的销毁顺序已正确，不靠放宽 owner 语义照顾不存在的 fixture 路径。

同一个 AppSettings 被关闭后不自动重开，也不清空全局单例。真实主窗口关闭本来就是应用级停止，第二个仍在运行的 MainFrame 共享全局资源不是本阶段新增支持的运行模式。跨测试的共享 QApplication 保留，每个真实设置用例在排空旧 owner 后建立新 owner；同一测试需要模拟重启时显式切换 owner，不复用已关闭实例。

## 冻结接口

只新增同步、非 Qt 的 `AppSettings.close(self) -> bool`。没有运行时消费者需要通用 `flush()`，本阶段不新增该 API；现有 `_save_atomic(*, deferred_only: bool = False) -> bool` 私有兼容入口保留，测试仍可覆盖原子写规则。

| 接口 | OPEN | CLOSING / CLOSED |
| --- | --- | --- |
| `get()` 与只读属性 | 原行为 | 继续可读，不隐式重开 |
| `set/update/set_many/reset` | 原校验、返回值与保存时机 | 在变更数据前抛 `RuntimeError("AppSettings is closed")`；不更改数据、不启动 Timer、不写盘 |
| `_save_atomic()` | 原子准入，再串行写入，返回保存结果 | 返回 False，不排队写盘、不等待 close、不重新开放准入 |
| `flush_deferred_save()` | 无 pending 时 True 且不建文件；有 pending 时按原规则写，失败保留 pending | 一律 False，包括无 pending，表示终止 owner 拒绝请求；不新建文件 |
| `close()` | 原子封闭准入并冻结快照；排空工作后保存一次 | 并发调用等待前次 close；成功后幂等 True，不再写；失败后仅重试首次冻结快照 |

严格关闭检查在更新锁域内进行，空 mapping、只含 schema_version 的 update 也遵守已关闭检查；不允许以无实质变更为由暗中绕开终止契约。OPEN 时原校验与 schema_version warning 保持。reset 的数据修改与同步保存准入必须在同一锁域中线性化。

close 不带内部 timeout，不以 False 表示仍有线程残留。返回 False 只表示**工作已经排空，但冻结或最后保存失败**。线程/I/O 卡住时 close 继续阻塞，由已有 ThreadedShutdownTask/TaskSupervisor 共用应用 deadline 报 TIMED_OUT 和 shutdown_finalizer 残留；不能提前返回让监督器误认为 owner 已结束。该 API 只能从后台 finalizer、测试清理或无 GUI 的使用方调用，不在 GUI 主线程等待。

## 所有权与锁协议

AppSettings 是唯一所有者，生产实现保持在 manager 原文件。新增私有状态建议为 `_save_timers: set[threading.Timer]`、`_active_saves: int`、关联 `_lock` 的 Condition、`_close_lock`、终止标记、冻结快照和最近 close 结果。字段命名可按现有风格微调，不改变本节协议。

1. `_lock` 保护数据、准入、Timer 登记和活动保存计数；`_write_lock` 串行磁盘操作；`_close_lock` 只串行 close 调用，普通回调不获取它。
2. `_schedule_save()` 在 `_lock` 内检查准入、取消最新 Timer、登记新 Timer并调用 `start()`。标准 threading.Thread.start 不等待回调完成；回调在状态锁释放后进入保存。close 取同一锁，因此看不到已登记但未完成 start 的线程，不存在 join-before-start 或 close 后才 start 的窗口。
3. 已取消 Timer 仍保留登记；**不能在回调 finally 中删除登记**，因为 Python 线程此时尚未退出。新调度时可以裁剪 `is_alive() == False` 的已启动线程；close 在锁外 join 全部登记线程，join 返回后再移除。保留最新 `_save_timer` 作为防抖指针不等于资源集合。
4. start 失败必须撤销确实未启动的新 Timer，保留旧 Timer 归属和当前内存数据；不登记不可 join 的未启动对象。若异常时线程已真正启动，则保留其归属。保留既有错误可见性，不能伪造启动成功。
5. `_save_atomic()` 在 `_lock` 内完成准入和活动计数增加，之后才等待 `_write_lock`；finally 在 `_lock` 内减少计数并通知 Condition。排队但尚未取得写锁的同步保存也属于 owner。
6. reset 在同一 `_lock` 内校验 OPEN、修改数据、取消当前防抖 Timer、取得同步写入名额，锁外执行 I/O。update 的内存修改和调度检查也保持同一 RLock 线性化，避免修改接受后 close 已返回才创建 Timer。准入拒绝只发生在 mutator 的状态锁线性化点；已经接受的数据由 close 冻结快照覆盖，不能随后在调度/helper 中再抛 RuntimeError 谎称修改未接受。
7. close 取得 `_close_lock` 后，在 `_lock` 内设置终止标记、深拷贝最后已接受数据及版本/未来字段、取消全部 Timer并取集合快照；释放 `_lock` 后 join。之后通过 Condition 等待 `_active_saves == 0`，等待时释放状态锁。最后调用内部磁盘 helper 写冻结快照。
8. 任何 join、Condition 等待或 `_write_lock` 等待都不得持有回调需要的 `_lock`；close 不持有 `_write_lock` 等 Timer。公开保存准入包装与实际磁盘 helper 分离，只有 close 的内部路径可在终止后保存冻结快照，不增加可被普通调用方使用的 bypass 参数。
9. `_save_atomic()` 仍在取得 `_write_lock` 后取当前快照；既有已准入保存允许完成。close 冻结发生后不再接受公开修改，最后保存使用同一冻结内容，失败重试不从可变 `_data` 或外部嵌套对象重新构建。

close 不设计为从自己的 Timer 回调、写入函数或错误 sink 重入调用；这些调用链当前不存在。实施需避免在锁内调用会等待 owner 的外部回调，独立审阅检查这一边界。进程崩溃、强制退出、跨进程覆盖及 get 返回嵌套对象的直接外部修改仍是现有边界。

## 关闭、晚到通知和失败

`CloseController._flush_shutdown_state()` 改为 `settings_saved = AppSettings.instance().close()`，不访问 Timer 或私有写方法。False 时继续提交原有有界诊断并排空 run library，最后抛已有 RuntimeError，让 finalizer 报 FAILED。不能直接把 `settings.close` 用作忽略返回值的 finalizer callback。

`MainFrame._on_theme_changed()` 在入口以既有 `_closing` 状态拒绝已关闭窗口的通知，不触发设置或其后 UI 更新；OPEN 窗口主题行为保持。guard 只能挡当前窗口，不能以共享 settings 是否存在来丢弃正常主题动作。已有脏 MainFrame 差异必须保留。布局与最后强调色保存仍先于 settings.close，不批量修改其他设置调用者；如实测还发现晚到写入入口，先记录确定性证据再由主任务扩围。

磁盘写/replace 失败保持旧文件、内存值、冻结快照和必要 deferred pending；临时文件沿现有清理规则处理。已成功保存清除 deferred pending 的原语义不变。关闭失败之后不重新开放修改；重试 close 写首次冻结快照，成功后后续 close 不再执行 I/O。

实施时补充确认：运行时 Any 值可能拒绝 deepcopy。冻结异常也必须先封闭、取消、join及排空，再记录
异常类型并返回 False；没有有效冻结快照时，后续 close 继续 False，不从已封闭的可变数据重新取值。
此异常不能绕过资源屏障或以 None 触发普通保存。schema_version 的外部 warning sink 在状态锁外调用，
保留原诊断且避免外部回调与关闭等待形成锁循环；两条边界均有新增直接红绿回归。

## 测试隔离与兼容

共享 `isolated_app_settings`、局部 `isolated_settings` 及本阶段手工单例切换测试，均在路径和单例恢复前调用真实 owner.close。不能只清理当前 `_instance`：同一测试创建多个 owner 时必须逐个排空，且模拟重启的旧 owner 在置 `_instance=None` 前关闭。关闭失败测试可以得到 False，但资源清理仍已完成；fixture 不把保存成功作为所有故障测试的额外断言。

现有 adb_client round-trip 测试在重建后仍修改旧 `settings`，应改为修改 `reloaded`，保持客户端校验断言而非放宽终止协议。FakeTimer 必须实现实际需要的 `start/cancel/join/is_alive`，不得用 `getattr` 默认成功绕过资源协议；真实退出断言由真实 Timer 回归负责。保留 `_save_timer` 作为已退出最新线程的兼容观测，不因新增集合删除现有收集探针对其退出状态的有效断言。混合 UI/纯逻辑选择不变，新增纯生命周期测试不引入 Qt。

其余单例替换按真实资源扩围：`test_model_device.py::test_app_settings_load_migrates_legacy_settings_file` 只同步加载/迁移，没有 Timer；`test_monkey_library.py::test_prepared_metadata_uses_versions_and_seed_does_not_enter_global_settings` 明确禁用调度、同步写后才重建。本轮不机械改动这两处，不把所有 `_instance=None` 都当作相同竞态。

关键回归：旧 Timer 替换后 close 等待；已取消但 callback 返回前/线程退出前仍等待；start/close 竞争；reset、deferred、私有同步保存等待写锁时 close 仍等待；并发和重复 close；磁盘失败后重试冻结快照；关闭后所有公开修改显式拒绝；真实主题信号对 closing 窗口无写入、OPEN 窗口正常；fixture 恢复合成 sentinel 后不存在旧写；finalizer 超时仍报告残留且 GUI heartbeat 继续。

## 实施与验证边界

生产边界紧耦合，由一个 owner 顺序实现 manager、关闭消费者、最小主题 guard、对应测试和事实文档；不为并行拆分这组锁协议。其他 agent 可继续独立后续审计，但不同时写这些文件。具体节点、文件所有权和验收命令见[实施计划](../plans/2026-10-24-settings-save-lifecycle.md)。

设计阶段只检查文档。实施阶段从新增直接回归扩大到设置持久化、字体设置、关闭/归档库、收集隔离及启动 deferred 消费者；不因持续任务或已有大量脏文件触发全量。未触及资源、依赖或启动接线，不默认运行 packaging self-check、PyInstaller 或实机。最终报告区分合成真实线程、离屏 Qt 与真实桌面关闭边界。
