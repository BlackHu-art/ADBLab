# 设备上下文独立化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将设备选择、最近成功发现列表和发现状态迁入纯 Python DeviceContext，保持现有功能、信号与数据兼容。

**Architecture:** SidePanel 在创建控件前拥有唯一 DeviceContext，并显式注入 DeviceManager。控件提交用户选择并投影视图，MainFrame 和功能页继续读取原有三字段快照；状态对象不承担扫描、元数据、持久化或会话生命周期。

**Tech Stack:** Python 3.11、PySide6、现有 qfluentwidgets、pytest、Ruff、Pyright；使用仓库 `.venv`。

**Spec:** [已确认的设备上下文独立化设计](../specs/2026-10-22-device-context-design.md)

## Global Constraints

- 本阶段保持 Python 3.11、PySide6 和现有依赖，不新增生产依赖，不修改版本、CI/CD、发布流程、ADB 命令、扫描代次或任务资源归属。
- 保留现有界面、信号签名、功能路由、JSON/YAML 格式和存储路径。
- 连接历史、设备元数据和设置持久化继续沿用原实现；不把它们复制到 DeviceContext。
- 隐藏 DeviceManager 及其布局仍保留，先解除状态对它的依赖。
- DeviceContext 不导入 Qt、GUI、core、DeviceStore 或文件系统服务，不启动线程、Timer 或观察者。
- 生产路径的修改和快照读取均由 Qt 主线程串行调用；后台扫描结果仍经现有信号和代次校验后提交。
- 保留 DeviceContextSnapshot 的 frozen/slots 和三个字段；list 兼容接口返回副本，不持久化选择。
- 不新增全局单例、跨线程共享入口、锁或事件总线；不迁移 Controller、DeviceStore、FeatureSessionRegistry 或目录结构。
- 按根 AGENTS.md 保留既有未提交修改，中文注释；本计划不授权 commit、push、变更依赖或发布。

## Review Focus

1. `unavailable` 下原勾选仍在、有效目标为空，恢复后重新投影；扫描中普通 App/System 与 Remote 的准入差异保持。（任务 1、2、3）
2. 发现重排与离线重连：发现顺序可变、存续行和选择顺序稳定，离线勾选不复活。（任务 1、2）
3. 控件回写造成重复信号或改变发布时序：保留原始载荷、旧状态下的选择通知及原有刷新通知。（任务 2）
4. 被取代的手动刷新不能覆盖新结果，重复刷新不重复提交，失败与成功空列表不同。（任务 1、2、3）
5. 预装状态被 UI 初始化清空、不同窗口串状态、晚到回调或改选影响原会话停止目标。（任务 1、2、3）

---

## 执行边界与文件地图

状态：2026-10-22 设计、计划与 Native 执行方式均获用户确认；2026-10-23 完成代码、自动回归与独立审阅。核对基线 `e0c0d04`。
执行前读取根 AGENTS.md、docs/README.md、设计及目标目录局部规则，再检查 `git status --short`
和目标文件差异。当前仅有本阶段设计和入口索引的文档变更；出现后续改动时重新核对归属。
隔离工作区的选择在执行时处理，不以创建 worktree 丢失已确认的未提交设计和计划。

| 文件 | 改动责任 |
| --- | --- |
| `adblab/application/device_context.py` | 新增纯状态对象，保留现有快照 |
| `gui/panels/side_panel.py` | 唯一实例组装、查询、发现状态与刷新信号桥接 |
| `gui/panels/device_manager.py` | 可选注入、选择提交、勾选投影 |
| `gui/panels/device_manager_view.py` | 成功列表提交、增量渲染、保留动作刷新 |
| `tests/test_device_context.py`（新建） | 纯状态规则及无 GUI/服务依赖导入测试 |
| `tests/test_device_context_adapter.py`（新建） | Qt 桥接、信号时序、构造与控件复用 |
| `tests/test_test_collection.py` | 新纯逻辑套件禁止 Qt 导入的实际运行回归 |
| `tests/test_model_panels.py`、`tests/test_global_device_context.py`、`tests/test_async_state_regressions.py`、`tests/test_remote_services.py` | 迁移旧私有状态依赖，保留原行为断言 |
| `docs/project-knowledge/ARCHITECTURE.md`、`docs/project-knowledge/DATA_FLOW.md`、`docs/project-knowledge/MODULE_MAP.md` | 实现验收后同步对象归属、数据流和模块索引 |
| `docs/README.md`、本计划及设计 | 阶段状态与验证记录，不把未实现方案写成当前事实 |

