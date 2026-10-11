# 设备选择区展开动画实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 执行；当前会话已经授权实施与验证，不提交或推送。

**Goal:** 让既有设备选择区展开、收起平滑，保留设备操作、五行高度与共享材质。

**Architecture:** 在 DevicePicker 外增加透明裁剪容器，内部内容保持自然高度，单个 Qt 动画驱动可见高度和箭头。展开意图独立于动画可见性；宿主快照批量同步，避免反复布局。

**Tech Stack:** Python 3.11、PySide6、现有 qfluentwidgets、pytest 离屏 Qt。

**Spec:** 本会话已确认的五项方案：约 200 ms 过渡、稳定内容、同步按钮反馈、退出清理、合并布局计算。

## 修改范围与约束

- 首版生产修改限于 `gui/widgets/device_context_bar.py`；后续卡顿修复范围见下文。不改变 ADB、设备选择真源、会话及后台任务。
- 不新增依赖、全局配置或页面入口；保留五行及短窗口 45% 上限。
- 云母使用现有父级材质；不增加背景色、截图淡入或透明度效果。
- 快速点击从当前高度反向；切页和窗口隐藏立即完成收起。
- 字体、明暗主题、键盘及鼠标焦点规则不变。

## 执行与验证

- [x] 在 `tests/test_device_selector_animation.py` 补中间帧、反向点击、焦点、隐藏和尺寸变化回归，确认原实现失败。
- [x] 实现透明裁剪、展开意图、统一动画时钟及快照合并；迁移既有测试对最终几何的等待。
- [x] 先运行新测试和 `test_inline_device_selector.py`、`test_device_operation_selector.py`。
- [x] 关联主窗口设备路由及远程控制集成，检查主题、字体和正文重排；仅按实际失败扩大范围。
- [x] 同步 `docs/guides/OPERATION_RESULTS.md` 的展开交互，运行修改文件 Ruff、类型检查、中文注释、文档链接与 diff 检查。

## 审查重点

- 收起中重新展开不能被旧完成回调隐藏。
- 不允许 Tab 或点击操作收起中的设备行。
- 字号和短窗口变化更新目标高度，不将动画中间值作为自然高度。
- 关闭或切页不留下动画、可见残片或后续布局回调。
- 主窗口正文每帧 resize 的成本需要实际 Qt 页面诊断，不能仅依靠独立容器测试。

## 本轮验证记录

- 原实现的动画回归 4 项失败，均复现正文直接跳变；实现后通过。
- 新增鼠标焦点回归先复现过渡中跳到最终高度，再限定键盘焦点提前完成展开。
- 最终直接集合：`test_device_selector_animation.py`、`test_inline_device_selector.py`、
  `test_device_operation_selector.py` 共 61 passed；150% 与 200% 下新动画集各 11 passed。
- 上述直接集合在焦点细化前，与 `test_remote_selector_integration.py`、
  `test_global_device_context.py` 合并运行 198 passed；其中关联路由 139 项。
  最后两项焦点用例及对应局部调整已由最终 61 项直接集合重新验证，没有重跑无关路由。
- Windows 原生平台的云母属性与主题切页 6 passed；主窗口远程控制和应用工具的明暗、
  字号诊断 4 passed。视觉探针使用隔离设置，设备和服务为替身。
- 同条件两设备探针：再次展开的高度及列宽同步各由 7 次降至 1 次；内部列表高度保持不变。
- Ruff、相关模块 Pyright、中文注释检查通过。未改变设备命令或打包边界，未执行实机操作或打包。

## 卡顿反馈后的修复与验证

首版只确认了展开过程与最终几何，没有充分度量主窗口的逐帧响应式规划。收到实际卡顿反馈后，
使用隔离设置、替身设备的真实 MainFrame 测量，确认每次高度变化都会触发顶层 LayoutRequest，
进而递归规划 Remote 内层网格。一次展开的规划累计约 213 ms，动画仅推进 6 次，耗时约 283 ms。

修复边界：

- DeviceContextBar 成对通知过渡开始/完成；MainFrame 转交 SidePanel，组件不直接依赖业务面板。
- ResponsiveCoordinator 暂存过渡期间和此前已排队的请求，结束后按最终几何统一收敛；保留真实
  宽度、字体、主题和屏幕变更。同步 settle 不能绕过暂停，旧排队/收尾回调不能覆盖新状态。
- SidePanel 的三个预留纵向滚动条的 viewport 跳过纯高度变化，避免昂贵的横向几何检查。
- 快速反向维持同一暂停边界；键盘提前进入、隐藏、切页与关闭均释放边界。
  CloseController 在停止面板计时器之前结束设备栏动画，防止清理后重新启动布局轮询。

验证记录：

