# 设备上下文独立化设计

日期：2026-10-22。状态：用户已确认，2026-10-23 完成代码迁移、自动回归与独立审阅。核对基线：`e0c0d04`。

用户已同意按功能渐进推进全项目重构，第一阶段独立设备上下文，并保持现有功能和数据兼容。
本文保留这一阶段确认的状态归属、接口和验收边界；当前实现事实由知识库架构与数据流文档维护。
后续 Controller、业务用例、执行器、持久化及目录归并分别实施，不与这一阶段混合。

## 1. 目标与范围

把设备选择、最近成功发现列表和发现状态从 Qt 控件及 SidePanel 的分散字段中迁到纯 Python
`DeviceContext`。每个 SidePanel 拥有一个上下文实例，DeviceManager 使用同一实例；MainFrame
和功能页继续通过现有公共接口读取不可变快照。

本阶段保持 Python 3.11、PySide6 和现有依赖，不新增生产依赖，不修改版本、CI/CD、发布流程、
ADB 命令、扫描代次或任务资源归属。保留现有界面、信号签名、功能路由、JSON/YAML 格式和存储路径。
连接历史、设备元数据和设置持久化继续沿用原实现；不把它们复制到 DeviceContext。
隐藏 DeviceManager 及其布局仍保留，先解除状态对它的依赖。

## 2. 当前调用链及迁移落点

| 入口 | 当前事实 | 本阶段调整 |
| --- | --- | --- |
| [DeviceManager.selected_devices](../../../gui/panels/device_manager.py) | 从列表行复选状态和 UserRole 读取目标 | 从共享上下文读取保留的勾选；列表点击成为状态提交入口 |
| [DeviceManagerView.update_device_list](../../../gui/panels/device_manager_view.py) | 增量增删列表、保留存续行勾选、写 SidePanel 缓存 | 先提交上下文，再按状态更新行；保留控件复用和布局刷新 |
| [SidePanel](../../../gui/panels/side_panel.py) | 缓存发现列表/状态，过滤公开目标，处理手动刷新恢复 | 拥有上下文并桥接 Qt 信号，公开查询和提交入口保持兼容 |
| [DeviceContextSnapshot](../../../adblab/application/device_context.py) | 只有三个不可变字段 | 保留字段及其现有语义；同模块增加状态对象 |
| [MainFrame](../../../gui/main_frame.py) | 消费快照并向功能页投影，关闭时拒绝晚到设备列表 | 继续消费同一快照接口；业务准入和关闭保护不迁入控件或新状态对象 |