MainFrame、功能页、Controller 和 DeviceStore 是关联验证范围，预计不改生产代码。任务 2
三个 Qt 文件作为一次协调迁移，不拆给多个写入者；独立审阅可并行进行。

## Task 1: 建立纯状态对象与测试

**Files:** 修改 `adblab/application/device_context.py`、`tests/test_test_collection.py`；新建 `tests/test_device_context.py`。

**Interfaces:**
- Consumes: 现有 `DeviceContextSnapshot(selected_devices: tuple[str, ...], connected_devices: tuple[str, ...], discovery_state: str)`。
- Produces: `DeviceContext()`，初始快照 `DeviceContextSnapshot((), (), "scanning")`；以下方法供任务 2 使用。

```python
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

- [x] **1.1 添加状态规则测试。** 在新测试文件中使用真实 DeviceContext；仅导入标准库、pytest 和状态模块。以下准备步骤与断言构成测试契约，参数化覆盖所有列出的状态。

| 测试名 | 准备/动作 | 必须断言 |
| --- | --- | --- |
| `test_initial_and_new_devices_are_not_selected` | 新实例；提交 `["a", "a", "b"]` | 初始 `snapshot() == DeviceContextSnapshot((), (), "scanning")`；随后 `connected_devices == ("a", "b")`，`checked_devices == ()`，状态仍 `"scanning"` |
| `test_reordering_and_reconnection_preserve_only_surviving_checks` | 见下方完整行为示例 | 两种顺序及重连不恢复勾选 |
| `test_selection_uses_membership_without_normalizing_identifiers` | 连接 `[" a ", "b"]`；选择生成器产生 `["b", "missing", " a ", "b", "a"]` | `checked_devices == (" a ", "b")`；不裁剪标识，不采用选择输入顺序 |
| `test_unavailable_retains_checks_but_masks_operation_targets` | 连接 `["a", "b"]` 并选中 a；逐一设置 `"ready"`、`"scanning"`、`"unavailable"`；不可用时改选 b 后恢复 ready | 前两种状态 `selected_devices == ("a",)`；不可用时 `checked_devices == ("a",)`、`selected_devices == ()`；恢复后 `selected_devices == ("b",)` |
| `test_state_normalization_does_not_replace_inventory` | 连接并选中 a；依次设置 `"READY"`、`"ready"`、`"unknown"`、`""` | 返回值依次 `True, False, True, False`；最后状态 `"empty"`，在线与勾选仍为 `("a",)`；再提交空列表才清空两者 |
| `test_refresh_restores_once_and_rejects_duplicates` | 对 `"ready"`、`"empty"`、`"unavailable"` 分别 begin 两次、restore 两次 | 返回值 `True, False, True, False`；两次 begin 后状态 scanning，首次 restore 后状态等于原状态；初始 scanning 的 begin/restore 都为 False |
| `test_terminal_state_invalidates_refresh_restore` | 从 a/ready 开始刷新；ready 分支提交 `["b"]`，empty 分支提交 `[]`，unavailable 分支不换列表；分别设置新终态 | `restore_superseded_refresh() is False`；终态分别保持 `"ready"/"empty"/"unavailable"`，connected_devices 分别为 `("b",)/()/("a",)` |
| `test_inputs_snapshots_and_instances_are_isolated` | 用可变列表 `["a"]` 提交连接与选择，并置 ready；保存快照；清空输入、更新原实例、创建第二实例 | 输入清空不改状态；原快照仍为 `DeviceContextSnapshot(("a",), ("a",), "ready")`；修改快照抛 `FrozenInstanceError`；第二实例为初始空状态 |

```python
def test_reordering_and_reconnection_preserve_only_surviving_checks():
    context = DeviceContext()
    context.replace_connected_devices(["a", "b"])
    context.set_selected_devices(["b", "a", "b", "missing"])
    context.replace_connected_devices(["b", "a", "c"])
    assert context.snapshot().connected_devices == ("b", "a", "c")
    assert context.display_devices == ("a", "b", "c")
    assert context.checked_devices == ("a", "b")
    context.replace_connected_devices(["b", "c"])
    context.replace_connected_devices(["a", "b", "c"])
    assert context.display_devices == ("b", "c", "a")
    assert context.checked_devices == ("b",)
