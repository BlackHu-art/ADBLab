# 页面切换稳定性实施与验收

## 后续：增强正文出现过渡（用户已批准）

原先 0.78 起点与 140ms OutCubic 的淡入过弱；连续切页继承旧透明度后趋近直接显示。
正文调整 PageTransition：每个新路由从 0.15 以 320ms OutQuad 淡入（用户体验 200ms 后要求延长），首帧绘制期间保持
起始透明度，在绘制返回事件循环后才推进时钟。复用 FrameAnimation 的暂停态等待首帧，
取消、替换、隐藏、缩放、主题变化和销毁同时撤销待启动回调。业务激活仍同步完成。

执行顺序：先补首帧慢绘制与快速替换回归；再实现局部计时调整；串行验证页面过渡、
导航/历史/会话与动画生命周期，最后由新上下文 Agent 独立审阅。保留以下原阶段验收记录，
新结果追加到文末；临时日志继续存储在系统临时目录，不增加仓库探针或截图。

用户追加：性能页 Monkey 的展开采用与操作设备相同的完整布局裁剪思路，并检查其他遗漏。
在既有 collapsible_tools 中复用 FrameAnimation，统一可选正文的 240ms InOutSine 开合，覆盖
Intent 高级参数、Monkey 设备明细、远控诊断、结果详情、截图信息、关于二维码和通用折叠区；保留原
控件/信号/业务启用状态。宽度、字体和内容变化重算完整高度；每帧同步祖先与滚动边界，
隐藏、关闭、最小化落实目标；键盘进入时提前展开，收起时先回收焦点。

浅色云母仅调查：当前主内容材质叠加 50% 白色（深色为 3.14%），本轮不改配色或 DWM。

**目标：** 按用户已批准的推荐方案，统一跨宿主和宿主内导航，消除大幅滑入和布局中间态，保留云母及业务／数据兼容。

**设计：** 主窗口拥有一个仅用于视觉的页面过渡器。同步切换批次包住路由激活、顶部栏和最终布局；
嵌套调用合并为一次提交，不泵事件、不异步延迟业务激活。关闭 Fluent 的 76px 位移动画，页面保持最终几何。
内容栈使用约 140ms 的轻淡入（非零起始透明度），共用背景和顶部栏不安装特效、不截图。
快速重入取消前次视觉过渡，立即呈现最后路由；重复当前路由不重播。动画结束不承担业务收尾。
隐藏、缩放、主题变化、关闭及异常恢复最终显示，沿用 FrameAnimation 的窗口生命周期与刷新时钟。

**范围：** 新增 `gui/widgets/page_transition.py`；修改 `gui/main_frame.py` 的组合和两个切页入口。
测试等待点从第三方私有位移动画迁到项目内容动画，保留原像素、布局、会话与导航断言；
新建专门的过渡回归。只同步 UI_IMPLEMENTATION 当前事实，不改变依赖、数据格式、版本或设备执行。

**执行：** 主 Agent 串行实施，完成后新上下文 Agent 独立审阅。保持当前 `ui-design`；
原有截图和设计稿不动。本次新增工作不自动提交或推送。

## 步骤

- [x] 在隔离数据／外部命令边界内取得直接基线；补跨宿主几何和同宿主统一过渡红测。
- [x] 实现同步提交和轻淡入，覆盖快速替换、重复路由、异常、隐藏／关闭与重绘恢复。
- [x] 迁移动画等待测试，验证主题、云母、设备栏、历史、路由 payload 和会话复用。
- [x] 运行相关 Qt／静态／文档检查，独立审阅并修正发现，记录真实平台未验证边界。

## 验收重点

页面在过渡各采样点的位置、大小和滚动范围稳定；空白背景像素不随动画改变；
同宿主和跨宿主都由同一时钟驱动；快速点击最终路由、选中项、标题和业务会话一致；
计时器停止后不残留半透明内容。授权设备及 DWM 实际视觉效果需人工复验，不以 offscreen 代替。

## 结果

基线：`ui-design`，`d1d381f6562c9b5828a028ae7909810a6e608c42`。原有两个 `demo_*.png`
和 `docs/design/` 未改动。主 Agent 实施，独立 Agent `page_transition_review` 只读复核；
未切换分支、提交、推送、改版本或数据格式。

