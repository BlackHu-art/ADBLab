# 页面主滚动条贴右边界实施计划

后续底部留白与截图页调整见 [工作区布局完善](2026-10-24-workspace-media-polish.md)；本页保留
前几轮视觉反馈和验收经过，最新嵌入上下外距已统一为 8px。

**目标：** 检查全部页面，将主滚动条与现有设置、概览、Logcat 的右边界统一。
**方案：** 主窗口宿主已有零外边距；把应用管理和文件管理主列表外侧留白移到非滚动控件中。
最新目标：两页主列表内容和表头左右与正文 32px 阅读边界对齐，右侧滚动条继续贴边；
底部操作栏/状态行外距为 0px，工具行保留原有横向阅读位置；移除文件列表重复内容提示。
分栏打开后的列表、预览、权限和画布仍使用各自区域，不改变业务或交互协议。
**环境：** Python 3.11、PySide6、现有 Qt 离屏测试；沿用当前未提交重构状态，不提交或推送。

## 边界与步骤

- [x] 核对首页、设置、任务、设备/应用/系统概览、Remote、Logcat、Performance、截图及两类列表页。
  主窗口和宿主已贴边；应用管理为 24+8px 右外距，文件管理为 32px。
- [x] 应用管理：修改 `gui/features/app_manager/form.py`，保留筛选、命令和状态内容的阅读留白；
  保留图文/表格视图、列宽及详情分栏策略。新增直接几何/状态回归，先红后绿。
  `page.py` 仅补偿从外层移到详情内部的 24px 留白，保持原分栏断点。
- [x] 文件管理：修改 `gui/features/file_explorer/page.py`，保留路径、命令和状态内容留白；
  可恢复独立模式，预览断点与宽窄布局保持。新增直接回归，先红后绿。
- [x] 强化 `tests/test_page_scroll_edges.py`，增加主窗口各功能主滚动矩阵，量实际可见轨道到主窗口的距离，
  覆盖正常/紧凑尺寸、长内容和空态；保留 Fluent 自身 1px 轨道 inset，不修改第三方样式或缩放热区。
- [x] 直接与关联验证、原生退出、离屏图像、静态检查及独立审阅通过，更新 UI 实现文档。
- [x] 按截图追加调整文件管理主表左侧：移走列表外侧 32px，路径/命令/状态行保留双侧留白，
  独立模式及预览阅读边界保持；补主窗口左右边界验证和独立复查。
- [x] 应用管理两种视图按同样规则左侧贴边，筛选/错误/命令行、详情阅读边界和分栏阈值保持；
  补主窗口两种视图的双侧边界及独立复查。

## 验证选择

应用/文件：新增滚条几何测试、既有 visual、column fill、状态/预览/键盘路径。
主窗口：page_scroll_edges、page_scroll_integration、scrollbar_resize_hit，按实际触及范围选关联节点。
不重复前一轮目录迁移的验收，不默认全量 pytest；离屏结果不替代多屏高 DPI 和真实桌面观感。

本轮快照、路由审计、测试命令/结果和审阅证据保存在
`.superpowers/sdd/2026-10-24-right-edge-scrollbars/`；现有未提交文件先保存快照，审阅仅比较本轮增量。

## 执行与验收记录

测试通过本轮 `run_checks.py <label> <pytest 参数>` 隔离设置、历史和临时目录，记录各测试阶段及
进程退出；使用项目 `.venv/Scripts/python.exe -B` 执行。以下四组共 261 次通过、232 个不同节点，
均无失败或跳过，pytest 与原生进程退出码均为 0。

| label | pytest 参数 | 通过 |
| --- | --- | --- |
| `app-related` | `tests/test_app_manager_scroll_edge.py tests/test_app_manager_visual.py tests/test_app_manager_column_fill.py tests/test_app_manager_status_layout.py` | 81 |
| `file-related` | `tests/test_file_explorer_visual.py tests/test_file_explorer_preview.py tests/test_file_explorer_focus.py` | 82 |
| `file-preview-inset-green` | `tests/test_file_explorer_scroll_edge.py tests/test_file_explorer_preview.py` | 41 |
| `window-final` | `tests/test_page_scroll_edges.py tests/test_page_scroll_integration.py tests/test_scrollbar_resize_hit.py tests/test_file_app_device_admission.py::test_app_manager_large_font_selection_keeps_rows_at_fit_boundary` | 57 |

