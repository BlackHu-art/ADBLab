# adblab 按职责归入既有目录

日期：2026-10-24。基线：`ee8fbca`。用户已明确要求先映射和计划，再实施、独立审阅与验证，
验证通过后删除顶层 adblab；沿用此前自主决策、并行推进授权，不重复索取方案许可。

## 目标和边界

复用 services、core、gui 等已有顶层目录；不新增 application、qt_adapters 或其他顶层包。
保持应用功能、用户交互、公开对象的行为/签名、配置和归档数据、路径、线程/进程生命周期不变。
实现正文仅迁移及调整导入，不借此合并状态机、拆分方法或改变错误语义。

本次明确退役仓库内部 `adblab.*` 源码导入路径，所有仓内消费者同步迁移。删除目录后，外部手写的
旧路径导入也需要更新；不建立同名 adblab.py、import hook、sys.path 注册或其他隐形兼容层。
这项取舍来自删除顶层目录的明确要求，不把“功能和数据兼容”扩大成旧内部模块名仍存在的承诺。
仓库未发现插件入口或持久化模块路径/pickle 的使用；原有 models worker、GUI 页面和 MainFrame
公开导出继续保持同对象与替换行为。品牌、资源 URL、用户目录和可执行文件名中的 adblab 不改。

## 方案取舍

- 原先两个子包提升为两个新顶层包：迁移简单，但用户已否定该方向，不能再次采用。
- 全部塞入 services 或 gui：把基础设施、业务和界面混放，不能表达实际职责。
- 本次采用按模块职责归入现有顶层包，只新增必要的轻量子包；单独的录屏/Monkey 服务放在
  services 根，不为每个单文件增加一层包。

## 精确映射

以下 21 个叶子完整迁移，类、函数、常量和信号名称不变。

| 原位置（adblab/ 下） | 唯一真实目标 | 职责 |
| --- | --- | --- |
| application/cancellation.py | core/tasks/cancellation.py | 通用协作取消 |
| application/supervision.py | core/tasks/supervision.py | 资源停止、等待和残留监督 |
| application/operations.py | services/tasks/operations.py | 业务操作身份与状态 |
| application/envelope.py | services/tasks/envelope.py | 操作载荷和元数据 |
| application/action_results.py | services/tasks/action_results.py | 请求身份、结果和输出归属 |
| application/device_context.py | services/devices/device_context.py | 设备选择、发现状态快照 |
| application/device_batch.py | services/devices/device_batch.py | 设备批次业务流程 |
| application/device_connection_lifecycle.py | services/devices/device_connection_lifecycle.py | 连接生命周期及历史准入协议 |
| application/install_batch.py | services/apps/install_batch.py | 应用安装批次 |
| application/apk_selection.py | services/apps/apk_selection.py | APK 选择端口协议 |
| application/screen_record.py | services/screen_record.py | 录屏业务登记、停止和发布 |
| application/monkey_batch.py | services/monkey_batch.py | Monkey 参数快照与批次交付 |
| presentation/qt_task_supervisor.py | core/tasks/qt_supervisor.py | 通用资源监督的 Qt 线程桥接 |
| presentation/qt_adb_runtime.py | gui/adapters/adb_runtime.py | ADB 运行环境 Qt 信号适配 |
| presentation/qt_adb_pairing.py | gui/adapters/adb_pairing.py | 无线配对的界面线程桥接 |
| presentation/qt_apk_file_picker.py | gui/adapters/apk_file_picker.py | QFileDialog 实现 |
| presentation/qt_app_update.py | gui/adapters/app_update.py | 更新检查 Qt 网络适配 |
| presentation/qt_device_connection_lifecycle.py | gui/adapters/device_connection_lifecycle.py | 窗口连接生命周期桥接 |
| presentation/qt_device_discovery.py | gui/workers/device_discovery.py | 设备扫描线程和载荷 |
| presentation/workers/app_manager.py | gui/workers/app_manager.py | 应用管理 Qt worker |
| presentation/workers/file_explorer.py | gui/workers/file_explorer.py | 文件操作 Qt worker |