红测复现：同步布局先把页面放在原点，旧 Fluent 动画在 40ms 后又把页面移动到 `(0, 42)`；
关闭该位移动画后改为最终几何上的轻淡入。另补回归并修复内容销毁后父容器未恢复绘制，
以及主题改变后等到排队的材质刷新才取消淡入这两个实现期问题。

验证在专用临时目录运行，使用仓库解释器、offscreen、临时用户／配置／缓存路径、串行锁，
禁止网络和非 Python 外部进程；没有运行真实 ADB、安装器、正式构建或真实用户数据。
完整命令、退出码和日志保存在本轮临时目录的 `validation.json` 与 `static-validation.json`：
`C:/Users/57289/AppData/Local/Temp/adblab-page-transition-20261029-wu4yhq0c`。

| 验证组 | 实际范围 | 结果 |
| --- | --- | --- |
| `transition-final-green` | `tests/test_page_transition.py` | 19 passed，退出码 0 |
| `transition-mainframe` | `test_main_window_layout.py` 的历史、选中反馈、设备恢复、菜单收起、主题与首帧布局节点 | 19 passed / 92 deselected，退出码 0 |
| `transition-navigation` | 新过渡测试的最初 13 项 + `test_navigation_rendering.py` + `test_workspace_feature_host.py` | 109 passed / 3 failed / 2 skipped / 1 teardown error，退出码 1 |
| `transition-baseline` | 从同一 HEAD 导出的原始版本，复跑上述四个失败节点 | 相同 3 failed / 1 passed / 1 teardown error，退出码 1 |
| `transition-consumers` | 设备选择、连接／详情展开、响应式、滚动、局部时钟，以及文件／日志／首页／设备栏关联节点 | 133 passed / 1 failed，退出码 1 |
| `transition-connection-baseline` | 原始版本的大字号连接区同一失败节点 | 同样失败，退出码 1 |
| `transition-dpi150` | `QT_SCALE_FACTOR=1.5`，四组路由几何与背景稳定测试 | 4 passed，退出码 0 |
| `transition-ui-collection` | 新测试文件 `--collect-only -m ui` | 19 项全部标记 UI，退出码 0 |
| Ruff | 全部修改 Python 与新增组件、测试 | 通过 |
| 中文注释与源码文本 | 两个生产文件；第一方文本完整性 | 通过；文本检查 916 文件 |
| Pyright | `gui/main_frame.py`、`gui/widgets/page_transition.py`，临时配置定位实际已安装依赖 | 仍有 MainFrame 两个基线错误；原始版本同样复现，无新增错误 |
| 文档与 diff | `check_doc_links.py`、`git diff --check` | 通过 |

以上是各次运行计数，包含重复覆盖，不相加为独立用例总数。阶段验证与独立审阅完成，
没有将基线失败、离屏跳过或未执行的实机验证记为通过。

基线保留项（未放宽或跳过断言）：

- `test_shared_content_keeps_round_corner_when_material_changes[Light/Dark]`：内容圆角边缘颜色与参考图不符。
- `test_route_animation_and_device_bar_visibility_keep_same_theme_surface[True-Light]`：`appManagerPage`
  事件循环后像素颜色／alpha 与参考材质不同；本次新增时序测试验证的是同一路由过渡前后背景稳定。
- `test_dispose_failure_does_not_skip_later_sessions`：故障注入的 `request_dispose` 在 teardown 仍抛出
  `ValueError`，清理夹具报告错误。该节点正文通过，但不能把它记作完整通过。
- `test_connection_text_stays_fixed_in_actual_paints_while_cards_slide[22-860]`：连接区展开时工具栏
  宽度不同于展开前采样；当前组合为 727→748，原始版本独立复跑为 734→748。
  未修改连接区的展开逻辑，保留此既有大字号布局问题供后续处理。
- 两个原生 DWM 属性测试按已有平台条件跳过。Pyright 原始版本 `main_frame.py:40/637`
  分别为 `shiboken6.isValid` 类型导入和可空对象 `installEventFilter`，当前只因新增 import 顺移行号。