- 新增主窗口回归最初 4 failed，协调器回归最初 5 failed，关闭回归最初 1 failed，均先复现后修复。
- 协调器完整直接文件 `test_responsive_layout_controller.py`：54 passed。
- 最终动画、主窗口过渡、正文空间恢复与关闭组合：42 passed。覆盖三页、连续反向、键盘、隐藏、
  中途切换宽度/22 号字/主题及关闭。原有正文空间测试改为等待动画完成，保留全部几何断言。
- 设备选择与相关 viewport、主题字体、导航 resize 组合其余 60 项通过；上述正文空间等待问题
  在最终 42 项组合中修复并验证。总计本轮直接及关联回归 156 项通过，未触发全量测试。
- 同条件带 cProfile 的主窗口再次展开约 207 ms、13 次更新，动画期间响应式规划为零。
  Windows 原生探针开启云母时，12 号字首开、收起、再次展开的更新间隔中位数约 16–17 ms，
  均有 13 个不同正文绘制位置。22 号字独立原生进程首开也保持约 16 ms 中位间隔。
- 测量使用真实 Qt 主窗口、隔离配置和替身设备，不代表实机 ADB 操作或每台机器的帧率保证。
  首次列表创建仍有一次初始化成本，动画结束后的布局收敛也有一次性成本。
  混合场景有一次 22 号字首开帧间隔异常，独立进程和相同顺序重测均未复现，不能确定原因。
  原生复测中列表初次创建约 52 ms，结束收敛约 58–234 ms；这些成本没有计入动画帧率改善。
- 修改生产与测试文件的 Ruff、相关五个生产模块 Pyright（0 errors）、中文注释检查通过；
  项目文档链接/frontmatter 48 项及 `git diff --check` 通过。未触及运行依赖、资源与打包边界，
  不执行构建或 ADB 实机操作。

最后一次交互与关闭组合命令（42 passed）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_responsive_transition.py tests/test_device_selector_animation.py tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
```

## 收起卡顿与跳动的二次修复

用户反馈多个页面收起仍卡顿后，本轮改为记录真实 MainFrame 的 Paint 与正文位置，
不再只以动画回调间隔判断画面。确认以下原因：

- 缓出曲线一开始移动过快；同条件首个可见位移约 39–53 px。
- 收起末尾的终点高度尚未落到父布局，协调器已经恢复规划；最后几像素最长等待约 182 ms。
- 水平布局输入未变化时仍重复规划和应用，迟到的 LayoutRequest 还会额外开启一代。
- 展开文案导致页头按钮宽度变化；收起时禁用整个容器，让列表瞬间切为灰色。

本轮修改仅涉及设备栏、响应式协调器与网格计划缓存：

- 改用缓入缓出曲线；设备摘要不变时保持按钮宽度。收起只退出焦点链、拦截操作，保留行外观。
- 终点先落实设备栏和父布局几何，实际绘制后解除暂停。隐藏、关闭、键盘提前完成仍立即解除；
  快速反向取消上一轮待绘制释放，不让旧回调终止新过渡。
- 过渡前已稳定且水平输入完全一致时，只校验一次并同步高度快照，不重排所有网格。
  终点迟到的布局反馈沿用现有低优先级清理机制；真实宽度、字体、主题和显式请求仍正常处理。
- 每个网格仅缓存最近的正常与保守计划；每次重新测量控件，字体、样式、模式、边距、
  间距或控件尺寸变化均使缓存失效，不积累窗口拖动历史。

验证记录：

- 最终帧回归先复现父布局仍停在旧高度，补同步后通过。迟到布局反馈回归先失败，修复后通过；
  三页集成保留严格的终点一次计算、零次重新应用断言，没有放宽测试。
- 选择区原有 50 项及最终动画 20 项通过；协调器、缓存与三页集成组合 96 项通过；
  关联宽度、字体、主题、正文空间与关闭组合 35 项通过，共 201 项直接和关联测试。
- 最终动画集在 150% 与 200% 缩放下各 20 passed。
- Windows 原生平台、云母开启、12/22 号字体与两种窗口宽度下，两组探针共 8 次展开/收起。
  起步位移约 2–5 px，所有场景没有重新应用网格。此前 182 ms 的收起场景最大绘制间隔
  降至约 22 ms；本次全部场景最大间隔约 29 ms，终点没有再出现百毫秒停顿。
- 首次创建列表仍有约 50 ms 初始化成本；测量使用隔离设置、替身设备和真实 Qt 主窗口，
  不代表用户进程或所有机器的帧率保证。未启动真实 ADB、未执行全量测试或打包。
- Ruff、相关六个生产模块 Pyright、中文注释、文档链接与差异检查通过。

主要验证命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_selector_animation.py tests/test_inline_device_selector.py tests/test_device_operation_selector.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_responsive_transition.py tests/test_responsive_layout_controller.py tests/test_responsive_plan_cache.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_responsive_panels.py::test_remote_control_real_viewport_scan_uses_group_specific_columns tests/test_responsive_panels.py::test_runtime_12_to_22_font_metrics_match_fresh_remote_panel tests/test_responsive_panels.py::test_remote_overflow_row_constraints_clear_when_viewport_grows tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_responsive_panels.py::test_feature_theme_and_font_events_each_create_one_generation tests/test_responsive_panels.py::test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback tests/test_responsive_panels.py::test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once
```

