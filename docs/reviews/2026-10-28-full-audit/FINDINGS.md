# 审查发现

审查对象：`ui-design`，提交 `574f0d2b39ae55ce126cb60db58cfefaa0d64a5e`，应用版本 3.3.4。以下位置均指本次工作区原文件，未实施修复。P2 表示应安排修复的正确性问题，P3 表示较低影响或条件罕见的问题；优先级与验证状态独立。独立复核者为新上下文 R6；动态探针统一由 Lead 在临时目录执行。

## 已确认缺陷

### F01 — 未读且未备份的设备历史被后续保存覆盖

- 来源：R5-01；P2；分类：已确认缺陷／持久化数据保全；验证：临时真实文件故障注入复现，R6 确认；风险账本中未记录此具体链路。
- 位置与符号：`models/device_store.py:148` `_read_text_with_retry`、`:260` `_backup_corrupt_file`、`:291` `upsert_devices`、`:252` 原子替换。
- 触发：原有合法历史读取重试失败，同时备份复制失败；随后 I/O 恢复，新 IP 连接或概览补全触发保存。冷启动内存为空，热加载则可能持有过时快照。
- 预期及依据：读取失败不能导致未读、无备份的合法用户历史丢失；DeviceStore 的保留快照约定与相邻 AppSettings 未读文件保护体现这一要求。实际读取返回 None，备份异常被忽略，没有保护状态；下一次保存直接以不完整内存替换原文件。
- 调用链：`main.py:514` 启动加载 → `DeviceStore.load` → `controllers/_device.py:194,377,417` 连接／概览保存 → `_persist_snapshot` → `os.replace`。
- 已有防护与影响：持久化锁、重试、尽力备份、原子写有效避免并发和半文件，但无法恢复未读内容；可丢失合法 IP 历史。探针只使用合成地址和临时 YAML，未触及真实历史。
- 最小建议：保留未读且未备份状态；后续写入先安全重读合并或确认可靠备份，否则拒绝覆盖，继续允许内存设备展示。
- 验证：`data-handoff-probes` 中读／备份均注入 PermissionError，恢复后追加 new，原有 old 消失，断言失败。现有 `test_device_store_concurrency.py` 只覆盖备份成功的读取失败；补保护解除与恢复保存回归。

### F02 — 默认原生命令清理失败后丢失仍存活客户端

- 来源：R2-01；P2；分类：已确认缺陷／进程归属；验证：替身故障注入复现，R6 确认；新发现。
- 位置与符号：`core/native_process.py:299` `cancel_and_drain_native`、`:362` `run_native`；`core/exec.py:358` 执行分流、`:381` 默认调用、`:414` 失败返回及减计数；`:286` `active_count`。
- 触发：未带取消回调或 scope 的默认原生命令超时，kill/wait 仍失败或超时，直接客户端依然存活。
- 预期及依据：业务返回失败后仍须保留资源归属，应用关闭不得把未释放客户端算作空闲。实际 `run_native` 只持局部进程对象，finally 关闭管道；CommandRunner 减计数，没有转交 residual owner。
- 调用链：`models/adb_app.py:134` 安装 → `models/adb_model.py:236` `_run` → CommandRunner 默认分支 → `run_native`；`gui/close_controller.py:169` 依赖 active_count/wait_for_idle 收口。
- 已有防护与影响：返回 failed，不会伪报命令成功或重放安装；native_capture 的 scope 已登记残留，但默认分支不受此保护。可能留下本应用创建的客户端并低估关闭残留；不等同于独立 ADB server 后代管道问题。
- 最小建议：默认路径清理失败也转交现有残留监督，确认退出后解除；保留安装不响应取消、不重放的原契约。
- 验证：`native-cleanup-probe` 得到 `failed / still_alive=True / active_count=0 / idle=True`，资源不变量断言失败。替身不证明实机发生频率；后续应覆盖退出后解除与关闭门禁。

### F03 — 监督器把已失败结束的清理任务记作已停止