独立复核已读取根规范、architecture / ui-i18n / verify skills、UI 与测试文档以及真实调用方。
初审和主题取消补丁复审均未发现证据充分的新增缺陷；业务路由、历史、一次性 payload、会话激活
仍同步执行。四组 Light/Dark × 云母的实际 `grab()` 探针各覆盖九条导航：可见子控件 enabled
effect 清单均空，未捕获 QPainter／paintEngine 错误；证据仅适用于构造的测试页面状态。

人工复验：在 Windows 原生窗口分别开关云母、使用浅深主题，在 100%／150% 缩放下快速切换
文件、应用、实时日志、性能、截图与设置；切页中收起菜单、改变尺寸／主题并返回历史。
检查背景是否闪白、内容是否位移、页头与滚动条是否稳定，最后在模拟或授权设备负载下确认阅读位置
和操作目标保持。未测实际 DWM、多屏跨屏、真实设备高负载或帧耗时，不声称实测帧率提升。
本轮边界可由直接与关联集覆盖，未触发全量 pytest，也未触及正式打包边界。

## 实际测试命令

以下命令使用上述临时目录的串行隔离 runner；每条的测试参数及退出码来自实际执行记录。
`run_baseline.py` 只将根目录指向 `git archive` 导出的基线，没有回退当前工作区。

```powershell
$scratch = "C:/Users/57289/AppData/Local/Temp/adblab-page-transition-20261029-wu4yhq0c"

# transition-navigation：退出码 1
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-navigation tests/test_page_transition.py tests/test_navigation_rendering.py tests/test_workspace_feature_host.py

# transition-baseline：退出码 1
.\.venv\Scripts\python.exe -B "$scratch/run_baseline.py" transition-baseline tests/test_navigation_rendering.py::test_shared_content_keeps_round_corner_when_material_changes 'tests/test_navigation_rendering.py::test_route_animation_and_device_bar_visibility_keep_same_theme_surface[True-Light]' tests/test_workspace_feature_host.py::test_dispose_failure_does_not_skip_later_sessions

# transition-final-green：退出码 0
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-final-green tests/test_page_transition.py --junitxml=C:/Users/57289/AppData/Local/Temp/adblab-page-transition-20261029-wu4yhq0c/direct-final.xml -o junit_family=legacy

# transition-mainframe：退出码 0
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-mainframe tests/test_main_window_layout.py -k 'navigation_history or navigation_and_workspace_selection_feedback or programmatic_workspace_route or workspace_page_switches_pause or no_device_feature_resumes or first_visible_frame or navigation_route_click_collapses or navigation_back_closes or theme_switch_keeps_mica or dark_theme_updates_hidden_workspace or system_color_scheme_change' -vv

# transition-consumers：退出码 1
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-consumers tests/test_all_page_transition_stability.py tests/test_connection_expansion_integration.py tests/test_device_details_integration.py tests/test_intent_transition_stability.py tests/test_selector_responsive_transition.py tests/test_page_scroll_integration.py tests/test_high_refresh_integration.py tests/test_frame_animation.py tests/test_page_scroll_edges.py tests/test_dropdown_material.py::test_settings_dropdown_inherits_shell_material_without_selection_changes tests/test_file_explorer_visual.py::test_file_explorer_main_window_toolbar_does_not_force_horizontal_scroll tests/test_live_logcat_visual.py::test_logcat_return_from_performance_keeps_output_inside_view_and_reading_state tests/test_home_banner.py::test_main_window_home_retains_all_shortcuts_after_hidden_resize_and_theme_change tests/test_global_device_context.py::test_workspace_selection_keeps_visible_page_and_bar_geometry tests/test_global_device_context.py::test_page_scrollbars_stay_close_to_content tests/test_global_device_context.py::test_page_scrollbar_uses_full_viewport_and_accepts_drag -vv

# transition-ui-collection：退出码 0
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-ui-collection tests/test_page_transition.py --collect-only -m ui

# transition-connection-baseline：退出码 1
.\.venv\Scripts\python.exe -B "$scratch/run_baseline.py" transition-connection-baseline 'tests/test_connection_expansion_integration.py::test_connection_text_stays_fixed_in_actual_paints_while_cards_slide[22-860]' -vv

# transition-dpi150：退出码 0
$savedScale = $env:QT_SCALE_FACTOR; $env:QT_SCALE_FACTOR = '1.5'
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" transition-dpi150 tests/test_page_transition.py::test_routes_keep_final_geometry_through_shared_content_transition
$env:QT_SCALE_FACTOR = $savedScale
```

