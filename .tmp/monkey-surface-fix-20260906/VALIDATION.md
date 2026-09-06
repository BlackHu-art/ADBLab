# Monkey 内部分区底色修复

日期：2026-09-06。本轮仅针对“应用与诊断”页 Monkey 功能块的两处内部结构背景，保留工作树此前修改。

## 根因与修改

外层 Monkey 分区已使用透明 ContentSection，但测试目标和运行参数仍各自创建 SimpleCardWidget，会通过 paintEvent 绘制底色与边框。本轮仅将这两处换为 QWidget 并移除无用导入；原布局、16px 内边距、全部子控件、信号、方案和参数卡运行锁保持。

通过本轮前 app_panel.py 字节副本对比，生产增量只有上述三处。未修改共享样式、主题、ContentSection 或依赖。

## 自动验证

- 修前新增明暗主题像素节点：2 failed，确认浅色内部 #fbfbfb / 页面 #f3f3f3，深色内部 #2b2b2b / 页面 #202020 的差异。
- 修后使用项目 `.venv/Scripts/python.exe`、`QT_QPA_PLATFORM=offscreen`：
  `-m pytest -q tests/test_monkey_layout.py tests/test_monkey_preparation.py tests/test_monkey_library.py` → 69 passed，exit 0。
- 像素节点覆盖两处分区的空白和边缘、悬停、禁用及恢复状态，并确认输入仍有独立背景。
- 关联节点覆盖明暗主题、12/22pt、292/960px 视口、包信息查询/失败/取消、开始/停止/关闭、方案读写与输入保持。
- `ruff check gui/panels/app_panel.py tests/test_monkey_layout.py` 通过。
- `pyright gui/panels/app_panel.py`：0 errors / 0 warnings。
- `scripts/check_comment_language.py gui/panels/app_panel.py`、`scripts/check_doc_links.py` 及限定本轮文件的 `git diff --check` 均通过。存在既有 Qt 弃用和 LF/CRLF 转换警告。

## 视觉与边界

真实 MainFrame 的隔离明暗预览、修前后像素和控件几何见同目录 `VISUAL_VALIDATION.md`。模拟设备仅用于展示，CommandRunner 禁止执行，没有连接设备或运行 Monkey。未运行全量、未重打包 EXE。本轮源码需要重新运行 main.py 后加载。
