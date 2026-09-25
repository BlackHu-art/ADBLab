# 无线 ADB 配对实施与验收记录

记录日期：2026-09-25。基于 `ui-redesign` 分支的
`11db202a9d7006dee9586c079fb3fd0714b2384c`，本轮改动保留在工作区，未提交、推送、改版本或正式发布。
这是阶段验收快照；当前行为以代码与知识库为准。

## 交付范围

按[已批准方案](../../superpowers/specs/2026-09-25-wireless-adb-pairing-design.md)完成实现。
专门的交互设计 agent 对照既有 PySide6 Fluent Gallery 参考，形成
[交互规格](../../superpowers/specs/2026-09-25-wireless-adb-pairing-interaction.md)，由独立实现与评审 agent
分别检查命令基础设施、配对服务、Qt 窗口和 Controller 接入。

- 既有连接入口统一为「地址连接 / 扫码配对 / 配对码」三个页面。默认地址页沿用原表单与历史；
  进入扫码页才开始发现，重复打开保留当前输入，不额外启动任务。
- 支持二维码、六位配对码，以及「配对成功、尚未连接」时补填连接端口。配对端口不当作连接端口；
  完整 GUID 与无线 transport 验证通过后才交付连接结果。
- 取消、刷新、切页、关闭和更换 ADB 客户端经过统一资源退出屏障。口令走匿名 stdin，二维码
  仅驻留内存；续连快照不含口令，错误提示不展示原始命令输出。
- 复用 FluentDialog、项目导航和设备表单；提供倒计时、可操作错误、键盘操作、三种语言与主题适配。
  窄窗、短屏、大字号和高 DPI 下整幅二维码可见后才确认展示并开始扫码计时。
- 成功后刷新现有设备列表，不自动切换操作设备。历史在现有后台执行器保存，保留有效元数据与
  原 schema，不把配对端口写入连接历史。
- 运行依赖新增 `segno==1.6.6`，同步约束、许可、翻译与打包资源。当前模块入口见
  [模块地图](../../project-knowledge/MODULE_MAP.md)，行为见
  [业务流程](../../project-knowledge/BUSINESS_FLOW.md)。

## 环境与测试结果