## 2026-10-30 正文淡入与展开补齐

本次基线为 `ui-design` 的 `354568d7e43b9a3f6a8db045f2ff7fb93bbca39b`，原有未跟踪
`docs/design/` 保持不变。正文淡入延长为 320ms；可选正文采用 240ms 的完整布局裁剪。
未改变业务目标、输入值、数据格式、版本、依赖或实际云母配色，也未提交或推送。

遗漏检查覆盖性能 Monkey、应用 Monkey 设备明细、Intent 高级参数、结果详情、远控原因、
截图信息、关于二维码和通用折叠区（含会话表与结果区）。设备选择、连接、设备详情与 ADB
设置卡已有专门动画，保留原实现；原生菜单、独立工具窗口及业务空态不按可选正文处理。

回归与独立审阅中实际发现并修复：首帧耗时吃掉淡入时长、快速导航沿用接近不透明的起点、
会话表增减行后裁剪高未刷新、包装层改变横向策略压缩大字号摘要、二维码收起残留间距、
截图信息收起首帧横向闪缩，以及截图页直接停用后动画仍在运行。对应失败日志保留，未删测试
或放宽断言；终态布局断言增加对动画结束的等待。导航像素夹具停止构造期背景时钟，再设置
固定模拟 DWM 颜色，避免采样期间旧时钟覆盖探针颜色；生产背景实现未改。

独立 Agent `content_fade_review` 复核淡入；`reveal_final_review` 复核展开、动态内容及清理。
主 Agent 串行实施和执行 Qt；复核发现的动态高度、截图宽度及停用边界均修正后再审。

本轮证据位于 `C:/Users/57289/AppData/Local/Temp/adblab-content-fade-tlvp4xra`，
`validation.json` 保存每次真实命令、退出码和日志位置。使用项目解释器、临时用户/缓存/数据目录、
offscreen 与串行锁，禁止网络及非 Python 外部进程；未运行真实 ADB、安装器或正式构建。

| 验证组 | 实际范围与结果 | 退出码 |
| --- | --- | --- |
| `fade-acceptance` | `test_page_transition.py` 全部节点，以及导航主题背景/快速替换两组：41 passed | 0 |
| `reveal-acceptance` | Monkey、性能、Intent、截图整文件；关于、远控、共享控件代表节点；会话表、结果列表及结果呈现整文件：148 passed / 1 failed | 1 |
| `reveal-terminal-fixed` | 收起终态、键盘焦点、窗口隐藏/关闭/最小化、截图停用/释放：12 passed | 0 |
| `content-dpi150` | 150% 缩放下路由、性能 Monkey、应用明细、二维码、远控与截图：20 passed | 0 |
| `head-existing-failures` | 用 `git show HEAD:<path>` 导出的原始模块替换导入，不切换工作区；Monkey 大字号 2 项通过，圆角 2 项和会话释放 1 项仍失败 | 1 |

表中计数为各次运行，包含重复覆盖，不相加为独立用例总数。最终展开集唯一失败为
`test_session_disposal_and_feature_navigation_release_or_hide_list`：替身 runner 下
`request_dispose()` 返回 False；原始模块同样失败。较早关联集还复现原有的浅/深主题圆角像素
两项和应用管理小窗口滚动范围一项；没有把这些既有失败记为通过。原始模块替换只用于确认
本次修改归因，不代表发布版本完整验收。

修改文件 Ruff、中文注释检查、文档链接/frontmatter 与 `git diff --check` 通过。Pyright 对全部
修改生产模块仍有 4 个 `shiboken6.isValid/delete` 类型导入错误；对导出的 HEAD 文件使用相同
依赖路径复现同样四项，无新增错误，不能记为 Pyright 通过。初次临时源码类型检查未配置对应
执行环境，曾报告 41 项缺失导入；纠正临时配置后以上述四项为有效比较结果，未改项目配置。

最终命令示例（其余完整参数见 `validation.json`）：

