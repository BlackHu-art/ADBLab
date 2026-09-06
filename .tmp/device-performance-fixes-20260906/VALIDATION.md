# 设备概览、性能采集与截图工具整理

日期：2026-09-06。基于当前 `ui-redesign` 工作树增量修改，保留此前未提交成果。没有提交代码、升级依赖或修改用户配置格式。

## 本轮行为

- 设备摘要和详情改为单行键值、列内对齐，窄屏按实际字体重排。省略只影响显示，提示和复制使用完整设备快照。
- 严格整数下拉在程序赋值时同步上游选中索引，修复显示 600 后首项 10 被误认为已选中的问题。
- Monkey 取得实际进程后才提交运行状态，保留重复启动保护；合并其错误输出，识别 EOF 并保存短日志，失败经过采集收尾传回 worker。Activity 输出仅在首个分隔符拆分，避免值中包含冒号时解包失败。
- 性能列表按所选设备和已有会话分别显示状态、预计进度和已用时间，完整计划在提示和当前设备详情中保留。列表最多三行并可收起；点击只切换查看，不修改操作目标或启动任务。启动和停止仍只作用于当前查看设备，不隐式批量运行。
- 性能页隐藏宿主重复的“结束性能采集”，保留页内启动与停止；功能分区使用透明布局，日志等实际内容仍保留阅读底色。为覆盖式滚动条留出独立通道。
- Toast 改为单行图标、标题、正文、可选动作和关闭按钮。正文换行转为空格，长内容可横向浏览及选择复制，原始正文保存在提示和辅助描述中；自动关闭、悬停暂停、去重和窗口关闭清理保持。
- “文本与屏幕”复用原控件迁至“截图与屏幕”；原入口改名“应用与诊断”，使用 CODE 图标，截图入口使用 CAMERA。清除图片会话前归还共享控件，录屏停止仍指向原批次设备。
- 截图页隐藏重复工具标题，两行操作后由画布占用剩余高度；工具区变化时仅在适应窗口模式刷新倍率，手动缩放保持。宽屏、窄屏大字号及英文高 DPI 的最终预览中，工具与底栏同屏。

## 已完成的自动化验证

均使用项目 `.venv/Scripts/python.exe`。下面范围存在重叠，不累计为独立用例总数。

| 范围 | 结果 |
| --- | --- |
| `tests/test_device_hub_page.py` | 72 passed，退出 0 |
| 严格整数下拉及性能响应式直接组合 | 54 passed，退出 0；之后分区透明像素及布局节点另行验证 |
| `tests/test_performance_sessions.py tests/test_performance_progress.py tests/test_workspace_feature_host.py tests/test_model_performance_launcher.py tests/test_performance_library.py` | 101 passed，退出 0 |
| 多设备列表最终直接回归 | 7 passed，退出 0；含折叠、字体、完整计划提示 |
| Windows 原生多设备列表 | 7 passed，退出 0 |
| 性能透明分区布局/关闭关联 | 23 passed，退出 0 |
| 性能日志阅读底色 | 3 passed，退出 0 |
| 150% DPI 性能透明像素和宽窄布局 | 10 passed，退出 0 |
| `tests/test_notifications.py tests/test_fluent_dialog_contract.py tests/test_dialog_languages.py tests/test_screenshot_page.py tests/test_run_library_ui.py` | 81 passed，退出 0 |
| Windows 原生单行 Toast | 14 passed，退出 0 |
| `tests/test_i18n.py tests/test_application_languages.py` | 30 passed，退出 0 |
| 后端配置、Monkey、解析、Runner 并发与停止关联 | 86 passed，退出 0；之后只增加三项直接测试 |
| 后端最终直接回归 | 27 passed，退出 0 |
| `tests/test_flat_feature_navigation.py tests/test_workspace_consolidation.py tests/test_main_window_layout.py::test_all_embedded_feature_pages_remain_reachable_on_short_workspace` | 43 passed，退出 0 |
| 最终截图画布、标题去重与共享工具直接回归 | 18 passed，26 deselected，退出 0 |

上述 UI 测试存在 qfluentwidgets/Qt 既有弃用警告，无测试失败或原生退出崩溃。

GUI 本轮 13 个生产模块 Pyright 为 0 errors / 0 warnings，生产 Ruff、中文注释与文档链接检查通过。三个 MobilePerf 内核文件存在历史类型问题：原字节隔离基线 53 个错误，当前 46 个，无新增诊断；不把该部分描述为 Pyright 全绿。比较证据见 `backend/evidence.md`。

## 实际 Qt 预览

- `device/device-after-light-1000-font12-zh_CN.png`：同一快照展开卡高从 361 降为 277，摘要从 41 降为 20；深色窄窗及英语/大字号另有预览。
- `root/performance-two-devices-*.png`：真实 MainFrame、两个模拟采集器；20% 与 10% 独立更新，每个 runner 只启动一次，行点击不串线，关闭重复入口隐藏，无横向滚动。
- `surfaces/after-light-top.png`、`surfaces/after-dark-results.png`：分区空白与宿主像素一致；输入、按钮、日志保留自己的显示边界。
- `toast-single-line/toast-single-light-860-font12.png`：常规截图成功提示 516×48，正文和“查看结果”完整单行。
- `toast-single-line/toast-single-dark-860-font22.png`：放大字号通知 812×61，正文和动作仍完整可见。另验证 150% DPI 和极窄窗口。
- `../screen-tools-relocation-20260906/screen-tools-light-1360x900-font12-zh_CN.png`：截图工具两行，画布高 492，重复标题已隐藏，横向和纵向滚动范围均为 0。
- `../screen-tools-relocation-20260906/screen-tools-dark-860x800-font22-zh_CN.png`：大字号时画布高 218，按钮与底栏同屏，横向和纵向滚动范围均为 0；英文 125% DPI 同样通过。

最后重新渲染两个多设备场景，进度分别完整显示为 `20% · 02:00` 和 `10% · 02:00`；两个 runner 各启动一次，行切换两次，横向滚动范围为 0，日志上下边缘均可滚动到达。性能页保留正常纵向滚动，设备状态列表可收起以腾出内容高度。

额外 500px 宽 / 22pt 的截图页探针仍有既有底栏组导致的横向滚动，所有按钮可滚动到达；该极窄边界没有作为无横滚通过。完整迁移证据见 `../screen-tools-relocation-20260906/VALIDATION.md`。

图像由真实 Qt 控件及隔离设置渲染，设备和外部命令使用模拟对象。没有在真实设备启动 Monkey 或性能采集；源码 `main.py --self-check packaging` 已通过，没有重新打包 EXE，也没有执行全量测试。运行中的 PyCharm 进程需要停止后重新运行 `main.py` 才会加载修改。