第一条组合在补充待绘制终点中断用例前为 67 passed；新增用例后单独复测动画文件 20 passed，
其余 50 项无需重复。探针在被 Git 忽略的 `.tmp/` 中记录，不作为平台无关的帧率阈值测试。

## 设备列表文字闪跳的后续定位

用户继续反馈，并明确闪跳发生在展开列表和文字。上一轮的正文位置与帧间隔验证没有充分覆盖
列表内部的实际绘制位置；此前的验证结论不能代表这一问题已消失。

真实主窗口的文字 Paint 记录确认：同一设备行的列宽、文字内容和滚动值不变，但收起时其位置
仍会偏移数十像素。原因是先更新裁剪层高度、后由排队事件更新设备栏高度；中间的 QVBoxLayout
会挤压或拉高页头，把整个列表的顶部锚点移走，下一轮再移回。独立选择区与真实主窗口均复现。
另外，快速反向时调整 QVariantAnimation 时长会按旧进度发出中间值，造成同步的高度往返；
仅在处理完事件之后检查最终高度，会遗漏这类错误。

修复限定在 `DeviceContextBar`：每帧同步设备栏与直接父布局，确保高度分配完成后再进入绘制；
重配动画参数时用 `QSignalBlocker` 隔离旧进度。没有固定页头高度、修改背景或改变列宽规则。

验证记录：

- 新增 `test_selector_content_stability.py`，直接观察工具栏和各设备字段的 Paint 坐标，
  并记录反向点击中的同步高度；12/22 号字体下共 10 项先失败，修复后全部通过。
- 最终选择区、主窗口三页、字体中途变更、正文空间恢复及关闭组合共 111 passed。
  150% 与 200% 缩放下，文字位置与既有动画两个文件各 30 passed。
- Windows 原生主窗口覆盖远程控制、应用工具、系统工具，明暗主题、云母开启及 12/22 号字
  共 4 组、16 次展开/收起。实际设备名称 Paint 坐标每个场景均唯一，不再出现上下回跳。
- 另两组原生帧时采样没有重新应用网格；收起与再次展开最大绘制间隔约 17–20 ms。
  首次展开样本最大间隔约 34 ms，仍有初次创建成本，不将这些本机采样视为帧率保证。
- Ruff、相关生产模块 Pyright、中文注释、文档链接和差异检查通过。本轮使用替身设备与隔离设置，
  未操作真实 ADB、未运行全量测试或打包。

本轮关联组合命令（111 passed）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_content_stability.py tests/test_device_selector_animation.py tests/test_inline_device_selector.py tests/test_device_operation_selector.py tests/test_selector_responsive_transition.py tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
```

## 将经验应用到设备概览连接区

用户要求把既有平滑展开方式用于“连接设备”。沿用以下已经验证的约束：内容保持自然尺寸，
只改变透明外壳的裁剪高度；逐帧提交直接父布局；反向动画从当前高度开始，重设参数期间屏蔽
旧进度信号；终点完成绘制后再恢复昂贵的工作区布局。

连接区额外处理业务与滚动边界：

- 主窗口显式启用动画，独立使用 `DeviceConnectionPanel` 仍默认即时显隐。
- 工具栏后保留固定基础间距，面板后的额外间距随动画一起裁剪，消除首次显示的 14 px 跳变。
- 动画期间只同步概览滚动高度，暂停自动跟底；二维码完全展开且实际可见后才确认显示。
- 收起立即清除秘密、使请求失效并取消任务；离页、隐藏与退出不等待视觉动画。
- 收起的最后一帧由父级绘制确认；视口外没有可绘制区域时立即释放过渡，避免永久暂停布局。
- 重开时跳过已删除的历史控件，恢复有效控件的键盘焦点策略；不会为动画把整块表单置灰。

原生窄窗口复核另发现：工具栏改为上下排列时，摘要原有的伸缩权重变为纵向，导致它先吸收
剩余高度，再随连接面板增高逐帧缩小。文字内部位置稳定，但整个面板顶部会移动。回归直接
记录实际 Paint 坐标，并覆盖 860 px 窗口及 22 号字体；工具栏只在横排时分配摘要伸缩空间。

验证记录：

- 连接区动画与原有业务共 43 项通过；新增主窗口集成 7 项及原有连接入口 13 项通过。
- 关联配对布局、真实协调器替身流程、设备概览、选择区暂停/恢复和关闭组合 85 项通过。
  窄窗工具栏修正后，集成与受影响概览节点 25 项再次通过；去重共 148 项。
- 150% 与 200% 缩放下，13 项动画回归分别通过。
- Windows 原生窗口、云母开启，1120 px/12 号字深色与 860 px/22 号字浅色两组共 6 次展开/收起。
  实际文字绘制位置保持唯一，卡片位置单向移动；帧间隔中位数约 16 ms，最大约 33 ms，
  终点收敛约 6–11 ms。这是使用隔离配置及替身设备的本机采样，不作为帧率保证。
- Ruff、三个生产模块 Pyright、中文注释、文档链接/frontmatter 和差异检查通过。
  未操作真实 ADB、未运行全量测试或打包；未修改窗口云母材质与全局字体设置。

主要增量命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_connection_expansion_animation.py tests/test_device_connection.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_connection_expansion_integration.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_global_device_context.py -k 'connection_panel or device_overview_connects'
.\.venv\Scripts\python.exe -m pytest -q tests/test_wireless_pairing_layout.py tests/test_wireless_pairing_flow.py tests/test_selector_responsive_transition.py tests/test_device_hub_page.py::test_connection_toggle_only_shows_focus_border_for_keyboard tests/test_device_hub_page.py::test_device_overview_toolbar_preserves_selected_device_disconnect tests/test_device_hub_page.py::test_device_cards_fit_actual_fonts_and_preserve_keyboard_actions tests/test_device_hub_page.py::test_expanded_details_and_copy_fit_the_scroll_owner_at_large_font tests/test_phase2_mainframe_shutdown_gate.py::test_pairing_tasks_are_registered_before_ui_and_coordinator_shutdown
```