```powershell
$scratch = 'C:/Users/57289/AppData/Local/Temp/adblab-content-fade-tlvp4xra'
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" fade-acceptance tests/test_page_transition.py tests/test_navigation_rendering.py::test_route_animation_and_device_bar_visibility_keep_same_theme_surface tests/test_navigation_rendering.py::test_rapid_route_replacement_keeps_animated_gap_in_current_theme
$changed = @(git diff --name-only -- '*.py')
.\.venv\Scripts\python.exe -B -m ruff check @changed
.\.venv\Scripts\python.exe -B scripts/check_doc_links.py
git diff --check
```

浅色云母诊断：`MainFrame._sync_material_surface_styles()` 在系统云母上叠加 50% 白色，
深色对应 3.14%；当前安装的 FluentWindow 在云母开启时根背景透明，因此存在明确的额外提亮。
可在后续经确认的视觉调整中先试 25%–30% 白色叠层，并检查文本/卡片对比度；本轮没有改色，
也没有用 offscreen 结果冒充原生 DWM 观感验证。

人工验收：原生 Windows 下以浅/深主题和 100%/150% 缩放快速切页，检查正文约 320ms 的出现
过程；反复开合 Monkey、明细、截图信息和二维码，检查输入保留、反向续接、收起间距与焦点。
未测真实设备高负载、多屏切换或实测帧率；本次影响可由关联集界定，未触发全量 pytest。

## 2026-10-30 云母配色与首页遮挡修正

按后续授权继续调整云母配色。基线仍为 `ui-design` / `354568d7e43b9a3f6a8db045f2ff7fb93bbca39b`，
保留前述未提交的淡入、展开和文档改动以及 `docs/design/`。范围仅为主窗口内容面、首页卡片与
横幅及对应测试，不修改系统材质申请、资源原图、业务、数据格式、依赖或版本。

代码与截图确认两层遮挡：内容面在系统云母上重复叠加 50% 白色；首页还有不透明渐变、完整
装饰图片，以及浅色正常态 170/255 白色卡片。调整后内容面和首页浅色正常卡片使用 64/255
白色；深色卡片及内容面沿用原透明度。首页横幅只在实际云母开启时跳过渐变并以 18% 绘制图案，
非云母保持原行为。卡片沿用原生鼠标、键盘和绘制，仅通过现有 MaterialObserver 同步宿主状态。

先验证失败：内容面新像素断言 1 failed，首页横幅/卡片断言 3 failed / 1 passed；修复后转绿。
既有圆角测试的非云母参照曾错误地把模拟 DWM 底色参与原生半透明合成，现以实际实色回退作
参照；云母参照改为明确的设计透明度，仍逐像素检查原生边框和项目遮罩，不放宽阈值。

独立 Agent `mica_palette_review` 分两次只读复核内容面及首页实现，未发现阻断问题；其建议的
云母持续开启时 Light/Dark 热切换已补入卡片用例并通过。未并行执行 Qt。

证据目录：`C:/Users/57289/AppData/Local/Temp/adblab-mica-palette-4hbhffxe`。
`validation.json` 保存完整命令、退出码和日志路径。各组使用串行锁和临时用户/缓存/数据目录，
禁用网络及非 Python 外部进程；原生组仅切换 Qt 平台到 Windows，不连接设备。

| 验证组 | 实际结果与范围 | 退出码 |
| --- | --- | --- |
| `mica-direct` | 7 passed：多底色文字对比、原生非云母、开关往返、不支持回退 | 0 |
| `mica-corners` | 6 passed：首页空白与材质圆角 | 0 |
| `mica-related` | 29 passed：12 个路由、快速切换、设备栏、菜单及设置下拉 | 0 |
| `home-mica-related` | 38 passed：首页整文件、只读正文、无障碍与首页空白/圆角 | 0 |
| `mica-dpi150` | 6 passed：150% 缩放下横幅、卡片交互/主题热切换与圆角 | 0 |
| `mica-native` | 2 passed：Windows 深浅主题下 DWM 明暗及背景属性开关往返 | 0 |
| `mica-preview` | 2 passed：真实首页控件的离屏截图，固定模拟底色，仅用于检查层次与文字 | 0 |