```

- [x] **1.2 确认红灯。** 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_context.py`，预期缺少 DeviceContext 导致收集失败；先排除解释器/依赖故障，不能将环境失败当作行为红灯。
- [x] **1.3 实现纯状态对象。** 在原快照模块按上述签名实现；使用实例字段保存最近列表、稳定顺序、勾选和刷新前状态，不保留输入引用。规则严格按设计第 4–5 节，包括非 scanning 提交即清除恢复信息；修正原快照 docstring 中“所有操作都要求 ready”的不准确概括。
- [x] **1.4 验证独立运行边界。** 新增 `test_device_context_imports_without_gui_or_services`：在独立解释器、仓库根 cwd 中用 MetaPathFinder 拒绝 `PySide6/qfluentwidgets/gui/core/models/services` 导入，再导入 DeviceContext 并执行连接/勾选/快照，断言子进程 `returncode == 0`，失败时显示 stdout/stderr；不在已经加载 core 的主 pytest 进程中判定此边界。
- [x] **1.5 验证纯套件收集。** 在 `tests/test_test_collection.py` 新增以下测试，复用既有 `_run_pytest` 的进程隔离与超时，不改全局 Qt 夹具或 marker 分配规则。

```python
def test_device_context_suite_runs_without_qt(tmp_path):
    result = _run_pytest(tmp_path, ["-q", "tests/test_device_context.py"], block_qt=True)
    assert result["collected"]
    assert set(result["passed"]) == set(result["collected"])
    assert result["qt_modules"] == []
    assert not result["has_settings_singleton"]
```

- [x] **1.6 确认绿灯与差异。** 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_context.py tests/test_test_collection.py::test_device_context_suite_runs_without_qt`，预期全部通过；检查 diff，确认无 Qt/服务依赖及公共快照字段变化。此时只完成纯对象，不能宣称 Qt 已迁移。

## Task 2: 将 Qt 入口接到唯一上下文

**Files:** 修改三个 `gui/panels/` 目标文件及地图中的四个现有测试文件；新建 `tests/test_device_context_adapter.py`。

**Interfaces:**
- Consumes: 任务 1 的完整 DeviceContext API；现有 Qt 信号、DeviceStore 元数据查询和控件布局接口。
- Produces: `DeviceManager.__init__(self, panel, parent=None, *, device_context: DeviceContext | None = None) -> None`；保留旧调用方式，未注入时创建独立实例。
- Produces: SidePanel 原构造及 `selected_devices -> list[str]`、`device_context_snapshot() -> DeviceContextSnapshot`、`set_selected_devices(devices: list[str]) -> None`、`update_device_list(devices: list[str] | None = None)`、`set_device_discovery_state(state: str) -> None`、`request_device_refresh() -> bool`、`on_device_refresh_superseded() -> None` 均保持兼容。
- Internal: SidePanel `_device_context: DeviceContext` 与 `_publish_discovery_state(previous_state: str) -> None`；DeviceManager `_device_context: DeviceContext`、`_on_device_item_changed(item: QListWidgetItem) -> None`、`_render_selected_devices() -> None`；DeviceManagerView `_render_device_list() -> None`。

- [x] **2.1 先固定适配行为。** 新文件设置 `pytestmark = pytest.mark.ui`，沿用 QApplication/隔离夹具；用 fixture 构造并清理真实 SidePanel，mock 元数据读取，不启动真实 ADB。新增以下测试后运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_context_adapter.py`；旧行为测试可先通过，新增共享对象/注入测试应在适配完成前失败，记录具体失败点。