## 连接方式切换与全页面复核

本轮起点为干净工作区 `2863f1a`，范围是扫码、配对码、IP 页签，以及各页面已有的选择区、
展开区和切换布局。不同功能页仍保留各自的自然高度，不新增设备选择入口或强行统一正文高度。

已复现并修复四处问题：

- 连接区共用状态框在扫码和配对码页之间移动后，子布局约束缓存未更新。正常取消后第一次
  切到配对码多出 9 px，错误恢复路径多出 14 px。现在先激活子布局，再统一测量三页自然高度；
  保留取消、秘密清理和动画期间的切换规则，没有用历史最大高度留下额外空白。
- 设置页两张 ADB 卡片在动画中反向点击时，原生入口先跳到完整高度再开始动画。局部派生类
  从当前可见高度续接同一个动画，保留箭头角度；完整开合仍使用原生逻辑。
- 系统工具的 Intent 高级参数显隐后，外层滚动内容高度晚一帧更新，22 号字输入框曾由
  51 px 压到 36 px 再恢复。现在只同步本表单祖先布局与最近滚动区的 LayoutRequest，
  不派发全局事件队列，不固定整页高度，也不新增定时器。
- 远程控制 FPS 下拉外壳仍按隐藏 Pivot 的较高尺寸计算，造成相邻尺寸字段错位 2 px。
  纯下拉外壳现在随当前字体的统一控件高度同步，12→22→12 字号循环保持对齐。

复核与验证边界：

- 新增五个测试文件、29 个回归用例，分别覆盖连接区切换、主窗口实际点击、八个设备入口、
  设置/详情展开和真实主窗口 Intent 的 Paint 坐标；直接验证均通过。
- 主窗口的八个既有设备入口全部检查：文件、远程控制、应用管理、应用与诊断、截图与屏幕、
  系统工具、Logcat、性能采集。选择区字段在动画绘制期间位置稳定，切页中断会释放过渡状态。
  该矩阵用替身替换五个需要外部资源的会话正文，因此另选真实正文控件的布局测试补充验证。
- 连接成功/失败/取消、设置卡片、Intent 表单及设置关闭清理的关联组合 94 passed。
  首页、任务中心、Monkey、远程、设置、文件、应用、Logcat、性能和截图的代表性组合原有
  42 项通过；远程字体切换失败节点修复后单独通过。未把“全页检查”扩展为全部业务测试。
- 远程选择字段文件的过时预期要求尺寸/FPS/码率三列，与既有生产实现及码率独行测试冲突。
  更新为“两字段同排、码率在下方满宽”，保留并加强高度、包含和不重叠断言；该文件与既有
  码率独行节点共 6 passed。
- 150% 与 200% 缩放分别运行连接切换、设置/详情、Intent 和远程字段四个文件，均为
  28 passed。使用隔离设置与替身设备，未连接真实设备、未运行全量 pytest 或打包。
- Windows 原生模式另有连接页实际点击 3 passed，以及八入口矩阵与 Intent 共 5 passed；
  覆盖明暗主题、12/22 号字及云母开关状态。原生连接动画两组采样共六次开合，文字 Paint
  坐标保持唯一，帧间隔中位数约 16 ms、最大约 29 ms；这是本机替身场景，不保证实机帧率，
  也不以控件截图代替 Windows DWM 材质的人工观感验收。