旧 adblab、application、presentation、workers 的四个 __init__.py 不复制跨域聚合；最终随旧目录删除。
新增 core/tasks、services/tasks、services/devices、gui/adapters、gui/workers 的 __init__.py
只声明职责，不主动导入叶子。services/apps 和其他既有包根保持轻量。

## 依赖和所有权

`services.apps.install_batch` 和 `services.devices.device_batch` 依赖 `services.tasks.operations`，
后者只向下依赖 `core.tasks.cancellation`；services/tasks 管业务终态，core/tasks 管资源退出，
两者不能互相替代。`services/task_history.py` 保持原位并切换操作类型导入。
`core.tasks.qt_supervisor` 显式依赖 Qt，但 core/tasks 包根及纯资源契约导入不带入 Qt。

gui/adapters 和 gui/workers 只适配已有服务/执行边界；不迁入 gui/features，避免其 AboutPanel
聚合提前加载 Fluent。设备发现 run 内既有 models 延迟解析保持原样，不将导入隔离误写为运行隔离。
所有 QObject 父对象、线程启动/停止顺序、关闭屏障、信号连接、页面工厂和翻译上下文保持不变。

models 两个 worker 入口直接指向 gui.workers 中唯一模块，保留 sys.modules 同对象别名和完整
TYPE_CHECKING 导出。MainFrame 对发现线程/载荷的原有再导出仍是同一类对象。

## 测试契约的迁移

- 设备上下文只精确放行 services、services.devices 和自身叶子；仍拒绝其它服务及 Qt/GUI/core/model。
- worker 导入只放行 gui、gui.workers 和其叶子；继续拒绝其它 gui 子包、models/controllers/Fluent。
  保留兄弟 worker 不被加载、原有导入次序、父包属性、模块身份、构造前后依赖替换和 QThread 基类断言。
- 新增新职责包根无 Qt/GUI 聚合、纯用例无旧包/Qt依赖及核心监督无 services 反向依赖的测试。
- 所有 import、动态导入字符串、monkeypatch 路径、类真实模块断言同步到唯一新位置；业务断言不降低。
- 旧目录暂存时用 import blocker 阻断 adblab 跑验证，证明新实现不依赖它；通过后删除四个包根及
  21 个旧叶子，再验证物理目录不存在、源码/配置无旧导入，以及代表性启动、关闭和替换点。

## 工程与文档

新子包已在既有 Pyright/coverage/中文注释检查根下；移除这些清单中的 adblab，更新相应结构测试和
CI 契约测试的第一方包列表，不改变 CI 本身。PyInstaller 沿既有静态依赖收集，不额外收集退役包。
执行现有构建描述测试和源码 packaging 自检，不进行正式构建、发布、版本或依赖调整。
更新 AGENTS 目录事实、README、当前知识库/指南，新增 ADR；旧阶段文档保留历史，并更新路线图完成口径。

## 验收

1. 21 个真实实现按映射归位，无新顶层目录、无 adblab 壳或同名模块。
2. 按基线 AST 对照，除导入路径/排序与说明中的类型路径外无逻辑变化；不规范化普通业务字符串。
3. 直接测试与受影响消费者覆盖成功、失败、取消、关闭及替换边界；所有测试保存原生退出码。
4. 用户数据目录、配置键、归档格式、资源/工具标识和 ADB 命令不变。
5. 基线已有失败单独记录、定位，不能跳过或归因为本轮迁移；确认的阻塞问题以独立最小修复处理。
6. 独立审阅、静态检查、文档检查、源码 packaging 自检及删除后的闭包检查通过。
7. 不提交、不推送；真实设备、多平台、原生桌面视觉和实际冻结产物属于未验证边界。