各组存在重复覆盖，不相加为独立用例总数。原生组确认 DWM 属性，不等于验证了不同真实壁纸、
激活状态和多屏下的最终观感；预览图也不代表 DWM 截图。实际窗口仍需观察系统壁纸色调、
浅深主题、云母开关和卡片反馈。没有触发全量测试、正式打包、实机 ADB 或发布。

Pyright 当前 4 个生产文件仍报告 MainFrame 的两项既有问题：`shiboken6.isValid` 类型导入、
可空 QApplication 的 `installEventFilter`。本轮修改前源码在隔离完整 GUI 包中复现同两项，
没有新增类型错误，不记为通过；最初只复制目标文件的参照产生额外缺失导入，已纠正隔离包布局。

主要命令（完整参数见上述日志）：

```powershell
$scratch = 'C:/Users/57289/AppData/Local/Temp/adblab-mica-palette-4hbhffxe'
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" home-mica-related tests/test_home_banner.py tests/test_workspace_reading_material.py tests/test_accessibility_contract.py::test_home_action_card_has_accessible_name_and_keyboard_focus tests/test_navigation_rendering.py::test_home_scroll_blank_uses_the_shared_material tests/test_navigation_rendering.py::test_home_corner_mask_is_stable_across_mica_changes_and_navigation
.\.venv\Scripts\python.exe -B "$scratch/run_native_tests.py" mica-native tests/test_navigation_rendering.py::test_native_palette_event_preserves_mica_theme
```

## 2026-10-30 主题混色、首页原图与全页面卡片同步

用户实测指出主题切换过曝、首页图片冲淡和设置卡片未同步；本轮覆盖前一节的 18% 图片
绘制方案。工作区仍为 `ui-design`，基线提交 `354568d7e43b9a3f6a8db045f2ff7fb93bbca39b`。
保留此前已授权的动画改动以及原有未跟踪远控设计草稿。本轮不改业务、数据格式、版本或依赖。

确认的根因与处理：

- `_current_theme` 原先在 qfw 完成全量 QSS 后才更新，期间原生 `ApplicationPaletteChange`
  能把新云母明暗写回旧值。两方向原生重入用例均先失败；现提前提交目标主题，并在完整样式、
  色板及项目回调期间暂缓 Qt 绘制，正常/异常/窗口销毁均安全恢复。保留原有系统消息补刷新，
  不宣称消除全量样式重建耗时。
- 横幅去掉额外 18% 透明度，原图和资源哈希不变。恢复后另确认图片极端明暗会压低文字对比，
  因此只给横幅上的快捷卡使用 `IMAGE_CARD_*`，验证正常/悬停/按压态对比度至少 4.5:1。
  独立复核另发现同窗重挂不改变材质观察器的宿主缓存，导致图片底色残留；卡片在重挂/首次显示
  时强制刷新既有观察器，涵盖整个分组移动。六张横幅卡与横幅外输出目录卡分别验证。
- 普通卡片共用 `MaterialCard`；设置卡因上游硬编码底色，由卡片拥有的局部 Paint 过滤器
  仅在实际云母下替换底板。普通设置 15 卡、关于 3 卡、ADB 2 张展开卡、四类无设备页、
  文件预览和应用/文件/日志/截图独立页头均覆盖。展开标题保留圆角与原边框，正文单层填充。
  透明 ContentSection、输入框和业务视图专用材质保留。

独立 Agent `theme_surface_review` 核实根因、全页面消费清单与修复增量；主 Agent 串行实施和
运行 Qt。重挂问题修正及测试范围更正后，最终独立静态复核无阻断项。
测试、类型参照、真实命令及失败日志保存于 `%TEMP%/adblab-theme-sync-rrjqwwt7`，
`validation.json` 保存退出码和完整参数，`before/` 保存本轮开始时源码，未回退用户工作区。

| 验证组 | 范围与实际结果 | 退出码 |
| --- | --- | --- |
| `theme-red` → `theme-green` | 样式重建/异常恢复及 Windows 原生重入：5 failed → 5 passed；初次另有测试补丁清理顺序错误，已修正 | 1 → 0 |
| `surfaces-red-isolated` → `surfaces-green` | 设置/关于/空态底板从 5 failed / 1 passed 修至通过；加首页图像/交互合计 10 passed | 1 → 0 |
| `theme-material-related` | 设置字体/展开、首页、主题入口、材质正文、全部 12 导航入口及隐藏页：168 passed | 0 |
| `artwork-final` | 首页整文件、图案对比和跨宿主材质：32 passed | 0 |
| `artwork-reparent-red` → `artwork-reparent-verified` | 六项同窗重挂/首显回归先失败；修复后首页整文件与普通卡交互组合 38 passed | 1 → 0 |
| `theme-dpi150-review-final` | 150% 缩放：设置/空态卡片、原图、对比度、重挂、首次显示及主题异常恢复，22 passed | 0 |

