# 测试结果归档、命名方案与遗留清理验收记录

日期：2026-09-06。起点：`ui-redesign`，HEAD `a90b3e2e599cd7c06343a2ff151cd695e3b76ff1`，开始时工作树干净。

## 本轮交付

- Monkey 和性能测试完成后保存运行快照，任务中心默认展示跨重启测试结果；包名/日期、类型、状态可以组合筛选。
- 表格约显示 6 行，其余内部滚动；详情包含可用设备别名、应用版本、耗时、参数和本地附件。参数默认折叠。
- Monkey 和性能页均可保存、载入、删除命名方案；同类型同名更新，另一名称另存。载入历史或方案只填表，不选择旧设备、不自动开始测试，运行中的表单拒绝回填。
- Monkey 支持每次随机或固定 seed，并保存每台设备真正使用的 seed；历史复用固定实际值，随机方案重复运行仍重新抽样。
- 用户配置目录新增 `test_runs.json`，最多 200 条结果、50 个方案；只保存新运行，不扫描旧产物。索引淘汰不删除文件，不迁移旧 AppSettings 或应用包名预设。
- 文件 I/O 在串行后台队列中进行；原子替换成功后更新 UI。损坏或未来版本文件保持只读；写失败保留原文件并通知，不伪装成功。
- 生产者停止后先补交 Monkey/性能终态，再排空队列并保存其它设置。归档失败不阻断其他页面收尾；附件目录故障保留参数并标记 partial/failed。
- 任务中心保留“本次操作”和运行记录。长操作列表隐藏后不参与结果页测高；空在途状态压缩为一行，1200×900 首屏可见三项附件/参数操作。
- 三个正式语言词库各增加 66 条，保留原有 1240 条；重新生成 QM 和翻译 QRC Python 资源。

主要实现：`services/run_library.py`、`gui/run_library.py`、`gui/widgets/run_results.py`、`gui/widgets/run_preset_bar.py`；Monkey、性能页、MainFrame、TaskCenter、关闭控制器按原有调用链接入。

## 清理范围

已删除 6 个完成使命的旧翻译生成脚本/输入（原大小共 58,307 字节），去掉 DeviceContextBar 内立即隐藏且无运行时消费者的旧详情/断开按钮及重复同步代码，保留真实菜单操作和业务信号。修正 `models/base` 执行层归属说明及任务中心过时阶段注释。

逐项消费者与替代入口证据见 [cleanup-evidence.md](cleanup-evidence.md)，旧文件路径/大小/SHA-256 见 [cleanup-removed-manifest.json](cleanup-removed-manifest.json)。本次排查创建的基线副本和一次性生成工具也已回收；最终图片和可复现渲染脚本保留。

没有删除动态 Qt 入口、有效测试、兼容迁移、源码资源、历史归档、既有验证材料、用户数据或平台二进制。没有提交、推送、更新版本、修改依赖或 CI。

## 最小充分验证

环境：项目 `.venv`；Qt 测试 `QT_QPA_PLATFORM=offscreen`。新结果库路径在测试中统一隔离到临时目录。未执行真实 ADB 命令。

### 最终功能集成

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_run_library.py tests/test_run_library_ui.py tests/test_run_library_integration.py tests/test_run_results.py tests/test_run_results_host.py tests/test_monkey_library.py tests/test_performance_library.py tests/test_task_history.py tests/test_task_center.py tests/test_phase2_mainframe_shutdown_gate.py tests/test_model_mainframe.py tests/test_i18n.py
```

**189 passed，exit 0，28.27 秒**。316 条警告来自安装版本的 Qt/QFluentWidgets QDomDocument 弃用提示。

覆盖重读持久化记录、原子写失败、超大整数时间拒绝、失败后继续处理队列、关闭排空、关闭归档失败、方案隔离、无自动执行、筛选、失效附件、200 条结果、销毁后回调、随机/固定 seed、真实终态、取消与关闭、性能附件故障、窄布局和三语言。

最后将空在途卡改成一行状态后，仅重跑直接与关联宿主：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_run_results_host.py tests/test_task_center.py tests/test_run_library_integration.py tests/test_model_mainframe.py
```