- 来源：R2-02；P2；分类：已确认缺陷／失败终态保留；验证：三个入口替身复现，R6 确认；新发现。
- 位置与符号：`core/tasks/supervision.py:198` `stop` 已停止分支、`:291` `_stop_selected` 已停止分支；`ThreadedShutdownTask:94` 先记异常再设置完成事件。
- 触发：进入 stop/stop_owner/stop_all 时任务已结束，但其 completion error 非空；或首次 FAILED 后再次请求停止。
- 预期及依据：任务退出只表示资源结束，不能抹去清理失败。实际已停止分支直接删除任务并返回 ALREADY_STOPPED／空错误；运行中等待结束的分支却正确保留 FAILED。
- 调用链：ThreadedShutdownTask 异常 → is_running=False、error_type 非空 → TaskSupervisor 停止入口 → 任务中心／关闭调用方。
- 已有防护与影响：CloseController 会保存首次失败及曾有 residual，现有升级门禁据此拒绝授权。因此不能推断正常一次关闭必然洗白失败或绕过升级门禁。本项确证的是监督器入口及重试时丢失错误证据。
- 最小建议：已停止分支同样检查 completion error，有错误返回 FAILED 并保留必要记录，区分无错误的已停止。
- 验证：`supervisor-probe` single/owner/all 三项预先失败任务均断言失败。首次 FAILED 后重试链仅静态确认，未作为已动态覆盖项；后续补此路径及正常已停止对照。

### F04 — 失败的升级握手遗忘仍存活的 helper

- 来源：R5-02；P2；分类：已确认缺陷／升级资源生命周期；验证：替身复现，R6 确认；新发现。
- 位置与符号：`core/installer_handoff.py:124` `_prepare` 异常清理、`:63` `reset_attempt`；`gui/adapters/installer_handoff.py:110` 活跃状态。
- 触发：握手失败、超时或取消，关闭 stdin 后 helper 在 5 秒内仍未退出。
- 预期及依据：失败尝试的活 helper 应继续有 owner，并阻止重试，直到确认退出。实际 wait 的 TimeoutExpired 被忽略，随后无条件 `_process=None`，重试保护失效；Qt 适配器只看准备线程。
- 调用链：QtInstallerHandoff.start → reset_attempt → prepare → `_prepare` 异常 → 清引用 → 下一次 start；关闭任务也只等待准备线程。
- 已有防护与影响：EOF、nonce、COMMIT、父进程正常退出和锁内摘要复验仍有效；没有证据表明可未授权安装或重复安装。确认影响是失败 helper 残留脱离监督、重试重叠。正常已授权 helper 需跨越父进程退出，不属于本项问题。
- 最小建议：未确认退出时保留失败 helper 句柄，作为 residual 阻止 reset；有界检查确认退出后释放。不要用业务授权撤销代替资源终态。
- 验证：`data-handoff-probes` 假握手超时及 wait 超时，观察 `retained=False / refused_retry=False / alive=True`，断言失败。现有测试只覆盖句柄尚在时的重试拒绝；补实际异常分支及随后退出场景。

### F05 — Logcat 导出线程没有进入全局关闭屏障

- 来源：R3-01；P2；分类：已确认缺陷／Qt 关闭资源归属；验证：离屏协调集成探针复现，R6 确认，原先 P1 崩溃推断降级；新发现。
- 位置与符号：`gui/features/logcat/stream.py:31` `LogcatExportWorker`、`:569` 创建／启动；`gui/features/base.py:194` 注册关闭任务；`gui/close_controller.py:471` 完成收口。
- 触发：Logcat 本地导出线程仍运行时关闭整个主窗口。
- 预期及依据：活动 QThread 的资源终态须在窗口退出前确认。实际导出是页面子线程但未注册 supervisor，Logcat 页无 register_shutdown_tasks；单页 dispose 会等待导出，全局关闭只等待 supervisor/finalizer，不等 registry 的 disposing 集合。
- 调用链：导出 → page 子 QThread → 主窗口注册 feature shutdown → 跳过 Logcat 导出 → host.shutdown 请求异步 dispose → supervisor 归零 → 主窗 close_ready。
- 已有防护与影响：单页 `_try_finalize_close` 正确检查 export_pending。全局关闭可能中断导出；活动 QThread 随父树销毁的原生崩溃是未验证风险，不宣称已复现。
- 最小建议：为导出资源登记全局关闭义务，或为页面提供等价 shutdown task；仅在实际线程结束后解除。
- 验证：`logcat-shutdown-probe-v2` 使用真实 registry/page/supervisor、现有测试 MainFrame 协调替身和受控 QThread，观察 `frame_close_ready=True / export_running=True / page_disposing=True / supervised_active=0`。finally 释放并 wait，无故意崩溃。完整真实窗口销毁仍待验证。

