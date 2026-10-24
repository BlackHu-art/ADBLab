# 服务与 Logcat 功能目录归位设计

状态：已完成（2026-10-24），最终独立审阅 PASS / APPROVE，无遗留问题。延续用户已授权的全项目持续重构及多 agent 并行方式，由主 agent 冻结边界并独立审阅。

## 目标与证据

目录应表达当前职责，并允许不加载无关执行基础设施就使用配置、结果和协议服务。
本阶段是三个可独立验收的子项目，不改变用户功能、交互、数据路径/格式或平台支持。

1. `app_metadata` 从 `app_icons` 借用通用 helper；`app_icons` 又延迟导入元数据解码器，形成实际双向依赖。
2. MobilePerf 配置与结果对象定义在进程运行器中，结果查询还调用运行器的路径方法。
3. Logcat 内嵌页及其协作者放在 `gui/dialogs`，`gui/features/logcat.py` 仅转发页面。

## A：应用 helper 服务

新增无聚合导入的 `services/apps/` 包，将 `HelperResult`、`run_app_helper`、`_run_inline_helper`
及其传输常量移至 `helper.py`。PNG 解析、批处理和元数据业务保留原模块；`app_icons` 正常导入
元数据解码器，二者直接依赖 helper，helper 不反向依赖图标或元数据。

`services.app_icons.HelperResult` 和 `run_app_helper` 继续重导出同一对象，保持签名及错误分类。
传输私有常量可兼容重导出；测试的私有 transport monkeypatch 改到真实所有者 helper，不能减弱断言。
不承诺将旧模块私有全局变量赋值自动转发；原业务级 `app_icons.run_app_helper` 与
`app_metadata.run_app_helper` 替换点保留。设备命令、quote、取消、清理与大小限制原样迁移。

## B：性能配置与结果

| 新位置 | 职责与旧入口 |
| --- | --- |
| `services/performance/config.py` | Monkey/Run 配置、分号字段辅助函数和 `normalize_local_path` |
| `services/performance/results.py` | `PerformanceArtifacts`、`PerformanceResultQuery`、纯函数 `path_key(Path) -> str` |
| `services/mobileperf_runner.py` | 保留进程适配与生命周期，重导出原类/函数；`_path_key` 委托纯函数 |

配置序列化字段、顺序、默认值、路径规范化与 UTF-8 文件写入保持相同。结果查询的基线、时间、
运行归属和部分失败语义保持相同。纯路径函数仍使用 `normcase(abspath(str(path)))`。
新包 `__init__.py` 不导入运行器。配置/结果直接导入不得加载运行器、`core.exec` 或受控进程模块。
只更新使用配置/结果的性能 GUI 消费者；运行器留在原位，保留 `__file__.parents[1]` 的项目根和
旧模块的执行依赖替换点。旧新类对象身份相同，不生成第二套 dataclass。

## C：Logcat 功能包

`gui/features/logcat.py` 转为 `gui/features/logcat/` 包。`LiveLogcatPage` 的公开入口保持不变，
包入口使用显式延迟 `__getattr__` 和静态函数内导入，避免导入 worker 时顺带导入页面及形成环。

| 旧 dialogs 模块 | 新 features/logcat 模块 |
| --- | --- |
| `live_logcat.py` | `page.py` |
| `live_logcat_form.py` | `form.py` |
| `live_logcat_lifecycle.py` | `lifecycle.py` |
| `live_logcat_stream.py` | `stream.py` |
| `live_logcat_worker.py` | `worker.py` |
| `live_logcat_controls.py` | `controls.py` |
| `live_logcat_highlighter.py` | `highlighter.py` |
| `live_logcat_material.py` | `material.py` |

旧模块保留静态导入新实现并以 `sys.modules[__name__]` 指向新模块的兼容入口，使新旧模块
身份相同，旧路径 monkeypatch 继续影响实际执行。新实现内部使用新相对导入，stream 的晚绑定
worker 查找仍经新 page 模块；共享 `gui.dialogs.lifecycle` 不迁移。
不改类、方法、信号、Qt 所有权、线程/进程/定时器、关闭路径、视觉交互及设置键。
旧路径测试继续运行；新增双导入顺序与真实替换点行为测试。静态导入便于 PyInstaller 发现模块，
源码 packaging 自检不能代表完整冻结产物验证。

## 全局保护与验收

Python 3.11 + PySide6，使用现有 `.venv`，不增加依赖、不改 CI/发布、不提交或暂存。
所有阶段前未提交文件先保存快照；并行任务按文件隔离，主 agent 负责共享文档和集成。
本次目录调整不搬用户数据、运行时工具或二进制资源，不操作真实设备。
各子项目先取得直接测试基线，新增可观察契约回归，再迁移并验证直接及实际消费者测试。
验证成功、错误、取消与关闭；最后检查类型/源文本/中文注释/链接、源码 packaging 及独立审阅。
更广的 GUI 功能目录、平台适配和后台 worker 归位继续按总路线图推进。