- 四个生产模块的 Ruff、Pyright 和中文注释检查通过。Pyright 通过临时配置显式加入当前
  解释器实际使用的系统 site-packages，未修改项目或系统配置。

主要增量命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_wireless_pairing_layout.py tests/test_wireless_pairing_flow.py tests/test_settings_expand_animation.py tests/test_system_intent.py tests/test_adb_client_refresh.py::test_parent_shutdown_cancels_client_probe_and_rejects_late_restart tests/test_adb_client_refresh.py::test_parent_destruction_cancels_probe_without_child_close_event tests/test_adb_client_refresh.py::test_settings_destroyed_before_deferred_detection_never_starts_probe
# 以下命令分别以 1.5 与 2 执行。
$env:QT_SCALE_FACTOR = '1.5'
.\.venv\Scripts\python.exe -m pytest -q tests/test_connection_page_stability.py tests/test_secondary_page_transition_stability.py tests/test_intent_transition_stability.py tests/test_remote_choice_layout.py
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_all_page_transition_stability.py tests/test_intent_transition_stability.py
```

## 设置滚动与设备详情动画的后续验证

用户继续反馈设置页滚动和展开卡顿、设备详情直接弹出。本轮保留上一轮全部未提交修改；
上一轮设置验证只涵盖布局和开合，不能代表持续滚动性能已经通过。

证据与修改：

- 设置页原本禁用平滑滚动，真实主窗口每个滚轮刻度直接移动 60 px，没有中间帧。
  独立页和主窗采样没有发现滚轮触发重复全页重排。直接恢复库的长缓动会有起步和反向滞后，
  因此由设置页单独持有 120 ms 滚轮过渡，反向从当前值开始，同向待执行距离最多一页；
  位移仍取 Qt 配置步长，触控板、水平、修饰键及子控件滚轮保留原生处理。
- 两张 ADB 展开卡的原生 resizeEvent 在每个高度帧中把正文宽度改为卡片外宽，再由滚动区
  缩回视口宽，重复相差 2 px。十个高度采样曾产生约 100 次正文/行宽变化；本地派生卡保留
  QScrollArea 原生视口更新及表头尺寸同步，让正文只有一个宽度管理者，新增回归确认往返归零。
- 设备详情原本只有 setVisible。现在详情内容按自然尺寸排版，透明外壳裁切高度和顶部间距，
  后续卡片同步移动；纯高度变化不重排字段网格。连续反向、窗口宽度、字体与缓存快照变化
  均复用原控件。实现期间修复字号恢复时头部子布局缓存多留 11 px 的问题。
- 概览聚合多卡活动状态，主窗口再合并连接、详情和设备选择过渡，避免提前释放布局门禁；
  过渡期间不自动跟随滚动底部。CloseController 在 SidePanel 清理前停止详情、复制反馈、
  设置滚动和卡片动画，异步关闭期间的晚输入不能重启动画。

本轮验证记录：

- 新增设置滚动 17 项、宽度效率 4 项、详情动画 11 项和主窗口集成 5 项，共 37 项回归通过。
  开发中先记录无动画、宽度往返、立即跳步及关闭未停止的失败，再验证修复。
- 原设备概览 110 passed；设置宽度修复与原开合/字体关联 35 passed；新滚动及设置直接组合
  29 passed。主窗口详情、连接、选择区、原 Paint 位置和关闭关联组合 32 passed。
  这些组合存在重叠，不相加作为独立用例数。
- 150% 和 200% 缩放各执行设置滚动、宽度效率和详情动画三个文件，均为 32 passed。
- Windows 原生主窗口在深色 1120 px/12 号字、浅色 860 px/22 号字、云母开启请求下，
  滚动、两张 ADB 卡片和详情开合两组采样通过。详情每次有 13–14 个绘制帧，文字坐标唯一，
  帧间隔中位约 16 ms、最大约 19 ms；设置卡片每次约 14 帧，中位约 16 ms、最大约 29 ms。
- 首轮滚动采样混合测试输入停顿和窗口静止重绘，最大间隔约 41–59 ms。额外使用正常 Qt
  事件循环及定时输入，仅记录运动中的绘制，得到 96 帧、中位 15.98 ms、最大 17.23 ms。
  保留两组记录，不将本机替身场景提升为实机帧率保证或 DWM 材质观感验收。
- 六个生产模块及受影响测试的 Ruff、Pyright、中文注释通过；Pyright 使用临时配置补入
  当前解释器实际使用的系统 site-packages。未操作真实 ADB、未运行全量 pytest 或打包。

主窗口关联与高 DPI 命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_details_integration.py tests/test_device_details_animation.py tests/test_connection_expansion_integration.py tests/test_selector_responsive_transition.py tests/test_secondary_page_transition_stability.py::test_device_details_toggle_does_not_move_existing_header_or_summary tests/test_phase2_mainframe_shutdown_gate.py::test_pairing_tasks_are_registered_before_ui_and_coordinator_shutdown
# 以下命令分别以 1.5 与 2 执行。
$env:QT_SCALE_FACTOR = '1.5'
.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_scroll.py tests/test_settings_reflow_efficiency.py tests/test_device_details_animation.py
```