**43 passed，exit 0，1.45 秒**。43 与 189 有重叠，不相加为独立测试总数。

### 分模块关联检查

- Monkey 直接及关联集合：81 passed、23 deselected；另一消费者集合42 passed、186 deselected，包含重复节点。
- 性能归档直接33 passed；原性能启动/停止模型22 passed。
- 设备栏真实菜单修改前后各3 passed；旧翻译输入清理后正式资源与打包许可契约29 passed。
- 结果面板最后字体/布局节点：100% DPI 3 passed、150% DPI 3 passed。540px/22pt 下表格省略显示，tooltip 和详情保留全文；按钮换行且无横滚。
- Monkey 真实中文字体12/22号、宽/窄布局通过。极窄视口仍遵循原表单约342px最小内容宽度，不宣称整个页面压缩到292px。

### 主窗口扩大检查及既存失败

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_main_window_layout.py tests/test_workspace_route_payload.py tests/test_workspace_consolidation.py tests/test_run_library_integration.py
```

结果为 **113 passed、1 skipped、1 failed**。失败节点是 `test_remote_workspace_requires_an_explicit_session_device_when_multiple_online`，第1025行期待只选会话设备就进入可操作状态，但现有准入还要求全局勾选。

当前工作树与完整隔离 HEAD 快照使用同一解释器重跑，都在同一断言失败，证据见 [remote-baseline-evidence.md](remote-baseline-evidence.md)。本轮没有修改该既存功能/测试，不把它记作本轮通过，也未放宽断言。

### 静态、文档与资源

- Ruff：所有本轮新增/修改的手写生产 Python 和测试文件通过。
- Pyright：17 个受影响生产路径 0 errors、0 warnings。
- 中文注释检查：同17个生产路径通过。
- `scripts/check_doc_links.py`：30篇项目文档链接与frontmatter通过。
- `git diff --check`：通过。

```powershell
$env:LOCALAPPDATA = Join-Path $env:TEMP 'adblab-run-library-self-check'
.\.venv\Scripts\python.exe main.py --self-check packaging
```

**exit 0，全部 OK**，包含依赖导入、三语言嵌入资源、显式资源及临时用户目录可写检查。此命令不是 EXE 构建验收。

## 实际渲染

合成数据、完整 fake AppSettings、临时用户目录、模拟设备控制器；截图脚本使用防护断言阻止 CommandRunner 外部执行，设备刷新调用数为0。

- [真实任务中心主窗口1200×900](task-results-mainframe-light-1200x900.png)：最终空态压缩后首屏可见附件与载入按钮；剩余外层滚动39px用于下方运行记录入口。
- [任务中心滚动到底部](task-results-mainframe-light-1200x900-bottom.png)。
- [结果组件浅色1080/12号](run-results-light-1080-font12.png)、[深色540/22号](run-results-dark-540-font22.png)。
- [Monkey浅色960/12号](../run-library-20260906/monkey-library-light-960-font12.png)、[深色740/22号](../run-library-20260906/monkey-library-dark-740-font22.png)。
- [性能页浅色1092/12号](../run-library-20260906/performance-library-light-1092-font12.png)、[深色740/22号](../run-library-20260906/performance-library-dark-740-font22.png)。

上述图已实际打开检查。任务中心最后一次渲染正常 exit0，参数默认折叠，无横滚、按钮无重叠。小窗口或大字号允许合理竖向滚动。

## 边界与后续

本轮完成选定的测试结果/方案复用与已核实遗留清理。未实施性能 A/B 对比、Perfetto 深度整合、更多连接方式等其余路线项。没有把代码量小、无静态文本引用或历史目录视为可直接删除的依据。

未跑全量 pytest、未生成新 EXE、未做真实设备采集。自动测试验证了命令/模型/结果归档调用链，真实长时间采集、不同 Android 版本和多实例并发保存不属于本轮已验收范围；结果库目前按单进程设计，多实例无合并协议。

人工验收可在 PyCharm 重启 main.py 后：保存一份Monkey方案→执行一次短测试→在任务中心打开日志和载入参数→确认不自动开始→重启后确认记录与方案仍在；性能采集同样验证一次成功和主动停止。