### F06 — 文件选择框返回后在已完成关闭协议的 Logcat 页面启动导出

- 来源：R3-02；P2；分类：已确认缺陷／关闭准入；验证：离屏模态返回替身复现，R6 确认；新发现，与 F05 根因不同。
- 位置与符号：`gui/features/logcat/stream.py:555` `_export`，`:561` 返回后准入，`:569` 创建线程；`gui/features/logcat/page.py:238` request_dispose。
- 触发：保存文件框期间页面完成 dispose，文件框随后返回有效路径。
- 预期及依据：页面结束后不能接纳新工作；Qt 模态事件循环可能处理关闭／页面切换。实际返回后仅检查路径和 export_in_progress，没有 closing/close_ready/对象有效性复核。
- 调用链：导出点击 → QFileDialog → dispose_ready／registry deleteLater → 对话框返回 → 创建并启动导出。
- 已有防护与影响：重复导出 busy 状态存在，但不能代替生命周期准入。可能在业务结束后新增工作；已删除 C++ 对象异常或原生崩溃未验证。
- 最小建议：打开前及返回后检查生命周期和对象有效性，关闭后放弃本次操作；保留文件选择取消语义。
- 验证：`logcat-dialog-probe` 真实页面、假文件框和假 exporter，观察 `page_closed=True / dispose_emitted=True / new_exports=1`，断言失败。不同平台原生文件框行为未实测。

### F07 — MobilePerf 的资源活跃状态遗漏排空中的 reader

- 来源：R2-03；P2；分类：已确认缺陷／资源终态建模；验证：静态链路及现有延迟 reader 测试确认，R6 降级影响范围；新增具体问题，关联既有长采集生命周期风险。
- 位置与符号：`services/mobileperf_runner.py:150` `is_running`、`:385` stop 清 `_proc`、`:756` 有界 join；`gui/features/performance/page.py:831` 监督谓词、`:913` dispose；`gui/features/performance/run.py:318` 收尾判断。
- 触发：子进程已退出，但 stdout/stderr reader 超过有界 join 仍在排空。
- 预期及依据：业务允许开始新采集与全部旧资源退出应分别表达。实际 is_running 只看 mode thread 和 `_proc`，页面监督／释放却把它作为全部资源终态。
- 调用链：stop → `_proc=None` → reader 有界 join → is_running=False → 页面 dispose／结果收尾；旧 daemon reader 后续仍工作。
- 已有防护与影响：`_maybe_notify_finished:681` 等待双 reader；代次隔离、弱引用和 QObject 有效性检查防旧结果串代。现有 `test_mobileperf_runner_concurrency.py:388` 明确允许旧 stderr 在 stop 返回、新代开始后继续结束。可能丢弃尾部回调，应用退出前未确认 daemon 排空；不能推断 XLSX 损坏、跨代污染或必然 Qt 崩溃。
- 最小建议：保留可重启业务状态，另将所有旧代 reader 纳入资源活跃／关闭监督谓词。
- 验证：现有并发测试在 `r2-direct` 通过，证明现有重启契约；未新增实际应用退出探针。后续用可控延迟双 reader 验证资源计数、页面释放和最后日志收口。

### F08 — 成功发布的 APK 备份不一定满足自身恢复准入