## 设置滚动手感的续调

用户反馈短过渡仍显呆板。本次只调整 `SettingsWheelScroll` 的运动轨迹及其直接测试，
保留此前卡片、详情、主题和字体修改；上节 120 ms 方案由以下行为替代。

- 旧 OutCubic 每刻度重启减速，测试复现输入前后 16 ms 位移从 4 px 突增到 21 px。
  改用临界阻尼，同向保留浮点位置和速度，停手后无回弹地趋近原 Qt 步长目标，反向清除余速。
- 连续输入保留动画时钟，只延长截止时间；修复密集输入反复重启时钟造成的间歇停顿。
  无动画帧间隔的连续输入显式同步段起点，避免从陈旧坐标启动。两项均先复现再修复。
- 滚动直接测试由 17 项增至 27 项，连同宽度效率和展开测试共 **52 passed**。
  修改文件的 Ruff、Pyright、中文注释检查通过；未扩大到全量或打包验证。
- Windows 原生主窗口定时滚轮采样通过，记录 101 次运动期间绘制，中位间隔 16.02 ms。
  最后 2→1→0 px 的减速收尾间隔约 32/47 ms；整数滚动值未变化时不会产生新的移动绘制，
  因此不把这个采样等同于持续帧率，也不把自动测试替代用户鼠标的手感验收。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_scroll.py tests/test_settings_reflow_efficiency.py tests/test_settings_expand_animation.py
.\.venv\Scripts\python.exe -m ruff check gui/widgets/settings_scroll.py tests/test_settings_scroll.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py gui/widgets/settings_scroll.py
```

## 高刷新率适配

本轮先在当前 PySide6 6.8.1.1 / Qt 6.8.1 验证，再接入局部驱动；未修改 Qt 全局时钟、
依赖、屏幕设置、主题或云母代码。

- 当前两块屏幕分别报告约 165 Hz / 100% 和 60 Hz / 150%。原 QVariantAnimation 在两屏
  都约 16 ms 更新一次。精确定时器能够更快唤醒，但唤醒频率不能代表页面实际绘制帧率。
- 排除了 QWidgetWindow.requestUpdate 方案：其 UpdateRequest 会同步重绘顶层 QWidget，
  原型实测更新中位约 24.5 ms，反而更慢；没有将这条路径接入生产代码。
- 新 `FrameAnimation` 使用局部 PreciseTimer 提供采样机会，以实际经过时间计算进度，
  只借用停止态 QVariantAnimation 的插值。正常刷新率取近似毫秒间隔，异常值回退 60 Hz，
  最高按 360 Hz 取整；跨屏和刷新率变化仅调整采样，不重新开始动画。
- 消费者限定为设置滚动、两张 ADB 设置卡的开合与箭头、设备选择区、连接区和设备详情。
  空闲、离页、最小化和关闭停止采样，业务控件负责落实最终几何及释放布局门禁。
  启动中止的动画清理也包含此组件。
- 回归先复现两张设置卡完整收起时先跳到 70 px，再回到展开高度的问题，修复停止态
  配置端点误写真实属性；另外保留 Qt 属性动画的 float 类型转换、箭头隐式起点和首帧提交。
- 开发中销毁压力测试发现 WinIdChange 期间查询窗口对象会触发 Qt 原生异常；改为 Show/
  ParentChange 时解析宿主，运行期间跟随窗口屏幕信号。父对象销毁和显式宿主先销毁均有回归。

验证结果：

- 新驱动直接测试 **26 passed**；设置滚动、开合、宽度效率、详情及新增集成组合
  **74 passed**；主窗口详情、连接、选择区与逐阶段启动中止组合 **31 passed**。
  共 131 个不同测试节点通过。Windows 原生窗口另跑新增集成 **11 passed**，属于重复验证。
- 原生 A/B 使用相同替身主窗口、相同滚轮输入，在 165→60→165 Hz 屏幕间移动。
  常规 pytest 警告采集下，原驱动绘制中位 16.27 / 16.92 / 16.12 ms，局部驱动为
  15.02 / 17.32 / 12.86 ms。最初包含输入前的静止重绘，最大间隔不能作为动画卡顿结论。
- 补充采样只统计动画 Running 期间的 Paint，并关闭测试框架逐条收集第三方弃用警告的
  开销：原驱动中位 16.00 / 15.85 / 16.01 ms；局部驱动 13.68 / 17.06 / 9.43 ms，
  最大 16.08 / 18.67 / 16.14 ms。短样本受绘制开销、缓存及系统负载影响，不承诺跑满
  165 帧，也不等同垂直同步或用户真实鼠标的手感验收。
- Ruff、七个生产模块的 Pyright、中文注释、文档链接/frontmatter 和 diff 检查通过。
  Pyright 仍用临时配置定位当前解释器已有 site-packages。未触及真实 ADB、全量测试或打包。

直接与关联命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_frame_animation.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_high_refresh_integration.py tests/test_settings_scroll.py tests/test_settings_reflow_efficiency.py tests/test_settings_expand_animation.py tests/test_device_details_animation.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_details_integration.py tests/test_connection_expansion_integration.py tests/test_selector_responsive_transition.py tests/test_mainframe_startup.py::test_partial_startup_abort_releases_window_once_without_starting_adb
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe -m pytest -q tests/test_high_refresh_integration.py
```