运行计数含重复覆盖，不累计为独立用例总数。修复展开正文 QSS 后验证两主题通过；最初未注册
子 view 的 custom QSS 不生效，改在已有注册的展开卡上限定 `QFrame#view`。离屏重挂测试在
150% 缩放下存在自动 Enter 干扰，改为明确测试隐藏宿主重挂及平台 Leave 事件，保留原断言。
最终组合也确认前例鼠标停留在同坐标会省略 Enter，测试先经卡片外再进入；真实 QTest 和颜色
断言保留。首显新增测试最初错误地把横幅外输出目录卡列为图片卡，现独立断言它仍用普通底色。

隔离说明：首次新增卡片测试遗漏设置预热替身，触发本机 ADB 客户端 version 探测，并在强制
测试销毁中留下 worker 回调错误；随后显式使用项目已有 `isolated_settings_client_detection`
隔离并重跑。未执行设备业务命令。其他测试使用临时用户/数据/缓存、串行锁和外部调用防护。

原生验证边界：DWM 属性和调色板重入断言通过，但窗口 DC 截图不含 DWM 背景；后续桌面区域
采样未可靠取得目标窗口，不能作为视觉通过证据，相关临时图片已清理。采样运行的 pytest
退出码为 0 仅说明原生属性断言通过。全量 QSS 重建在双测试窗口探针中仍约 1.7–2.1 秒，含
采样开销，不能据此声称实际应用切换提速。真实壁纸、多屏、前后台切换的观感仍需人工观察。

Pyright 修改范围仍有 MainFrame 的两项既有错误（`isValid` 导出类型、可空 QApplication），
本轮开始快照在同依赖配置中复现相同两项，无新增错误，不记为通过。默认命令不能识别本机
共享 site-packages，最终用临时 `pyright-current.json` 显式指定实际依赖路径，与参照配置一致，
未更改仓库配置或安装依赖。未触发全量 pytest、
正式打包、安装器或发布。本轮 Git 交付按用户后续授权执行，设计草稿不夹带上传。

主要命令（完整列表见临时目录 `validation.json`）：

```powershell
$scratch = "$env:TEMP/adblab-theme-sync-rrjqwwt7"
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" theme-material-related tests/test_card_material.py tests/test_navigation_theme.py tests/test_home_banner.py tests/test_settings_typography.py tests/test_settings_expand_animation.py tests/test_workspace_reading_material.py tests/test_navigation_rendering.py::test_all_navigation_pages_share_material_without_covering_reading_controls tests/test_main_window_layout.py::test_dark_theme_updates_hidden_workspace_surfaces_before_navigation tests/test_main_window_layout.py::test_theme_switch_updates_mica_fluent_window_shell
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" artwork-reparent-verified tests/test_home_banner.py tests/test_card_material.py::test_material_card_keeps_hover_on_theme_change_and_native_reparent
$previousScale = $env:QT_SCALE_FACTOR; $env:QT_SCALE_FACTOR = '1.5'
.\.venv\Scripts\python.exe -B "$scratch/run_tests.py" theme-dpi150-review-final tests/test_card_material.py tests/test_home_banner.py::test_home_banner_preserves_original_pixels_in_both_material_modes tests/test_home_banner.py::test_banner_card_text_remains_readable_over_original_artwork tests/test_home_banner.py::test_action_card_refreshes_artwork_surface_when_reparented_in_same_window tests/test_home_banner.py::test_home_initial_show_refreshes_cards_wrapped_into_banner tests/test_navigation_theme.py::test_theme_rebuild_uses_target_tokens_without_painting_partial_state tests/test_navigation_theme.py::test_theme_rebuild_failure_restores_window_updates
$env:QT_SCALE_FACTOR = $previousScale
```