- 来源：Lead + R4-01；P2；分类：已确认缺陷／备份恢复契约；验证：临时合成归档往返复现，R6 确认；既有备份完整性债务的具体新问题。
- 位置与符号：`services/apps/archives.py:92` backup_app make_archive、`:98` 原子发布、`:140` restore_apps；`utils/archive.py:8` 大小／成员／压缩比上限、`:24` 检查。
- 触发：自制备份超过恢复的 512 MiB 总解压大小、10,000 成员或单成员压缩比 200 限制。
- 预期及依据：报告成功的本工具备份应满足本工具恢复接受策略。实际备份只核验拉取／数量，直接压缩发布并通知成功，恢复统一安全解压时拒绝。
- 调用链：`gui/workers/app_manager.py:295` backup → archives → ZIP 发布；`:304` restore → safe_extract_zip → 安装前拒绝。
- 已有防护与影响：串行拉取、取消检查、原子发布、每次写入前 Android 用户复核和安全解压均有效。问题是生产／消费政策不一致，不是 ZIP 防护过严本身；可能以不可恢复的新归档替换旧备份。
- 最小建议：发布前复用恢复接受策略检查，失败保留旧备份；若需更大范围另作产品决定，不取消安全检查。
- 验证：`archive-roundtrip-probe` 合成 ZIP 格式 APK 含 2 MiB 重复存储数据，外层 2,352 bytes，成员 2,097,418 bytes、ratio 约 937；备份成功、恢复拒绝、安装调用 0。样本不是签名可安装 APK，不推断真实设备发生率；大体积路径只静态确认。

### F09 — 非主 Android 用户的前台组件被解析成用户标记

- 来源：R4-02；P2；分类：已确认缺陷／性能指标与 Android 多用户；验证：纯解析夹具复现，R6 确认；既有厂商／实机矩阵风险中的具体新缺陷。
- 位置与符号：`mobileperf/android/tools/androiddevice.py:762` get_focus_activity、`:784` u0 特判、`:795` get_foreground_process；`mobileperf/android/fps.py:342,394` 窗口查询及匹配。
- 触发：窗口输出如 `mCurrentFocus=Window{abc u10 com.example.app/.MainActivity}`。
- 预期及依据：接口返回前台 Activity／窗口组件供 FPS 查询。实际只识别 u0，副用户返回 u10；gfxinfo 的真实 Window 精确匹配失败。
- 调用链：FPSMonitor → SurfaceStatsCollector → ADB.get_focus_activity → SurfaceFlinger／gfxinfo 目标窗口 → 无有效帧。
- 已有防护与影响：无效帧标记不可用并延后重查，不伪造零 FPS；u10 非空不抛异常，不能触发启动异常回退。普通窗口模式可能持续缺样；不扩大为所有指标或 legacy 全屏路径均失效。
- 最小建议：识别合法 u<数字> 可选字段并验证后续组件，兼容空焦点、旧格式、重复空格及短行。
- 验证：`data-handoff-probes` u0 对照通过、u10 断言失败。真实厂商输出和 FPS 端到端未验证；后续追加 fake gfxinfo 消费与授权多用户实机验收。

### F10 — 异步测试等待查询开始，未等待结果提交

- 来源：R1-01／R3e；P3（R3e 初报 P2，经 Lead／R6 降级）；分类：已确认缺陷／测试确定性；验证：静态时序证明，R6 确认，未复现随机失败；新发现。同类同步错误归档在同一条目，下面两组测试实现可独立修复。
- 位置与符号：`tests/test_model_ci_controller.py:564,608` 两个 metadata 测试；`controllers/_device.py:345` 并发查询与 as_completed 发布。
- 触发：第二个查询线程发出 second_started 时，父线程还没有调度到第一个结果的 emit。
- 预期及依据：断言第一结果已发布应等待发布事件，而非另一个并发任务开始。实际测试等待 second_started 后立即断言首个 emit，其中一个还随即使 topology 失效。
- 调用链：内部三槽查询池 → 第二任务 Event → 测试继续；父线程 as_completed → emit 与上述顺序没有保证。
- 已有防护与影响：finally 释放等待任务，避免挂死；外层单线程 executor 不限制内部池。可能造成 CI 偶发误报，未证明生产发布顺序缺陷。
- 最小建议：mock emit 设置 first_published Event，等待后再断言／失效；不添加 sleep 或放宽断言。
- 验证：后续用可控发布门闩确定性展示时序，不用大量重跑估计未经测量的失败概率。本轮没有运行这两个节点。
- 第二组位置／调用链：`tests/test_phase2_live_logcat_gate.py:846,869` 恢复过滤测试及 `:973,1018` 切包测试，在 PID 查询返回前设置 Event，等待事件后喂入唯一目标日志；`gui/features/logcat/worker.py:225–243` 要等查询返回后才提交 PID。独立 reader／消费线程可能先按空 PID 在 `:315–322,424–426` 丢弃日志，后续提交不重放，因此合法调度可使断言失败。
- 第二组反证／最小建议：初始 Alpha 在 `worker.py:375–390` 提交 PID 后才启动 reader，有顺序保护；同测试 `:1009` 已等待 PID 快照的轮换路径也有效。失败切包要求拒绝日志属于正确行为。只修恢复和切包测试的同步点，等待当前 package/generation 对应 PID 快照或 commit 完成事件；不加 sleep、不放宽断言。本轮只读代码，没有执行这两个测试或故障调度探针。

