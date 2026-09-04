---
status: current
last_verified: 2026-09-03
owner: 待确认
related: [ARCHITECTURE.md, MODULE_MAP.md, DATA_FLOW.md]
---

# 风险与技术债

本页只保留尚未闭环的事项；已解决问题由 Git 历史、ADR 和
[archive](../archive/README.md) 追溯。状态含义：**Open** 为未处理，**Partial** 为已有保护但仍缺
关键闭环，**待确认** 为需要负责人、真实设备或环境验证。

| 等级 | 未闭环事项 | 当前保护与剩余工作 | 状态 |
| --- | --- | --- | --- |
| High | 设备 shell 的动态 path、URI、组件、设置值和文本尚未全部经过统一 quote/校验 | model 层和部分 Controller 已采用白名单或 `shlex.quote`；继续审计所有高级 shell/intent/文件入口，并做授权实机验证 | Partial |
| High | 打包发布会自动删除保留范围外的 tag/Release，且没有独立的历史版本登记 | 已禁止覆盖现存同版本并限制 workflow 权限；增加不可复用版本登记和发布审批 | Partial |
| High | PySide6-Fluent-Widgets 的分发许可尚未形成正式项目决策 | 当前约束为内部使用；任何对外分发前核验实际依赖许可并完成法务/开源或商业授权决策 | Open |
| High | 端点防护可能锁定配置/Git/打包文件并把 adb 启动拖慢到扫描超时附近 | DeviceStore 有重试、损坏保护和原子写，扫描可中断且保留最后成功快照；根治仍需 IT 白名单或代码签名，并复验打包产物 | Partial |
| Medium | App Manager 备份/恢复缺少 manifest、hash 与新版 Android 实机闭环 | 关键 CommandResult 已校验，备份使用 staging；补完整性元数据和授权恢复测试 | Partial |
| Medium | 已运行的 QRunnable/Executor 长命令不能统一协作取消，MobilePerf 内核仍有独立 Popen 边界 | 新任务有终态准入栅栏，受控长进程优先走 ProcessRunner；继续统一取消、有限等待和应用关闭顺序 | Partial |
| Medium | 打包 CI 不运行 pytest，macOS/Linux 也缺少真实功能验证 | Windows 有 Ruff/Pyright 和打包自检；至少恢复非 UI 测试，并补平台启动/ADB/scrcpy 降级检查 | Open |
| Medium | 诊断、日志、bugreport、heapdump、截图和报告没有统一保留/清理策略 | 输出写入用户目录；仍需数据分类、默认保留期、访问控制和可选清理 | 待确认 |
| Medium | 全量 pytest 较慢，响应式几何扫描占用较多时间 | 日常使用受影响测试和 `not ui` 子集；继续拆分稳定快慢门禁并记录耗时预算 | Partial |
| Low | 设备信息仍可能把 device id、序列号或 MAC 写入用户可见日志 | 文件日志默认关闭不等于脱敏；应在日志边界统一遮蔽真实设备标识并补契约测试 | Open |
| Low | Qt/qfluentwidgets 在部分全量或子进程退出场景偶发原生异常 | 业务断言可能已完成，但进程退出码仍不稳定；以最小探针定位 QObject 延迟销毁和原生资源顺序 | Open |
| Low | 跨任务关闭顺序、MobilePerf 长跑/断线、录屏清理和 Android 厂商差异缺少授权实机矩阵 | 单元与故障注入覆盖主要状态机；建立可选硬件验收清单，不把离屏测试当作实机结论 | 待确认 |

新增问题只在本表登记；实现事实放入相应主题文档，测试缺口放入
[TESTING_GUIDE](../guides/TESTING_GUIDE.md)。