现状依据另见[设备数据流](../../project-knowledge/DATA_FLOW.md#设备发现与元数据流)和
[业务目标规则](../../project-knowledge/BUSINESS_FLOW.md#workspace-路由目录)。

## 3. 状态归属

DeviceContext 不导入 Qt、GUI、core、DeviceStore 或文件系统服务，不启动线程、Timer 或观察者。
生产路径的修改和快照读取均由 Qt 主线程串行调用；后台扫描结果仍经现有信号和代次校验后提交。
对象不新增全局单例或跨线程共享入口，因此不引入无用途的锁。

对象内部保存以下状态：

| 状态 | 语义 |
| --- | --- |
| 最近发现列表 | 最近一次成功设备列表，按输入首次出现顺序去重；失败不覆盖 |
| 稳定展示顺序 | 存续设备保持原行顺序，新设备按发现顺序追加；用于保持既有选择输出顺序 |
| 保留的勾选 | 稳定展示顺序中的已勾选子集；与当前是否允许提交操作区分 |
| 发现状态 | `scanning`、`ready`、`empty`、`unavailable`；初始为 `scanning` |
| 手动刷新前状态 | 仅用于现有刷新被取代时恢复状态；新终态到达后失效 |

`DeviceContextSnapshot` 的三个字段维持兼容：

- `selected_devices`：公开操作目标。`unavailable` 时为空；其他状态返回最近在线集合中的保留勾选。
- `connected_devices`：最近成功发现列表，保留扫描顺序，不以是否勾选为条件。
- `discovery_state`：当前发现状态。

快照及列表查询返回不可变 tuple；SidePanel、DeviceManager 原有 list 返回接口继续生成副本。
既有快照不会随后续修改改变。不同窗口或测试实例之间不共享状态。

## 4. 最小接口

在 `adblab/application/device_context.py` 中增加以下接口；不创建额外通用状态管理框架：

```python
class DeviceContext:
    def snapshot(self) -> DeviceContextSnapshot: ...

    @property
    def checked_devices(self) -> tuple[str, ...]: ...

    @property
    def display_devices(self) -> tuple[str, ...]: ...

    def replace_connected_devices(self, devices: Iterable[str]) -> None: ...
    def set_selected_devices(self, devices: Iterable[str]) -> None: ...
    def set_discovery_state(self, state: str) -> bool: ...
    def begin_refresh(self) -> bool: ...
    def restore_superseded_refresh(self) -> bool: ...
```

- `replace_connected_devices` 替换成功列表，更新稳定顺序并移除已离线设备的勾选；不自动勾选，
  不修改发现状态。Qt 入口将原有 `None` 列表参数转换为空序列。
- `set_selected_devices` 按成员关系提交选择，忽略当前列表之外的目标和重复项；输出遵循稳定
  展示顺序，不采用调用者传入的选择顺序，不新增字符串裁剪或设备标识转换。此入口不增加
  `ready` 限制：全局选择器现可在扫描或不可用期间修改保留勾选，实际操作准入仍由原入口决定。
- `set_discovery_state` 沿用 `str(state or "empty").lower()` 及未知值回退 `empty` 的行为；返回
  发现状态是否变化，非 `scanning` 状态清除刷新恢复信息。单独设置状态不清空发现列表或勾选。
- `begin_refresh` 在已经 `scanning` 时返回 False；否则保存原状态并转为 `scanning`，返回 True。
- `restore_superseded_refresh` 仅在仍为 `scanning` 且有保存的原状态时恢复，消费恢复信息；
  返回状态是否改变。已有新成功/失败状态时不覆盖它。

SidePanel 在创建子控件前构造上下文并显式交给 DeviceManager。DeviceManager 的原有构造方式仍可用，
独立构造时创建自己的上下文；SidePanel 路径始终显式传入唯一实例。

## 5. 必须保持的行为

| 条件 | 预期行为 |
| --- | --- |
| 初次发现一台或多台设备 | 显示候选但全部未勾选，不自动开启功能会话 |
| 更新成功列表 | 保留仍在线设备的勾选，去除离线设备，新增设备不勾选 |
| 设备离线后重新出现 | 作为新增设备，不恢复已经移除的旧勾选 |
| 发现顺序改变 | `connected_devices` 反映新发现顺序；存续行及所选目标保持原稳定顺序 |
| 请求包含重复或列表外设备 | 重复选择归一，列表外目标忽略 |
| `scanning` | 保留最近列表和选择；普通 App/System 动作保持当前准入，Remote 等现有 ready-only 入口仍各自校验 |
| `unavailable` | 保留最近列表与原勾选，公开操作目标为空；恢复状态后按原规则投影 |
| 成功返回空列表 | 清空列表和勾选，再进入 `empty`；不同于扫描失败 |
| 仅设置 `empty` 状态 | 保持当前独立状态提交语义，不隐式模拟一次成功空列表 |
| 扫描期间重复手动刷新 | 不重复发送请求；被取代时恢复原状态，已有更新快照优先 |
| 清空选择或改选设备 | 已运行任务保留原目标及停止入口，缓存会话保留 |
| 后台宿主等待设备 | 不提前消费 pending route/payload，继续由现有前台激活规则处理 |
| 元数据更新 | 只更新显示信息，不新增选择或拓扑通知 |
| 窗口关闭后的晚到结果 | 沿用当前关闭和 generation 准入保护，不重新创建对象或启动任务 |

例如，先发现 `[a, b]` 并全选，再发现 `[b, a, c]`：发现快照为 `(b, a, c)`，展示顺序仍是
`(a, b, c)`，所选目标为 `(a, b)`。随后成功发现 `[b, c]`，再发现 `[a, b, c]`：展示顺序为
`(b, c, a)`，只有 `b` 保持勾选。

ADB 客户端检测中的 `checking/missing_adb` 不属于本上下文状态，不在本次新增映射。
设备历史也不表示在线或已选中，不用于初始化 DeviceContext 的选择。

## 6. Qt 适配与通知

Qt 适配继续使用现有 SidePanel、DeviceManager 和 DeviceManagerView，不增加另一套事件总线。

1. 原列表单行勾选、全选、清空及公共 `set_selected_devices()` 都先修改同一上下文，再更新视图。
   单行事件只提交用户改变的设备；批量选择提交完整目标集合。程序刷新列表时使用现有
   `QSignalBlocker`，不让渲染重新作为用户选择提交。
2. `DeviceManager.selected_devices` 继续暴露保留勾选；`SidePanel.selected_devices` 继续暴露经发现
   状态过滤的操作目标。两者在 `unavailable` 时本来就不同，不能为统一命名合并其语义。
3. `selected_devices_changed(list)` 保持原始勾选载荷。消费者继续通过 SidePanel 拉取有效快照。
   一次显式批量选择仍只交付一次选择通知；已有列表刷新/动作刷新发出的通知也保留，不能仅凭
   前后值相等就统一取消通知。
4. 成功列表更新保持当前顺序：提交列表及勾选、渲染并通知选择，再提交并渲染 `ready/empty`。
   `device_discovery_state_changed(str)` 仍仅在状态变化时发送。纯状态对象不自行发送这些信号。
5. 手动刷新在上下文变更后，由适配层根据前后快照渲染并发送状态变化，再发出刷新请求。
   恢复被取代刷新也用同样的前后状态比较，避免先修改状态导致漏发通知。
6. 现有 DeviceManager、列表行、按钮和 QObject 父子归属保留；更新与重排不重建所有控件。
   概览、选择器、Remote、WorkspaceFeatureHost 继续使用原有接口及锁定策略。

原 `_connected_device_cache`、`_device_discovery_state` 和刷新恢复字段不再保存独立可写副本。
如迁移期间需要兼容读取，属性应从上下文派生。测试对私有字段的写入改为真实提交入口或纯状态
测试；保留原有用户行为断言，不添加只服务测试的第二套生产状态路径。

## 7. 文件边界与迁移步骤

| 文件 | 责任 |
| --- | --- |
| `adblab/application/device_context.py` | 现有快照及新的纯状态对象 |
| `gui/panels/side_panel.py` | 唯一实例组装、兼容查询、发现/刷新状态与 Qt 通知桥接 |
| `gui/panels/device_manager.py` | 选择事件及批量选择提交、保留勾选查询 |
| `gui/panels/device_manager_view.py` | 成功列表的适配与状态投影，元数据展示和布局保持 |
| `tests/test_device_context.py`（新增） | 不依赖 Qt 的状态转换、顺序、快照与实例隔离测试 |
| 现有相关 Qt 测试 | 验证选择通知、操作准入、会话恢复、原目标停止和控件复用 |

先用测试固定现有规则，再增加状态对象，随后将 SidePanel 和 DeviceManager 同时接到同一实例，
最后迁移私有字段消费者和更新现状文档。新的实例必须接入全部生产选择入口后才算完成；
不能把“增加了纯状态类、控件仍独立保存业务状态”作为本阶段交付。

本阶段不迁移 DeviceStore、Controller、FeatureSessionRegistry 或目录结构。
架构与数据流事实在实现通过后分别更新到
[ARCHITECTURE](../../project-knowledge/ARCHITECTURE.md)和
[DATA_FLOW](../../project-knowledge/DATA_FLOW.md)，本文仅保留阶段设计与验收依据。

## 8. 验收与验证边界

纯逻辑测试覆盖第 5 节的状态表、不可变快照、不共享实例、输入集合副本，以及禁止导入 Qt/GUI
仍可运行的边界。特别补齐扫描重排、离线重连、未知目标、重复选择和刷新恢复竞态。

直接 Qt 回归选择
[test_model_panels.py](../../../tests/test_model_panels.py) 的设备列表/选择/发现/刷新节点，以及
[test_global_device_context.py](../../../tests/test_global_device_context.py) 的公开快照、手动刷新、
单选和多选提交节点。迁移私有字段后，对原测试替身同步提供真实的新接口，不放宽断言。

关联回归依据实际消费者选择：

- [test_workspace_device_recovery.py](../../../tests/test_workspace_device_recovery.py)：pending route 与前台恢复。
- [test_session_device_admission.py](../../../tests/test_session_device_admission.py)：取消选择后的准入、晚到回调和停止原任务。
- [test_remote_selector_integration.py](../../../tests/test_remote_selector_integration.py)：Remote 选择锁与发现更新。
- [test_flat_feature_navigation.py](../../../tests/test_flat_feature_navigation.py)：一次选择提交和批量目标保持。
- [test_ui_delivery_order.py](../../../tests/test_ui_delivery_order.py)：已有发现代次与发布顺序。
- [test_async_state_regressions.py](../../../tests/test_async_state_regressions.py)：手动刷新进入/退出扫描状态。
- [test_responsive_panels.py](../../../tests/test_responsive_panels.py)：设备行复用及真实 checkbox 操作。

实现完成后对实际修改文件运行 Ruff、中文注释检查；对共享类型及其消费者运行 Pyright，
同步文档后运行链接检查和 `git diff --check`。本地 Pyright 的系统 site-packages 解析差异需
单独说明，不能用空分析范围或修改检查标准得到通过结论。

本阶段不新增线程、进程、持久化或打包入口；直接及关联测试通过后按
[增量验证策略](../../guides/TESTING_GUIDE.md#增量验证策略)决定是否扩大，不自动全量测试或构建。
离屏测试不能代替真实设备、真实窗口和冻结产物验证。

设计前基线记录（2026-10-22，`e0c0d04`）：选择/列表/刷新及公开快照的 12 个 pytest 节点，
加上 `test_workspace_device_recovery.py`、`test_session_device_admission.py` 和
`test_remote_selector_integration.py` 三个文件，共 53 项通过。执行使用 `.venv`、离屏 Qt、
临时 `LOCALAPPDATA/XDG_CONFIG_HOME` 并禁用 pytest 缓存；99 条警告来自现有第三方弃用 API。
这是迁移前的行为基线，不表示新的 DeviceContext 已实现或通过测试。

## 9. 审阅结论与实施入口

用户于 2026-10-22 确认设计符合要求，授权继续制定实施计划。确认边界包括保留勾选与有效目标的
区分、两种顺序的兼容、信号发布顺序，以及第一阶段不改变持久化与任务生命周期。
后续任务、测试与执行安排见[实施计划](../plans/2026-10-22-device-context.md)。
此文不授权 Git 提交或推送，所有未提交文件继续留在工作区供审阅。