### F12 — 数值输入的 locale 与后端 ASCII 协议不一致

- 来源：R3c-01；P2；分类：已确认缺陷／国际化输入；验证：两种 locale 离屏复现，R6 确认；新发现。
- 位置与符号：`gui/panels/base_panel.py:687,694` `_in_int/_in_float`；`gui/panels/system_panel.py:585,600,709` 原文提交；`utils/adb_values.py:38,68` 数字规范化。
- 触发：de_DE 输入 `12,5` 坐标，或 en_US 输入 `5,555` 端口。预期 GUI 接受的值可规范化后提交，或 GUI 提前拒绝；实际默认 QLocale 的 validator 接受，后端 ASCII 校验拒绝。
- 调用链：SystemPanel 数值字段 → BasePanel._submit_device_action/hasAcceptableInput → 原文信号 → Controller 坐标／forward 或 model TCP/IP → normalize。PID 分组符属于同根因静态扩展，未动态覆盖。
- 已有防护与影响：后端在命令执行前正确拒绝，不构成注入或错误设备操作。影响是合法提示与最终行为矛盾、部分系统 locale 下无法按自然格式输入。
- 最小建议：统一输入格式，或按 validator locale 解析后输出规范字符串；保持后端严格校验。已有 `_SuffixedIntValidator` 拒绝分组符不能自动覆盖这两个工厂。
- 验证：`numeric-locale-probe` 使用真实输入控件及工厂，两项 acceptable=True 后 ValueError，断言失败；未发送 ADB。后续覆盖实际 SystemPanel 信号参数、分组符及小数分隔符矩阵。

### F13 — 非 Windows 的置顶开关只更新显示与配置

- 来源：R3b-01；P2；分类：已确认缺陷／跨平台功能；验证：静态控制流确认，R6 确认，目标平台未运行；关联既有跨平台验收风险。
- 位置与符号：`gui/main_frame.py:2897` `_set_always_on_top_native`、`:2937` set_always_on_top、`:580` 初始化 flag；`gui/pages/fluent_pages.py:254,375` 开关及连接。
- 触发：Linux/macOS 本次会话开启置顶，或关闭启动时已启用的置顶。预期即时生效；实际 native 方法非 nt 恒 False，调用方仍刷新 UI/设置且标记 applied，无其他窗口更新；下次启动才按配置设置 Qt flag。
- 调用链：设置开关 → MainFrame.set_always_on_top → 非 Windows no-op → UI/持久化；启动另走 WindowStaysOnTopHint。
- 已有防护与影响：Windows 原生路径避免窗口重建；`test_model_mainframe.py:749` 明确要求 native 失败不调用 setWindowFlags/show。不能简单增加通用 fallback 并删除该测试。影响限于非 Windows 即时切换，不能说平台永远无法置顶。
- 最小建议：为支持平台定义受控生效路径，或明确提示延迟生效；保留 Windows 可见性、几何、焦点和不重建窗口约束。
- 验证：本轮未模拟/实测非 Windows 窗口管理器。后续验证开、关、已置顶启动后关闭，并关联 Windows 原生回归。

### F14 — UI 模式投影测试泄漏到机器客户端探测