原生短采样脚本保存在忽略目录 `.tmp/test_high_refresh_audit.py`，不是 CI 门禁；它通过
测试替身构造窗口，分别使用原 Qt 驱动和新局部驱动，不操作正在运行的用户窗口。
人工体验时重启源码程序，在高刷屏连续滚动设置页并反向滚动、连续开合设备列表和详情，
再拖到 60 Hz 屏幕及最小化恢复，确认当前输入设备和桌面负载下的观感。

## 全页面滚动状态与绘制开销

本轮只扩展滚动策略并处理已复现的绘制/测量开销；不改变云母背景、字体配置、设备命令或
页面功能，不将此前工作树中的 UI 修改重新视为本轮范围。

| 消费者 | 滚动策略与边界 |
| --- | --- |
| 首页、设备概览、应用/系统/远程概览、深层功能宿主、任务中心、设置 | 像素滚动复用局部阻尼控制器及高刷采样 |
| 操作设备候选、连接历史 | 同一策略；设备候选内层列表禁用滚条，只有外层负责滚动 |
| 文件表格、应用表格/图标列表、应用详情权限、运行结果和性能会话表格 | 保留原有选择/排序与像素单位，仅替换普通垂直鼠标刻度的缓动 |
| 性能配置与图表、应用详情富文本及批量说明 | 像素滚动；拖动、选区、外部定位、触控板仍交给原控件 |
| Logcat、性能日志、操作结果、文件文本、结果摘要及参数 | `QPlainTextEdit` 使用行单位，关闭旧 Fluent 缓动后原生按行滚动，保持阅读位置和跟随 |
| 图片预览、截图查看器、兼容横向工具条、菜单/下拉框 | 保留缩放、翻页及组件自带输入；不安装通用垂直滚轮控制器 |

已确认并处理的开销：

- 应用管理可见项加载原先在每次滚动检查时扫描整表；改为从视口顶行向下遍历至底边，保持
  排序代理、隐藏行、水平滚动和包名映射。600 行、约 8 个可见项的用例中，相关视图/模型调用
  从约 3600 次降到 128 次以内；这证明工作量随视口而非总行数增长，不是实际帧率结论。
- 性能配置的四类布局容器在仅高度改变时重复测量横向计划；现在宽度变化才重排横向计划，
  字体、内容和显示事件仍走原刷新入口。
- Fluent 图标热绘制反复创建 SVG 解析器，显式颜色还重复读取和改写 XML。为项目配置过的
  按钮、功能卡、设置卡和资源图标复用有界矢量缓存，保留明暗主题、禁用态、颜色、DPI 和
  painter 变换。五次重复绘制的解析从五次降为一次；设置卡热绘制不再增加解析次数。
- 新滚动入口重复调用不叠加控制器；禁用、隐藏、外部定位、滚动范围变化与关闭会取消待执行
  目标。窗口关闭先停止所有滚动控制器，拒绝异步清理期间的晚到滚轮输入。
- 扩大关联测试发现，结果表格重挂外层 `QScrollArea` 后关闭会触发 Qt 原生访问异常。
  隔离证明确由 `FrameAnimation` 强引用祖先窗口改变所有权，子控件清理时释放最后引用会重入
  祖先析构。改为弱引用祖先，不改变时钟或窗口信号策略；所有权回归先失败后通过，原关闭场景恢复。

展开仍使用已接入的设备选择、连接、详情及 ADB 设置卡局部动画；上述绘制缓存与重排优化
同时降低这些过渡的重复开销。Intent、Monkey 参数、结果参数、支持二维码等直接显隐入口
未因此自动改成动画，不能称作“所有展开统一动画”。材质观察器的签名去重也不等于不重绘：
原生 Paint 区域采样显示透明滚动视口仍会重绘对应区域，没有改成不透明底板或整页截图缓存。

