# 性能采集结构底板移除

日期：2026-09-06。只改 `gui/dialogs/performance_launcher_form.py` 和新增于 `tests/test_performance_responsive.py` 的两个主题参数节点。之前所有改动原字节已保存到同目录 `*.baseline`。

## 绘制源与最小修复

实际安装 `.venv/Lib/site-packages/qfluentwidgets/components/widgets/card_widget.py` 中，CardWidget / SimpleCardWidget 的 `paintEvent` 绘制卡片底色与边框；普通背景为浅色白 alpha 170、深色白 alpha 13，操作卡还会绘制悬停色。HeaderCardWidget 另有标题分隔线。性能页的配置、结果区仍直接创建 HeaderCardWidget，顶部操作容器仍继承 CardWidget，因此与已实施的去底板要求冲突。

配置和结果区现在使用已有 `ContentSection`；顶部操作容器改为普通 QWidget。保持原来的字体、内边距、响应式尺寸计算、配置锁和控件对象。未修改共享 ContentSection、performance_launcher.py、进度环、日志样式、Toast、宿主、导航或后端。

## 真实 MainFrame 视觉结果

`render_surfaces.py` 构造实际 MainFrame，使用完整 fake AppSettings、内存结果库、隔离用户目录及禁止 CommandRunner 运行的桩。不访问桌面、用户配置或真实设备。分别保存深浅主题修改前后的顶部/结果截图，均已通过 view_image 实看；进程均正常 exit 0。

实际主窗口合成图中，操作区、配置标题/正文空白、结果标题/正文空白共五处：

| 主题 | 修改前 | 修改后 |
| --- | --- | --- |
| Light | #fbfbfb | #f3f3f3，与宿主一致 |
| Dark | #2b2b2b | #202020，与宿主一致 |

浅色日志阅读底仍为 #f2f4f6。深色日志保留上游自己的半透明阅读底与边界，其合成色随下方结构层移除从 #373737 变为 #2d2d2d，仍区别于 #202020 的分区背景。没有改变深色阅读样式或透明度。两主题主窗口横向滚动上限均为 0。

代表截图：`before-light-top.png` / `after-light-top.png`、`before-dark-results.png` / `after-dark-results.png`；原始采样在四个 before/after JSON 中。

## 验证

新增测试先在旧实现取得真实像素红灯：2 failed，见 `red-tests.log`。修复后两节点通过；测试使用显式有色宿主、合成图按 devicePixelRatio 取点，覆盖主题往返、悬停、进度容器空白、分隔线隐藏以及日志独立阅读底保留。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_performance_responsive.py -k 'sections_inherit_blank_surface or persistent_configuration or workspace_performance or groups_fields or bounds_configuration or cards_reflow_without or large_font_running_summary or plan_and_results or result_view_switch or single_layout_preserves or running_locks or embedded_expanded or close_stops_progress'
```

**23 passed，exit 0**。包括宽窄/大字号、控件身份与焦点、单滚动宿主、配置锁、日志/图表切换和关闭释放。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_reading_surface.py -k performance
```

**3 passed，exit 0**。性能日志焦点、主题往返/强调色刷新及复制保持。

```powershell
$env:QT_SCALE_FACTOR='1.5'
.\.venv\Scripts\python.exe -m pytest -q tests/test_performance_responsive.py -k 'sections_inherit_blank_surface or cards_reflow_without'
```

**10 passed，exit 0**。最后只将新增像素测试改为按实际 DPR 采样，并加强深色日志与结构空白的区分断言，生产代码未再改变。

Ruff（生产/测试）、Pyright（form.py，0 errors）、中文注释检查、受影响文件 `git diff --check` 均通过。未运行全量、打包或真实采集。此子任务没有新增文案，现有 ARCHITECTURE 的 ContentSection 去底板事实已覆盖该行为，无需重复文档描述。