- 两类主列表的新测试先复现原 32px 内缩，再验证修复；主窗口矩阵检查真实可见 Fluent 轨道，
  覆盖两种窗口尺寸、长内容及无设备/关闭状态。共享准入测试只补齐内部留白的宽度预算，保留原断言。
- 独立审阅发现预览正文和关闭按钮右距随外边距缩短，已将 32px 留白补到预览内部；新增三个宽度下
  活动预览反复嵌入/退出测试，保持正文右距与关闭后主列表贴边。复查探针 5 项通过，双退出码为 0。
- 检查并查看应用图文/表格、文件列表及参考设置页面的离屏截图；真实 Windows 材质与多屏 DPI
  体验尚未人工验证。截图存于本轮证据目录的 `screenshots/`。
- 修改文件 Ruff、三个生产文件 Pyright、中文注释、92 份文档链接/frontmatter、844 个源文本以及
  `git diff --check` 均通过。Pyright 临时配置继承仓库规则，仅补当前解释器实际 site-packages 路径。
- 本轮没有改业务、用户数据、依赖或打包边界，未运行全量 pytest、打包或真实设备验收；未提交或推送。

## 截图反馈后的左边界调整

用户认可右侧效果后，依次追加文件管理、应用管理左侧贴边。两页主列表现左右均贴内容区，
工具行仍为双侧 32px 留白；独立页面不变。窄屏详情/预览恢复原阅读起点，宽屏分栏维持局部边距，
应用 1227/1228px、文件 927/928px 分栏断点及筛选/搜索换行预算保持。

追加验证均通过且双退出码为 0，无跳过：

- `file-left-green`：文件主列表直接 13 项；`file-left-related`：字体、列宽、状态、命令重排、
  预览开关和焦点等受影响节点 22 项；`window-file-left`：主窗口两种尺寸左右边界 2 项。
- `app-left-green`：应用两视图及详情往返直接 16 项；`app-left-related`：列宽、状态、大字体、
  小工作区及筛选换行等受影响节点 27 项；`window-app-left`：主窗口两视图/两尺寸及临界宽度 5 项。
- 两批追加都先由回归复现左距仍为 32px，再验证新要求 0px；窗口截图分别保存在
  `file-left-screenshots/` 和 `app-left-screenshots/`，已目视检查列表两端及工具栏留白。
- 文件独立对照探针 6 项通过，证明路径、命令和状态控件矩形与追加前一致，预览和断点保持。
- 应用独立对照探针 6 项通过，证明两视图双端贴边、非滚动控件矩形和详情阅读边界保持，
  分栏断点稳定。最终独立审阅的三个阶段均无待解决问题，报告为证据目录 `final-review.md`。
- 累计分阶段覆盖 234 个不同测试节点，最终相关运行均成功，详细命令、去重及原生退出记录见
  本轮证据目录 `acceptance.json`。没有对未触及页面重复全量验证。

## 最新反馈：恢复内容对齐并压缩底部外留白

用户撤回前一阶段列表左侧贴边的视觉方案，保留已确认的右侧滚动条位置，并要求增加中间列表高度。
此前阶段记录仅供追溯，以下目标覆盖前述左侧贴边要求。

- [x] 应用管理恢复左侧 32px 阅读起点；取消 page 底部 24px，仅保留 master 底部 6px。
- [x] 文件管理恢复左侧 32px 阅读起点；底部 30px 改为 6px。
- [x] 保持顶部控件位置、右侧轨道、独立模式、预览/详情阅读边界及宽度断点；补相同窗口下列表
  高度增加 24px 的直接测试，以及两页真实主窗口底部 6px 的集成检查。
- [x] 核查离屏截图、静态检查与独立审阅，记录本轮实际验证范围，不重复已验收的其他页面。

本次修改前快照、局部报告和截图保存于原证据目录 `alignment-bottom/`，保留上一轮已验收记录。