验证与剩余边界：

- 应用可见项直接 7 项及关联 44 项、性能重排直接 9 项及关联 20 项通过；图标缓存/资源图标
  36 项及关联按钮 3 项通过。主题往返、显式颜色、禁用/按下、DPI、旋转、后台绘制和缓存上限有覆盖。
- 动画生命周期和完整结果页组合 **43 passed**；关闭编排替身补齐真实主窗的 `findChildren`
  契约后，完整关闭测试文件 **24 passed**。真实窗口另覆盖晚到滚轮、离页和最小化恢复。
- 共享滚轮、普通页面集成、设置滚轮、阅读表面、Logcat、性能会话、图表与文件视图组合在
  首个既有列宽失败前 **169 passed**。全页面选择区绘制/离页、开合最小化及完整文件视图随后
  跑完；只剩文件视图的 22 号字 Light/Dark 两项类型列宽失败。它们在隔离进程撤掉本轮
  文件滚动及按钮图标接入后仍失败（52 px 列宽小于测试测得的 65 px 文本宽），未削弱断言或
  将它们表述为通过，也未扩入本轮滚动优化。最初接入暴露的 ListWidget 绘制 delegate 与
  滚动代理同名问题已单独先复现再修复，应用详情明暗主题关联恢复通过。
- Windows 原生探针使用替身设备构造真实主窗，不操作用户窗口。六个主要页面在 60 Hz /
  150% 与 165 Hz / 100% 上完成滚动；最终 165 Hz 视口 Paint 间隔中位依次为：首页 8.20 ms、
  设备概览 9.45 ms、应用概览 17.39 ms、系统概览 8.93 ms、远程控制 13.48 ms、设置 7.05 ms。
  60 Hz 中位约 16.5–17.3 ms。短内容到边界和整数位移收尾仍有 40–52 ms 的稀疏绘制，
  不把这些间隔直接等同于丢帧，也不把定时器频率或短样本提升为实际持续帧率保证。
- 同一窗口、同一内容、关闭/开启/开启/关闭缓存的四段各 30 次重绘对照，设备概览从
  9.31–9.55 ms 降到 6.46–7.04 ms，远程从 11.95–12.75 ms 降到 8.74–10.60 ms。
  首页、应用、系统、设置的短样本有波动，未据此声称稳定耗时收益。此项使用真实控件向
  QPixmap 重绘以隔离解析开销，与桌面合成/真实滚动帧率是不同指标。
- 修改文件 Ruff、23 个生产模块的 Pyright（动画模块另检）、中文注释、文档链接/frontmatter
  与 diff 检查通过。Pyright 临时配置只补入当前解释器已有 site-packages。未执行全量 pytest、
  打包或真实设备负载验收，未新增依赖或修改屏幕/系统设置。

主要直接与关联命令（组合有重叠，不相加作为独立用例总数）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_visible_scan.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_scroll_reflow_efficiency.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_cached_icons.py tests/test_remote_icons.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_frame_animation.py tests/test_run_results.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase2_mainframe_shutdown_gate.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_page_wheel_scroll.py tests/test_page_scroll_integration.py tests/test_settings_scroll.py tests/test_reading_surface.py tests/test_live_logcat_material.py tests/test_live_logcat_visual.py::test_logcat_new_batch_keeps_history_position_and_resumes_following_at_tail tests/test_live_logcat_visual.py::test_logcat_reading_controls_pause_resume_and_clear_without_stopping_capture tests/test_live_logcat_visual.py::test_logcat_resize_that_removes_scroll_range_keeps_reading_paused tests/test_performance_sessions.py tests/test_perf_chart_material.py tests/test_file_explorer_visual.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_high_refresh_integration.py tests/test_all_page_transition_stability.py tests/test_file_explorer_visual.py tests/test_model_mainframe.py::test_main_frame_shutdown_disconnects_scan_callbacks_without_warning tests/test_phase2_mainframe_shutdown_gate.py::test_pairing_tasks_are_registered_before_ui_and_coordinator_shutdown tests/test_phase2_mainframe_shutdown_gate.py::test_mainframe_two_stage_close_is_nonblocking_broadcast_first_and_idempotent
```

原生采样脚本位于忽略目录 `.tmp/test_scroll_native_profile.py`，需 `QT_QPA_PLATFORM=windows`
并单独加载 `-p tests.conftest`；测量结果分别在 `.tmp/native-scroll-paired-final.txt`、
`.tmp/native-paint-paired.json`，早期两组顺序对照在 `.tmp/native-scroll-profile-final.txt`。
顺序对照存在整段负载漂移，最终不以它推导缓存收益。重启源码程序后，可在实际设备负载下
检查长应用/文件列表连续滚动、快速反向、滚条拖动、滚动中展开、跨屏和关闭，补充真实手感验收。