| 测试名 | 准备/动作 | 必须断言 |
| --- | --- | --- |
| `test_panel_and_manager_share_context_and_queries_do_not_read_rows` | 创建 SidePanel；连接、选中 a；用 QSignalBlocker 清空列表行，模拟暂时没有投影视图 | `manager._device_context is panel._device_context`；两者查询仍为 `["a"]`；快照仍为 `DeviceContextSnapshot(("a",), ("a",), "ready")` |
| `test_injected_context_survives_ui_build_and_instances_are_independent` | 用预装 a/ready/勾选的上下文构造并 build_ui；另构造未注入的 manager 和第二 SidePanel | 原上下文快照不变，a 行已勾选；其余实例快照初始为空且相互不是同一对象 |
| `test_reordered_scan_reuses_surviving_rows_and_matches_context` | 按任务 1 重排/离线/重连序列更新真实 SidePanel | 存续 a/b 的 QListWidgetItem 身份不变；列表最终 `["b", "c", "a"]`，selected 为 `["b"]`；新行不勾选 |
| `test_selection_entries_publish_once_without_render_echo` | 参数化公共 setter、全选、清空、真实 checkbox 点击、双击；每次动作前清空 signal spy | 一次动作选择通知计数 `== 1`，raw 载荷与预期勾选一致；连续两次相同公共 setter 各自仍有一次通知；getter 返回列表修改不影响状态 |
| `test_list_refresh_keeps_raw_payload_and_state_publication_order` | 连接/选中 a，再置 unavailable；捕获载荷和回调当时快照；更新 `["a", "b"]` | 事件依次 `("selection", ("a",), "unavailable", ())`、`("state", "ready", ("a",))`；再刷新相同列表仍发一次选择通知，无状态通知 |
| `test_manual_refresh_publishes_state_before_request_and_restores_once` | 从 ready 连续刷新两次，再通知被取代；另分支在被取代前到达新成功列表 | 首次 `True`、第二次 `False`；事件依次 state/scanning、refresh、state/ready；新结果分支最终快照不被覆盖 |
| `test_item_metadata_change_keeps_action_refresh_without_selection_submission` | 已选 a；修改现有列表行文本，监测 context 的选择提交和原选择信号 | 上下文选择提交调用次数 `== 0`，原动作刷新通知次数 `== 1`，raw 为 `["a"]`；不将 metadata 的 itemChanged 当成用户改选 |

- [x] **2.2 接入构造和查询。** SidePanel 在 `_create_ui` 前创建 `_device_context` 并显式注入 DeviceManager；后者保留位置参数兼容。两个 selected getter 分别返回有效目标/保留勾选的 list 副本，快照直接委托上下文。build_ui 只渲染已有状态，不通过 `update_device_list(None)` 清空注入的数据。
- [x] **2.3 接入单行和批量选择。** DeviceManager 的 setter 先提交上下文，再用 `_render_selected_devices()` 在 QSignalBlocker 内写复选状态，最后走原 `_update_action_states()`。`_set_all_checked(checked: bool)` 通过同一 setter 提交全部 display_devices 或空集合。itemChanged 只按当前行与上下文的差异提交一次增删；检查状态未变时保留原动作刷新，但不提交选择。双击和原生点击继续只切换 CheckState，避免重复提交。
- [x] **2.4 接入成功列表投影。** DeviceManagerView.update_device_list 将 None 转为 `()`，只调用一次 `replace_connected_devices`；随后 `_render_device_list()` 按 display_devices/checked_devices 增量增删和复用行。保留 DeviceStore 元数据、Detecting 占位、行卡片、父子归属、doItemsLayout、最小高度和 reflow；渲染在 QSignalBlocker 中且不通知。外层继续刷新动作并发送原 raw 选择通知，视图不决定 ready/empty。
- [x] **2.5 接入发现和刷新。** SidePanel 正常 setter 保存旧状态、提交新状态，再 `_publish_discovery_state(old)` 渲染；只在前后状态不同才刷新已加载功能动作并发状态信号。begin/restore 同样先保存旧值再调用上下文，不能再次调用 setter 丢失比较。刷新请求必须在 scanning 已发布后发送；SidePanel.update_device_list 保留“列表及选择通知 → ready/empty”的时序。
- [x] **2.6 移除旧的独立存储并迁移测试。** 删除 `_connected_device_cache`、`_device_discovery_state`、`_manual_refresh_previous_state` 的可写副本；检查状态常量是否仍有消费者。以下原测试改用公开提交/快照，三个列表替身显式注入真实 DeviceContext；不保留只供测试写入的兼容字段。