- 来源：R2b／R3d；P2；分类：已确认缺陷／测试隔离；验证：原测试加受控外部边界的探针复现，R6 源码及既有探针复核；新发现。
- 位置与符号：`tests/test_qt_adb_runtime.py:192` 模式投影测试、`:208` SettingsPage、`:216` 事件处理；`gui/widgets/adb_client_card.py:153` `_ProbeTask.run`、`:555` start_detection；`services/adb_clients.py:96` native version。
- 触发：执行该测试时存在未缓存的本机 ADB 候选，启动识别任务得到运行机会。
- 预期及依据：只验证执行模式投影的测试应使用受控外部边界。实际只 patch runtime adapter 的 resolve_adb_path；设置页独立卡片的候选、程序解析及探测未替换，QTimer/QThreadPool 仍可执行真实客户端 version。
- 调用链：SettingsPage 默认启动检测 → QTimer → 卡片 QRunnable → list_adb_candidates/resolve_adb_program/detect_clients → CommandRunner native version；Windows 客户端解析还可能创建改名副本。
- 已有防护与影响：全局夹具隔离设置／归档／模拟器枚举；取消、缓存和缺失候选可能阻止某次探测，但不建立测试隔离。只读 version 不代表会启动 5037 或操作设备，不能扩大描述。
- 最小建议：与检测无关的测试延迟启动检测，或在真正卡片边界提供合成候选及受控 runner，并等待任务收口；不能仅 patch 另一适配器的同名 resolver。
- 验证：`test-isolation-probe` 调用原测试，预先把候选／resolver 限定临时不可执行文件，mock CommandRunner 记录；原测试断言通过，额外出现 `[synthetic-client.exe, version]`，外层无外部调用断言失败。未运行真实 ADB，未复制真实客户端。
- 同根因静态扩展：`tests/test_main_window_layout.py:206` 的 build_main_frame 仅在构造期间 patch start_detection，返回后补丁失效；`fluent_pages.py:444` 定时回调到时才取该方法。本模块 autouse 保护不随 helper 导入继承；`test_live_logcat_visual.py:100,353,405,504` 和 `test_file_explorer_visual.py:458` 的消费者没有对应隔离。文件页 `:720` 的测试已有 runner 替身，不纳入真实 version 执行结论。此扩展没有另行动态触发。
- 其他已审消费者：R3d 指出 `test_workspace_consolidation.py:222`，R3e 指出 `test_navigation_rendering.py:113,178,285,325` 和 `test_workspace_feature_host.py:538` 同样跨模块复用上述 helper，未维持完整生命周期的探测替身；只作为静态扩展，不声称本轮逐节点实际执行了客户端。

### F15 — Monkey 部分设备完成后运行数量没有刷新

- 来源：R3c-02；P3；分类：已确认缺陷／展示状态；验证：真实面板离屏复现，R6 源码及既有探针复核；新发现。
- 位置与符号：`gui/panels/app_panel.py:1280` on_monkey_target_finished、`:1294` 部分完成直接返回、`:742` `_update_monkey_presentation`。
- 触发：两台或多台设备的 Monkey 批次，首台提前完成／失败。预期显示剩余设备数；实际 active/pending 已收敛，但未刷新标签，直到其他 UI 刷新或整批完成。
- 调用链：Controller 单台终态 → `main_frame.py:2619` → `side_panel.py:365` → AppPanel 槽 → 提前返回；最后一台才经过 _set_monkey_running 刷新。
- 已有防护与影响：批次、设备去重及停止目标集合正确，不能推断重复停止、任务丢失或资源未释放；只是显示计数陈旧。
- 最小建议：部分完成后刷新展示，不改变运行状态机。
- 验证：`display-ci-probes` 真实 Apps 面板注入两目标运行状态，首台结束后 active tuple 只剩一台，而标签仍为两台，断言失败；没有启动 Monkey。后续覆盖两台→一台→结束和晚到重复结果。

### F16 — Actions 固定版本门禁跳过未匹配引用

- 来源：R5b；P3（Lead／R6 依据当前引用均已固定降级）；分类：已确认缺陷／回归门禁；验证：临时合成工作流复现，R6 确认；新发现。
- 位置与符号：`tests/test_ci_contracts.py:52` USES_PATTERN、`:103` test_all_actions_are_pinned_to_verified_commit_shas。
- 触发：保留一条可匹配固定引用，再添加无 `# vN` 注释的第三方 uses；合法的 `- uses:` 写法及 `.yml` 工作流也是静态遗漏范围。
- 预期及依据：测试名称与断言意图是检查全部 Actions 来源／SHA。实际只遍历满足注释和行结构的正则匹配，assert matches 仅证明至少一条存在，未匹配引用被完全跳过。
- 调用链：CI 测试 → glob `*.yaml` → USES_PATTERN.finditer → 仅验证匹配集合。
- 已有防护与影响：当前两个 workflow 的 8 条引用均固定 SHA，没有当前供应链漏洞或恶意引用证据；影响是未来回归可能漏检。
- 最小建议：先完整枚举支持的 workflow/uses 语法，再逐项执行来源与 SHA 规则；补未注释、inline uses、未知来源、非 SHA、`.yml` 的反例夹具。
- 验证：`display-ci-probes` 临时 YAML 保留合法 checkout，加入 `actions/setup-python@main`，原门禁错误通过，外层拒绝预期失败；未修改或执行真实 workflow。其他语法遗漏本轮只静态确认。

