---
status: current
last_verified: 2026-09-27
owner: 待确认
related: [ARCHITECTURE.md, MODULE_MAP.md, DATA_FLOW.md]
---

# 风险与技术债

本页只保留尚未闭环的事项；已解决问题由 Git 历史、ADR 和
[archive](../archive/README.md) 追溯。状态含义：**Open** 为未处理，**Partial** 为已有保护但仍缺
关键闭环，**待确认** 为需要负责人、真实设备或环境验证。

| 等级 | 未闭环事项 | 当前保护与剩余工作 | 状态 |
| --- | --- | --- | --- |
| Medium | 无线配对的手机与局域网兼容矩阵尚未实测 | 服务、Qt 交互及本地客户端生命周期使用离线替身验证；仍需 Android 11+ 实机覆盖扫码入口、六位码、mDNS/防火墙/网络隔离、配对与连接端口变化及取消后的信任记录。实现不能保证所有厂商提供二维码扫描入口 | 待确认 |
| High | 打包发布会自动删除保留范围外的 tag/Release，且没有独立的历史版本登记 | [Build](../../.github/workflows/Build-exe.yaml) 拒绝覆盖现存同版本，并仅保留最新 5 个版本 tag 及对应 Release；被删除版本的不可复用登记与发布审批仍需项目决策 | Partial |
| High | PySide6-Fluent-Widgets 的分发许可尚未形成正式项目决策 | 已记录 GPL-3.0/商业许可边界并把第三方说明纳入产物；任何分发前仍需完成法务、开源或商业授权决策 | Open |
| High | 随包 chkbugreport JAR 的分发许可尚未确认，仓库缺少对应官方许可文本 | MANIFEST 标识 `com.sonyericsson.chkbugreport.Main`；对外分发前核对准确上游版本及许可，并补齐官方许可文本和第三方声明 | Open |
| Medium | 少数公共 model 入口依赖 Controller 的业务参数校验 | 主 UI 的 forward/reverse TCP 端口与 geo 经纬度已有校验；直接调用 `ADBNetworkMixin.forward_port_async/reverse_port_async` 或 `ADBSystemMixin.emu_geo_fix_async` 时未重复完整约束。是否收紧直接调用契约需确认；已 quote 的 URI、组件、设置值和文本不再笼统列为注入缺口 | Partial |
| Medium | AppSettings 只在进程内串行保存，多实例并发写入没有文件锁或冲突检测 | [AppSettings](../../core/settings_manager.py) 已有可重入锁、写锁和原子替换；确认是否支持多实例，再补进程间协调或显式单实例约束及测试 | Open |
| Medium | App Manager 备份/恢复缺少 manifest、hash 与新版 Android 实机闭环 | [AppManagerWorker](../../models/app_manager_worker.py) 校验关键 CommandResult 和拉取 APK 数量，先暂存再原子发布 ZIP；恢复使用安全解压，取消后不启动后续安装或发布完整成功；页面业务批次串行，仍需完整性元数据和授权恢复测试 | Partial |
| Low | App Manager 批量元数据与图标补全缺少 Android 版本、厂商和多用户实机耗时矩阵 | [临时 helper](../../tools/app_icons/Main.java) 保留用户校验和退出保护；协议与页面测试覆盖文字优先、精确缓存失效、取消和晚到结果。仍需测量首屏名称/图标时间，并验证设备用户切换、语言变化与应用升级后的刷新 | 待确认 |
| Medium | 写操作、传输和部分长任务仍不能按 operation 统一中止；设备离线时远端 Monkey 退出无法自动确认 | MobilePerf 异步客户端使用本次临时作用域及 helper 显式归属，worker 强停后仍监督直接客户端，不终止独立 ADB 服务；远端 Monkey 按 PID/starttime 停止，未确认义务保留为残留，不允许覆盖后重启。只读查询与采样等待支持取消；仍需实机验证 worker 强停、设备拔线后人工处理及平台差异下的收尾 | Partial |
| Medium | 跨平台真实功能验证与依赖闭包仍不完整 | Build 已配置 macOS x64/arm64 架构校验、三平台 packaging 自检和 Linux xcb GUI 探针；CI 不运行 pytest，测试按测试指南在本地执行。仍需对应平台实际运行、Windows windowed MobilePerf 管道、macOS Finder 启动、授权设备投屏与断线验收，不能把构建或路径模拟通过视为功能验收 | Partial |
| Medium | 诊断、日志、bugreport、heapdump、截图和报告没有统一保留/清理策略 | 输出写入用户选择目录或用户数据目录；仍需数据分类、默认保留期、访问控制和可选清理 | 待确认 |
| Low | Remote、MobilePerf 和录屏的长跑、断线、清理及 Android 厂商差异缺少授权实机矩阵 | 单元与故障注入覆盖主要状态机；建立可选硬件验收清单，不把离屏测试当作实机结论 | 待确认 |
| Low | 完整 Qt 测试长序列曾出现下拉控件悬停超时，具体前置状态尚未定位 | [下拉材质测试](../../tests/test_dropdown_material.py) 在独立、紧邻前置及原失败节点组合中通过；活动 Popup 遮挡可复现相同症状，但尚未证明全量中的来源。失败时记录鼠标实际命中、活动窗口、Popup 和模态窗口，保留原交互与像素断言 | 待确认 |
| Low | scrcpy 端口移交与 ADB 映射删除缺少跨应用原子操作 | 已为应用内会话保留独立端口并在删除前核对 scid；探测端口到 scrcpy 绑定、核对映射到删除之间仍可能被外部 ADB 客户端改写，不应视为跨应用独占保证 | Partial |
| Medium | 稳态能力健康检查只保留一次 1 秒尝试，本机服务引导也只在运行实例首次初始化做一次 | 已评估「稳态重试」与「冷却期重试引导」，但会改变 `test_adb_runtime` 固定的行为与 [ADB_FAST](../guides/ADB_FAST.md) 语义，需先做产品决策；当前失败后按 `CHECK_INTERVAL` 在下一轮用完整能力预算恢复 | 待确认 |
| Low | 设备面板与设置页各有一个「重启 ADB」入口 | 两个入口复用同一 `restart_adb_requested` 信号和同一结果处理器，重启后都会作废能力并重测；是否删除隐藏面板按钮需产品决策 | Open |
| Low | 首次执行本机 `adb.exe` 可能显著偏慢（Windows 加载与安全扫描），客户端识别依赖预热与护栏 | 设置页构建后空闲预热一次识别、单项 3 秒预算、串行探测、15 秒护栏且失败不入缓存；缺少其它机器与真实设备矩阵验证 | 待确认 |
| Low | 表格的手动列宽与排序分组规则尚未统一 | 文件/应用主列表支持手动列宽；[归档结果](../../gui/widgets/run_results.py) 和 [多设备采集状态](../../gui/widgets/performance_sessions.py) 仍采用自动列宽。文件列表大小/时间排序固定父目录及目录分组，名称/类型排序使用普通文本排序；是否统一手动调整及目录置顶属于后续交互决策 | 待确认 |
| Low | 通知紧凑高度测试存在 Linux 字体度量差异 | [通知测试](../../tests/test_notifications.py) 的 22pt 中文浮条在本机为 67px，超过固定 64px 断言；原 HEAD 同样复现，全文、按钮与窗口边界检查通过。尚需确定跨平台紧凑高度标准；未放宽断言或缩小字号 | 待确认 |
| Low | Windows 上的 macOS ADB 重检模拟用例存在路径分隔符断言差异 | [重检测试](../../tests/test_qt_adb_runtime.py) 的 `test_adapter_recheck_discovers_new_macos_tool_through_both_path_caches` 比较含正斜杠的模拟 darwin 路径与 WindowsPath 反斜杠字符串而失败；本轮未修改解析器或该节点，需单独校准跨平台断言 | Open |

新增问题和测试缺口只在本表登记；实现事实放入相应主题文档，测试选择与门禁命令见
[TESTING_GUIDE](../guides/TESTING_GUIDE.md)。