| 文件 | 需迁移的现有节点（均保留原行为断言） |
| --- | --- |
| `tests/test_model_panels.py` | `test_side_panel_selection_is_a_unique_online_snapshot`；`test_device_manager_shows_placeholder_for_new_unstored_device`；`test_device_manager_updates_device_list_incrementally`；`test_device_manager_none_device_list_clears_without_model_lookup`；`test_side_panel_refresh_owns_scanning_state_and_rejects_duplicates` |
| `tests/test_global_device_context.py` | `test_superseded_manual_refresh_restores_state_and_allows_retry`；`test_superseded_refresh_cannot_replace_new_device_snapshot` |
| `tests/test_async_state_regressions.py` | `test_reordered_discovery_restores_panel_state_and_refresh_button` |
| `tests/test_remote_services.py` | `test_remote_panel_controls_follow_full_session_state`：以 update_device_list/set_selected_devices 准备在线勾选，保留 idle/starting/running/stopping 的全部按钮契约 |

- [x] **2.7 执行直接回归。** 修改边界是状态适配、列表事件与测试替身，因此先运行下列命令；预期全部通过，不新增 Qt 对象残留或 teardown 错误。读取差异，确认历史下拉框逻辑、原生 checkbox 和布局入口仍走原路径。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$deviceDirect = @(
    "tests/test_device_context_adapter.py",
    "tests/test_model_panels.py",
    "tests/test_global_device_context.py::test_public_device_snapshot_preserves_admission_and_is_immutable",
    "tests/test_global_device_context.py::test_connection_history_is_a_value_snapshot",
    "tests/test_global_device_context.py::test_superseded_manual_refresh_restores_state_and_allows_retry",
    "tests/test_global_device_context.py::test_superseded_refresh_cannot_replace_new_device_snapshot",
    "tests/test_global_device_context.py::test_picker_updates_two_targets_once_and_refresh_does_not_emit",
    "tests/test_global_device_context.py::test_single_picker_switches_one_target_once_and_allows_clear",
    "tests/test_async_state_regressions.py::test_reordered_discovery_restores_panel_state_and_refresh_button",
    "tests/test_remote_services.py::test_remote_panel_controls_follow_full_session_state"
)
.\.venv\Scripts\python.exe -m pytest -q @deviceDirect
```

## Task 3: 消费者验收与当前事实收口

**Files:** 验证下列既有测试；修改地图中的三份现状文档和阶段索引。仅当缺少下表行为断言时，在对应现有测试中补充，不扩大生产迁移范围。

**Interfaces:**
- Consumes: 任务 2 保持的 SidePanel/DeviceManager 公共接口、原始选择信号，以及不可变 DeviceContextSnapshot。
- Produces: 有命令和结果的阶段验收记录；现状文档明确 SidePanel 所有、纯上下文真源、Qt 适配提交/投影、原会话归属不变。

- [x] **3.1 核对消费者契约。** 在运行前逐一核对以下既有行为，不把读源码当作测试通过；若补充断言，先在现实现上运行并确认其有效性。

| 契约 | 现有证据与验收断言 |
| --- | --- |
| scanning/失败准入及原任务停止 | model_panels 的 `test_discovery_failure_blocks_new_actions_but_preserves_selection_and_recording_stop`；global_device_context 的公开快照测试：扫描中 `selected_devices == ("demo-b",)`，`_remote_operation_devices() == []`；session_device_admission 覆盖停止原任务及晚到回调 |
| 前台恢复及选择锁 | workspace_device_recovery 保留未激活 pending route，不因单台在线自动选择；remote_selector_integration 保留运行会话锁定；已有断言不得改成接受新的自动切换行为 |
| 元数据不扩大选择通知 | global_device_context 的 brand/model 与 Android version 两节点；ui_delivery_order 的 metadata 与 metric 两节点；选择通知计数保持原断言，显示信息仍更新 |
| 刷新代次与关闭 | ui_delivery_order、async_state_regressions、model_mainframe、phase2_mainframe_shutdown_gate 中下列节点；旧结果/关闭后回调不得覆盖快照、重新启动任务或发出销毁对象警告 |
| 控件复用及销毁 | responsive_panels 的 reflow 节点、global_device_context 的 hidden coordinator 销毁节点；保持对象身份、单次信号及实际销毁断言 |

- [x] **3.2 执行关联回归。** 扩大原因是同一快照同时被会话、发现投递、功能宿主和关闭路径消费。下列集合与任务 2 重复节点不重跑；失败先定位直接原因/顺序污染，修复后只重跑受影响组合。

```powershell
$deviceRelated = @(
    "tests/test_workspace_device_recovery.py",
    "tests/test_session_device_admission.py",
    "tests/test_remote_selector_integration.py",
    "tests/test_ui_delivery_order.py",
    "tests/test_flat_feature_navigation.py::test_device_workbench_selection_commits_once_through_device_manager",
    "tests/test_async_state_regressions.py::test_only_latest_manual_discovery_publishes_in_any_completion_order",
    "tests/test_global_device_context.py::test_brand_or_model_refresh_updates_only_its_device_without_selecting",
    "tests/test_global_device_context.py::test_android_version_refresh_updates_open_picker_without_changing_targets",
    "tests/test_global_device_context.py::test_window_destruction_releases_hidden_device_coordinator",
    "tests/test_responsive_panels.py::test_device_reflow_preserves_objects_state_and_single_signal_delivery",
    "tests/test_model_mainframe.py::test_main_frame_syncs_device_context_to_every_task_page",
    "tests/test_model_mainframe.py::test_main_frame_device_refresh_uses_side_panel_state_owner",
    "tests/test_model_mainframe.py::test_main_frame_shutdown_disconnects_scan_callbacks_without_warning",
    "tests/test_phase2_mainframe_shutdown_gate.py::test_late_scan_notifications_are_ignored_after_close_starts",
    "tests/test_workspace_feature_host.py::test_host_projects_selection_before_connection_and_activation",
    "tests/test_workspace_feature_host.py::test_batch_selection_growth_does_not_preselect_single_device_session",
    "tests/test_workspace_feature_host.py::test_idle_overview_adopts_new_unique_batch_target_until_user_chooses",
    "tests/test_workspace_feature_host.py::test_workspace_suspends_and_resumes_feature_across_navigation"
)
.\.venv\Scripts\python.exe -m pytest -q @deviceRelated
```

- [x] **3.3 运行静态检查。** 共享类型接口已变，因此 Pyright 包含 Qt 适配与 MainFrame 消费者；若实际修改其他 Python 文件，将其补入 Ruff/注释范围，不改规则降低标准。

```powershell
$deviceProduction = @(
    "adblab/application/device_context.py", "gui/panels/side_panel.py",
    "gui/panels/device_manager.py", "gui/panels/device_manager_view.py"
)
$deviceTests = @(
    "tests/test_device_context.py", "tests/test_device_context_adapter.py",
    "tests/test_test_collection.py", "tests/test_model_panels.py",
    "tests/test_global_device_context.py", "tests/test_async_state_regressions.py",
    "tests/test_remote_services.py"
)
.\.venv\Scripts\python.exe -m ruff check @deviceProduction @deviceTests
.\.venv\Scripts\python.exe -m pyright @deviceProduction gui/main_frame.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py @deviceProduction
.\.venv\Scripts\python.exe scripts/check_source_text.py
```

若 Pyright 无法识别 `.venv` 继承的系统 site-packages，先用该解释器读取 sys.path 和 pyvenv.cfg
确认环境。必要时在临时配置中保留仓库原规则、显式生产分析文件并补实际解释器搜索路径后重试；
记录两次结果及分析文件数，不将本机绝对路径写入仓库配置，不以空分析范围、忽略错误或降低标准通过。

- [x] **3.4 同步当前事实。** 验收代码后更新 ARCHITECTURE 的对象归属、DATA_FLOW 的设备选择与发现流、MODULE_MAP 的纯状态模块索引及各自 last_verified；按文档单源规则链接，不复制全套行为表。更新 docs/README 与本阶段设计/计划状态；本计划记录实际命令、通过/失败/未运行和限制，不把基线结果算作重构后结果。
- [x] **3.5 检查文档与最终差异。** 运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py`、`git diff --check`，预期通过；另核对未跟踪新文件。检查旧私有字段没有生产读写、新上下文没有 Qt/持久化依赖、所有选择入口已迁移，且无新增版本/依赖/命令/数据格式变化。
- [x] **3.6 独立审阅并交付。** 由独立 reviewer 审阅最终工作区补丁和上面的五项 Review Focus；有问题时先修复并运行对应直接/关联测试。交付文件范围、实际结果和剩余人工检查；不自动 commit/push，不因任务较长重复已通过测试。