## 待验证风险

### F11 — 图标 helper 编译结果与源码摘要存在竞态窗口

- 来源：R5-03；P3；分类：待验证风险／构建来源一致性；验证：静态确认条件性竞态，R6 确认并降低优先级；新发现。
- 位置与符号：`scripts/build_app_icon_helper.py:72` build_helper 编译、`:77` 首次摘要读取；`:26` verify_helper；对照其他 helper 构建器的编译前后摘要核验。
- 触发：javac 已读取旧源码，摘要读取前开发者并发修改 Java 文件。
- 预期及依据：内嵌摘要应标识实际编译源码。实际旧 DEX 与新源码摘要可一同写入，verify 只验证 DEX 结构及摘要等于当前源码，因此无法识别错配。
- 调用链：build_helper → javac／d8 → `_source_digest` → ZIP → verify_helper → 原子发布 → services/apps/helper 使用随包 JAR。
- 已有防护与影响：临时目录、DEX 校验、原子发布防不完整文件；源码稳定的 CI 不触发。可能错误认定旧字节来自新源码，没有证据表明当前 JAR 或已发布版本已错配。
- 最小建议：编译前冻结摘要并于发布前重核，或编译不可变源码快照。
- 验证：未运行编译器或 fake 编译探针。可在临时源码上 mock 编译步骤后改文件，要求拒绝发布且保留原产物。

## 规范差异或产品待决策

### D01 — FileExplorer 大目录风险描述落后于实现

- 来源：R3-03／R3b；P3；验证：静态确认。
- `docs/project-knowledge/RISKS_AND_DEBT.md:60` UI-05 称一次构造全部行；`gui/features/file_explorer/list.py:336` 起已有 Timer 分批填充，每约 64 行或 6 ms 让出。
- 这是已知问题记录需要更新，不能作为当前“一次建全部行”的 Bug。最终 Qt 排序与 1k／10k 文件实际耗时仍未测量，保留该剩余风险。
- 建议后续仅修正文档事实，性能验证按帧延迟、首批显示、排序峰值和设备数量固定条件测量；不编造优化收益。

### D02 — 项目 skills 的路径／设置来源提示不准确

- 来源：Lead／R5；P3；验证：工作区与当前代码核对确认。
- `.dsh/skills/adblab-verify/SKILL.md:66` 将当前仓库描述为 Program Files (x86)；本次实际工作区为 S 盘 CodeSpaces。`.dsh/skills/adblab-ui-i18n/SKILL.md:52` 指向 settings_manager 添加 DEFAULTS；当前定义在 `core/settings/schema.py`，manager 为兼容导出。
- 已按当前代码和实际解释器审查，未因此安装依赖或改文件。后续更新说明并保留兼容导出；这不是运行时缺陷。

## 已排除或未升级为缺陷的推断

- 不把兼容门面、旧数据键、Qt 回调和测试替换点当作无用代码；未基于文件长度提出拆分。
- AppSettings 未读／未来 schema 保护、RunLibrary 跨进程锁与锁内重读、安装交接 COMMIT／父进程身份／摘要防护均已核对，不重复列为缺陷。
- APK 后缀大小写规则已有测试保持，真实设备可达性及产品契约未明确；未列确认 Bug。
- FPS 首轮 `$` 转义、MobilePerf stop_logcat 关闭活跃 reader 的潜在阻塞没有足够新增证据，未列确认缺陷。
- 原生 Qt 崩溃、真实安装／升级／卸载、真实设备命令执行与长跑稳定性均不由离屏替身测试证明。