本次验证使用相同隔离 runner，以下五组 89 个不同节点全部通过，无失败或跳过，pytest/原生退出码
均为 0；没有重跑此前全部 234 项。

| label | 本次范围 | 通过 |
| --- | --- | --- |
| `app-align-bottom-green` | `tests/test_app_manager_scroll_edge.py` | 18 |
| `app-align-bottom-related` | 应用列宽、状态及受影响的宽窄窗口/字体/筛选节点 | 27 |
| `file-align-bottom-green` | `tests/test_file_explorer_scroll_edge.py` | 15 |
| `file-align-bottom-related` | 文件列宽、状态、工具重排、预览开关及焦点节点 | 22 |
| `window-align-bottom` | `test_feature_scroll_track_reaches_main_window_edge` 的应用/文件节点及 `test_app_manager_large_font_selection_keeps_rows_at_fit_boundary` | 7 |

独立审阅探针另有 24 项通过（双退出码为 0）：按两页各六种宽度和 12/22 字号对照此前认可版本，
确认顶部控件矩形完全相同、主列表精确增高 24px，详情/预览阅读边界与宽窄切换稳定，无待修改问题。
最终截图已检查；Ruff、相关生产 Pyright、中文注释、文档链接/frontmatter、源文本及差异检查通过。
真实桌面多屏高 DPI 未验证，本次未触及设备、数据或打包边界，未提交或推送。


## 再次反馈：内容右侧留白、底部贴边及文件列表提示

用户确认问题仍在内容区域而非滚动条：之前只调整列表控件外框，视口和表头仍伸到右侧，底部
6px 也不是所要求的贴边。本节覆盖上一阶段的 6px 底部目标。

- [x] 应用图文/表格视图通过材质入口给具体视图添加 32px 右内边距，列表外框和 Fluent 轨道不动。
- [x] 文件列表通过已有焦点样式入口合成 30px 内容内边距，加上原有 2px 透明焦点边框，得到与
  工具行一致的 32px 阅读边界；独立模式清除此规则，主题、字体、强调色和焦点切换保留规则。
- [x] 两页嵌入模式的底部外间距清零；原先 30px 外留白全部交还列表高度。
- [x] 移除文件条目的类型、名称及修改时间提示，保留工具按钮、预览和错误提示，以及类型无障碍
  描述、排序、选择和导航。
- [x] 检查真实主窗口的视口、表头、可见轨道和页底；查看文件、应用两视图的离屏截图。

本次快照、截图及逐项命令汇总保存在原证据目录 `content-inset-bottom/`。仍使用上述隔离 runner，
以下六组共 124 个不同节点通过，pytest 与原生退出码均为 0，无失败或跳过：

| label | 本次范围 | 通过 |
| --- | --- | --- |
| `content-inset-green` | 两页 `scroll_edge` 直接几何、独立/嵌入及预览/详情断点 | 33 |
| `window-content-inset` | 主窗口两种尺寸、三种列表及大字体临界宽度 | 7 |
| `content-inset-related` | 列宽、状态、材质、文件焦点/字号及共享 Fluent/无障碍消费者 | 58 |
| `content-style-refresh-v1` | 三种列表的主题、字号、强调色、键鼠焦点、拖动列宽和横滚 | 3 |
| `tooltip-green` | 文件项无提示、真实帮助事件及图标/无障碍/导航 | 9 |
| `tooltip-related` | 修改时间排序和刷新后选择恢复 | 14 |

右侧和底部回归先复现原有布局问题，列表提示也先由真实 Fluent 提示窗口复现。独立页面保留
原生内容留白，未强制按嵌入页的 32px 对齐。截图位于 `content-inset-bottom/screenshots/`。
本轮不涉及设备协议、配置、用户数据或打包边界；未运行全量或打包，未提交或推送。离屏验证
不替代真实桌面多屏高 DPI 观感检查。

独立审阅无发现，报告为 `content-inset-bottom/final-review.md`；复核了本次快照差异、124 项结果、
样式所有权与状态恢复，并查看文件窄窗和应用图文宽窗截图。修改文件 Ruff、五个生产文件 Pyright、
中文注释、92 份文档链接/frontmatter、846 个源文本及 `git diff --check` 均通过。