## 验证边界与执行方式

设计前基线已记录在设计第 8 节：53 项通过、99 条第三方弃用警告。它仅证明迁移前行为，
实施时未重复运行旧基线，也未将它算作新实现验收。执行时使用项目已有用户数据隔离夹具；
需要额外启动子进程时复用既有临时环境隔离，不读取或写入真实用户设置与设备历史。

本阶段影响可按上述调用链界定，不预设全量 pytest、真实 ADB 操作或 PyInstaller 构建。
若实现实际触及启动、资源、运行时路径或打包边界，按[测试指南](../../guides/TESTING_GUIDE.md#增量验证策略)
重新确定范围并说明原因。离屏回归不能证明真实设备连接、可见窗口高 DPI 行为或冻结产物通过。
人工验收建议：现有历史仍可读、双设备勾选/刷新/重连、扫描失败恢复、运行中改选后仍可停止原任务、关闭无新增残留。

用户已选择 **Native：主 agent 串行实施三个任务，最后独立审阅**。三个 Qt 适配文件共用状态与
信号时序，保持同一实施上下文；未创建提交、推送或执行发布。

## 实施记录（2026-10-22 至 2026-10-23）

- 任务 1：新增测试先因缺少 DeviceContext 失败；实现后纯状态及禁止 Qt 导入的收集回归共 14 项通过。
- 任务 2：适配前新增套件 3 项共享对象/注入测试失败、8 项既有行为通过；迁移后 11 项全部通过。
  按 `$deviceDirect` 执行的完整直接集合 71 项通过、26 条第三方弃用警告，耗时 37.94 秒。
- 任务 3：按 `$deviceRelated` 执行的关联集合 70 项通过、150 条第三方弃用警告，耗时 44.22 秒。
  实际 pytest 命令增加 `-B`（解释器参数）和 `-p no:cacheprovider`；Qt 使用 offscreen，两个集合的
  LOCALAPPDATA/APPDATA/XDG 目录指向本阶段临时测试目录；所有用例保留原行为断言。
- Ruff、四个生产文件中文注释检查通过；源文本完整性检查通过（699 个文件）。初次 Ruff 的行长和
  已失效测试导入已修正，没有放宽标准。
- 原 Pyright 命令分析 5 个文件，报告 17 个错误，主要为当前 `.venv` 继承的系统 site-packages
  未被解析。临时配置继承仓库规则，仅补实际解释器 extraPaths 与 venvPath，CLI 显式传入同样的
  5 个生产文件，得到 0 错误、0 警告；仓库配置未变。临时配置初次使用绝对 include 导致 0 文件，
  该结果被拒绝，改为显式 CLI 文件后核实分析数量。
- 实施调整：复用当前 ui-redesign 工作区；三个列表 SimpleNamespace 替身改用已有真实 DeviceManager
  构造助手，避免测试另存选择副本；按项目增量验证规则执行直接/关联集合，不重复已通过检查。
- 独立审阅：未发现 Critical/Important 问题，五项 Review Focus 全部符合设计。一条仍称复选框为
  状态源的旧注释已同步；收尾检索同时发现术语表的两处旧定义，更新 `glossary.md` 的 DeviceManager、
  批量目标并加入 DeviceContext 定义。它们属于本阶段状态归属说明，只有注释和文档变化。
- 文档链接/frontmatter 检查通过（53 份），`git diff --check` 通过；新增文件另检 UTF-8、尾部换行、
  行尾空白和冲突标记。所有计划任务已完成，工作区改动保留，未提交或推送。
- 审阅边界：真实设备连接、可见窗口高 DPI 和冻结产物仍需人工/产物验收；原扫描器及会话资源释放
  内部实现不在本次重新审计范围，已核对新快照入口、代次/关闭保护及相关回归。未执行全量 pytest
  或 PyInstaller 构建，本阶段未触及启动、资源收集、外部命令、数据格式或依赖边界。