使用用户现有 Python 3.11.9；测试工具和 Segno 放在任务临时目录，没有修改系统 Python 或创建根
`.venv`。独立构建使用 `.tmp/wireless-pairing-clean-build` 干净 venv，依赖严格来自
`requirements-build.txt` 与 `constraints.txt`。本轮实际测试前置环境为：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.tmp/wireless-pairing-python') + ';' + (Join-Path $env:TEMP 'adblab-startup-tools-20260925')
$env:PYTHONIOENCODING = 'utf-8'
$env:QT_QPA_PLATFORM = 'offscreen'
```

下表记录不同阶段的实际检查，包含重叠节点，不相加为一个总数。pytest 均由
`& 'S:/Program Files/Python/Python311/python.exe' -m pytest -q` 执行。

| 范围 | 测试文件或检查 | 结果 |
| --- | --- | --- |
| 原生命令与旧路径兼容 | `test_command_outcomes.py`、`test_native_process.py`、`test_adb_runtime.py`、`test_native_command_scope.py` | 关联 170 通过；补真实 stdin/env 子进程后增量 29 通过 |
| 配对协议与打包契约 | `test_adb_pairing.py`、`test_ci_contracts.py` | 52 + 51 通过 |
| 连接历史与重启失效 | `test_wireless_connection_history.py` 及关联 Controller 用例 | 直接 22、关联 19 通过 |
| 主窗与关闭集成 | `test_qt_adb_pairing.py`、`test_device_connection.py`、`test_global_device_context.py`、`test_fluent_dialog_contract.py`、`test_phase2_mainframe_shutdown_gate.py`、`test_qt_adb_runtime.py` | 236 通过、1 个既有平台模拟断言失败，见下文 |
| DPI 1 与 2 | `test_wireless_pairing_layout.py`、`test_qt_adb_pairing.py`、`test_device_connection.py` | 当时各 32 通过 |
| DPI 1.5、翻译与窗口语言 | `test_wireless_pairing_layout.py`、`test_i18n.py`、`test_dialog_languages.py` | 80 通过；生成并检查离屏截图 |
| 最终扫码错误文案与跨层流程 | `test_device_connection.py`、`test_wireless_pairing_flow.py` | 17 通过；跨层测试使用真实窗口、协调器与服务，注入命令和时钟 |
| Qt 测试路径可移植性 | `test_qt_adb_pairing.py` | 最终 12 通过 |
| 静态与文档 | 修改 Python 的 Ruff、12 个受影响生产模块 Pyright、中文注释、源码文本、文档链接与 diff 检查 | 通过；Pyright 为 0 errors / 0 warnings，另提示配置中的根 `.venv` 不存在 |

独立评审发现并修复了应用关闭等待者仍持有 QThread 时提前释放对象的问题，使用 Event 与
DeferredDelete 构造确定性回归；同时修复短屏动作区挤占二维码、仅按 isVisible 提前确认展示、
扫码失败误提示到不存在的配对码输入框等问题，并重跑直接测试。

唯一未通过节点为
`tests/test_qt_adb_runtime.py::test_adapter_recheck_discovers_new_macos_tool_through_both_path_caches`：
在 Windows 模拟 darwin 后，断言比较同一路径的正斜杠与 WindowsPath 反斜杠字符串。隔离重跑仍失败；
解析器、运行时模块与失败函数均未修改，未跳过测试或放宽断言。此项和实机验证缺口统一跟踪在
[风险账本](../../project-knowledge/RISKS_AND_DEBT.md)。

本轮没有运行全量 pytest：默认命令路径保持兼容，修改影响已通过直接、消费者与集成用例界定；
按[增量验证策略](../../guides/TESTING_GUIDE.md#增量验证策略)执行。本次打包验收独立完成，不能据此
宣称完整测试套件或手机实机验证通过。

## 实际冻结产物验收

最初混合 `--target` 与宿主 site-packages 的构建虽退出 0，实际 EXE 在 `pyi_rth_pkgres` 启动失败。
已定位到 setuptools 82 元数据与宿主旧 pkg_resources 源码混用，改为任务专用干净 venv 后消除。

干净构建进一步暴露原 spec 排除 `unittest`、`pydoc` 导致 Acrylic 不可用：当前 SciPy/NumPy
图像处理链实际依赖这两个标准库模块。仅从 `ADBLab.spec` 的 excludes 移除这两项并添加原因注释，
未更改 CI、锁版本或放宽自检。最终重新构建，包含最后的二维码错误文案修正。

实际构建命令如下；构建进程清空 PYTHONPATH，并设置 PYTHONNOUSERSITE=1：

```powershell
& 'S:/Program Files/Python/Python311/python.exe' -I -m venv .tmp/wireless-pairing-clean-build
& '.tmp/wireless-pairing-clean-build/Scripts/python.exe' -I -X utf8 -m pip install -r requirements-build.txt -c constraints.txt
& '.tmp/wireless-pairing-clean-build/Scripts/python.exe' -I -X utf8 -m pip check
& '.tmp/wireless-pairing-clean-build/Scripts/python.exe' -I -X utf8 -m PyInstaller ADBLab.spec --noconfirm --clean
& '.tmp/wireless-pairing-clean-build/Scripts/python.exe' -I -X utf8 -m PyInstaller ADBLab.spec --noconfirm
```

产物为 `dist/ADBLab/ADBLab.exe`，运行时须保留同目录完整内容。最终 EXE SHA256：

```text
f6f94265b194d6858f62c5709f0f9959295bfe92b5a13fa42e7346b6354b087e
```

| 同一最终产物检查 | 实际结果 |
| --- | --- |
| `ADBLab.exe --self-check packaging` | 退出 0，49/49 项通过，5.188 秒，stderr 空；包含 Segno、二维码 PNG、许可、翻译、Acrylic、运行时工具与 bridge |
| 离屏 `ADBLab.exe --self-check gui` | 退出 0，2.469 秒；验证 QPA、最小 QWidget 与事件循环，不代替真实桌面视觉验收 |
| 冻结 native 成功 | 2.812 秒；真实本地 Python 客户端通过指定 EXE 的 `--adblab-native-launch` 启动，二进制 stdin 和固定 env 正确 |
| 冻结 native 取消 | 0.328 秒；只通过真实 NativeCommandScope 请求停止，资源归零 |
| 冻结 native 超时 | 6.063 秒；正确返回 timed_out，资源归零 |
| 退出核对 | 三种场景客户端与 launcher 无残留 PID；指定路径的 EXE 进程计数为 0 |

自检数据写入任务临时 LOCALAPPDATA；未执行真实设备的 devices/pair/connect/shell，也未操作用户
ADB 信任记录。运行时工具仅执行版本探针。冻结 smoke 使用合成输入，不接入 Android 设备。
本地诊断与原始日志保存在忽略的 `.superpowers/sdd/2026-09-25-wireless-adb-pairing/`。

## 人工验收边界与步骤

未完成 Android 11+ 手机、厂商设置入口、mDNS/防火墙/隔离网络、多设备与跨屏拖动的实测。
离屏截图使用合成二维码，只证明布局和控件行为。后续实机验收建议：

1. 在同一局域网的 Android 11+ 手机上开启无线调试，从 ADBLab 原连接入口进入扫码页；
   使用手机无线调试内的扫码入口，确认成功后设备列表出现正确目标且原操作目标不变。
2. 在手机显示六位配对码后填写配对地址和码；模拟发现连接服务失败时，从手机无线调试主页
   获取连接端口继续连接，确认与配对端口分离。
3. 等待扫码、配对与连接阶段分别测试取消、刷新、切页和关闭；重新打开后无旧二维码或口令，
   不重复发起旧会话，也不承诺取消能撤销手机已经记录的信任。
4. 在两台设备、端口变化和 mDNS 被阻断场景核对身份与提示，再验证 Windows 高 DPI 跨屏拖动。
   厂商未提供扫码入口时使用手动配对码。

源码运行需在用户选定的项目解释器安装更新后的运行依赖；本轮没有替用户修改原本机解释器。
已生成的完整 `dist/ADBLab` 目录包含所需运行依赖，可用于本地验收。
