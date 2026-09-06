# 浅色云母与阅读区柔化验证

日期：2026-09-06。范围仅为浅色共享材质、只读正文背景和对应文字对比度。
工作树中原有的结果库、预设、布局及清理变更继续保留，不计入本轮验收范围。

## 实现

- `gui/main_frame.py`：浅色云母内容层由 50% 白色改为 20% 的中性浅灰；深色、关闭云母时的底板和原生主题同步逻辑保持原样。
- `gui/styles/theme.py`：浅色阅读背景为 `#F2F4F6`；加深灰色和错误红色，全部 8 个日志前景色在此背景上的对比度不低于 4.5。
- `gui/styles/fluent.py`：新增只读正文背景适配，普通、悬停、聚焦保持相同浅色底板；沿用现有焦点边框和主题/强调色刷新。
- `gui/panels/log_panel.py`、`gui/dialogs/performance_launcher_form.py`、`gui/widgets/run_results.py`：运行记录、性能日志、结果摘要和参数正文接入统一适配。
- 实时 Logcat 已使用共享日志色，无需改动其数据、过滤或滚动逻辑。
- 架构文档补充当前表面层次和只读背景规则。

## 验证结果

解释器为仓库 `.venv\Scripts\python.exe`；Qt 离屏检查使用 `QT_QPA_PLATFORM=offscreen`。

| 检查 | 结果与边界 |
| --- | --- |
| 新材质回归修复前 | 失败：两种模拟底色的输出色差 18，低于输入色差 34 的 70%；修复后为 27，断言保持不变 |
| 新增日志前景对比检查修复前 | 失败：原错误红色在新背景上为 4.375；调整颜色后超过 4.5 |
| 材质直接检查、实时 Logcat 对比度与可访问性 | 10 passed |
| 阅读区、Fluent 组件、实时 Logcat 视觉、全部日志文字对比度集成 | 51 passed |
| 主题、导航、页面动画相关筛选组 | 初次 44 passed、2 failed、2 skipped、92 deselected；两项失败的原因及独立复测见下文 |
| 导航全入口严格留白检查修正后 | 2 passed，覆盖 Light / Dark |
| Windows 原生云母与系统调色板事件 | 2 passed；实际读取 DWM 明暗与云母开关属性 |
| 150% DPI 的只读背景、焦点、主题往返及复制 | 14 passed |
| 性能页日志与主题关联 | 6 passed |
| 结果详情与宿主关联 | 13 passed |
| LogPanel 关联测试 | 4 passed、2 条既有文案断言失败，详见下文 |
| 修改文件 Ruff | 通过 |
| 6 个生产文件 Pyright | 0 errors、0 warnings |
| 中文注释检查 | 通过 |
| 文档链接及 frontmatter | 30 篇文档通过 |
| `git -c core.safecrlf=false diff --check` | 通过 |

上述组有重复节点，不相加为唯一测试总数。未运行全量 pytest、打包或 ADB 实机测试；本轮未修改设备命令、资源收集、依赖或打包边界。

## 两类检查问题的处理

导航全入口检查原先对性能配置页取样 `(2, 2)`，当前页面布局下命中卡片的 `headerView` 圆角。
已通过 `childAt()` 确认这不是共享背景；改在前两个布局控件之间的实际留白取样，先断言点位在页面内且没有子控件，再保持原有严格颜色相等断言。
此项只修正测试取样位置，没有为测试改变页面颜色或放宽断言。修正后两种主题独立复测通过，没有重复运行整个主题筛选组。

`tests/test_logging_contract.py` 的两条既有失败：

- `test_log_panel_text_output_is_wrapped_in_card_container` 仍期待“操作日志”，实际已为“运行记录”。
- `test_log_panel_toolbar_clear_button_wipes_entries` 仍期待“清空操作日志”，实际已为“清空运行记录”。

通过 `git show HEAD:gui/panels/log_panel.py` 确认当前名称在本轮前已存在；本轮该文件只接入样式并更新样式注释。
本轮没有改变这些名称或其断言，因此不宣称整个测试集全部通过。

## 可复查的主要命令

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_reading_surface.py tests/test_fluent_components.py tests/test_live_logcat_visual.py tests/test_accessibility_contract.py::test_theme_text_tokens_keep_readable_contrast
.\.venv\Scripts\python.exe -m pytest -q tests/test_navigation_rendering.py tests/test_main_window_layout.py -k 'navigation_collapse or mica or material or theme or background or route_animation or rapid_route_replacement or menu_collapse_style_reset'
.\.venv\Scripts\python.exe -m pytest -q tests/test_navigation_rendering.py::test_all_navigation_pages_share_material_without_covering_reading_controls --tb=short
$env:QT_SCALE_FACTOR = '1.5'
.\.venv\Scripts\python.exe -m pytest -q tests/test_reading_surface.py
Remove-Item Env:QT_SCALE_FACTOR
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe -m pytest -q tests/test_navigation_rendering.py::test_native_palette_event_preserves_mica_theme
```

## 视觉证据

见同目录 `README.md`、`comparison.json` 和 `before-*.png` / `after-*.png`。
这些图片为隔离 Qt 窗口中的模拟材质，未截图用户桌面，不能代替真实壁纸与 Windows 合成材质的视觉验收。
两种模拟底色下，背景色差保留从约 53% 提高至约 79%，此数值不是原生 Mica 透明度。
调整后任务摘要和性能日志的 8 个普通/聚焦样本均为 `#F2F4F6`，并核验了实际焦点状态。
旧 focus 图片的焦点对象不同，只作为布局基线；不能据此声称已经对比旧版正文聚焦状态。

用户侧最终观察：在 PyCharm 停止并重新运行 `main.py`，启用云母后观察浅色设置页、运行记录、性能日志与结果详情，并往返切换浅色和深色。
原生明暗及开关属性已有自动验证；实际显示器和壁纸下的柔和程度仍需在用户窗口观察。
