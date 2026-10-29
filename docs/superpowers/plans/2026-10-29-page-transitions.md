# 页面切换稳定性实施与验收

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
