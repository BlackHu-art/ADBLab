# 统一 Toast 提示验收记录

日期：2026-09-06。范围仅为本轮纯消息弹窗迁移、截图提示完整性、共享提示生命周期及关联文档；工作树中其他已有改动不属于本轮验收。

## 完成内容

- 审计 31 处 FluentMessageBox 调用，均未依赖返回值，经兼容入口统一为窗口右上角非阻塞 Toast。另将 3 处已有 InfoBar 接入同一组件。
- 保留 4 处文本输入调用，以及权限编辑、应用预设、文件和目录选择等实际交互表单。截图删除保留二次点击确认。
- 提示根据实际字体和可用宽度换行；长标题、长路径和长正文可在提示内滚动并选择复制。重复内容合并，每个窗口最多 3 条，并按窗口高度进一步限制数量。
- 常规提示自动消失，悬停暂停；窗口关闭释放提示及计时器。位置避开原生窗口操作按钮。
- 截图完成提示保留“查看结果”入口，按钮单独排布。复制、删除提示不再覆盖底部截图信息；删除确认提示到期后同步关闭。

## 自动化验证

环境：项目 `.venv`，Python 3.11.9、PySide6 6.8.1.1、qfluentwidgets 1.11.3。

| 命令/范围 | 结果 |
| --- | --- |
| `QT_QPA_PLATFORM=offscreen`；`python -X faulthandler -m pytest -q tests/test_notifications.py tests/test_fluent_dialog_contract.py tests/test_screenshot_page.py tests/test_run_library_ui.py` | 57 passed，退出码 0 |
| `python -m pytest -q tests/test_dialog_languages.py` | 9 passed，退出码 0 |
| `QT_QPA_PLATFORM=windows`；`python -X faulthandler -m pytest -q tests/test_notifications.py` | 11 passed，退出码 0 |
| 截图页面及主窗口截图通知的直接测试 | 14 passed，退出码 0；与上述 57 项部分重叠 |
| `python -m pytest -q tests/test_phase2_screenshot_gate.py` | 18 passed，退出码 0 |
| 设置语言保存、恢复设置两个关联节点 | 2 passed，退出码 0 |
| 本轮 13 个 Python 文件 Ruff | 通过 |
| 本轮 7 个生产模块 Pyright | 0 errors，0 warnings |
| 本轮 7 个生产模块中文注释检查 | 通过 |
| `python scripts/check_doc_links.py` | 30 篇文档通过 |
| `git diff --check` | 通过 |

上述 pytest 命令均使用 `.venv/Scripts/python.exe`。各行存在覆盖重叠，不累计为独立用例总数。测试有上游弃用警告，无测试失败或原生进程崩溃。

## 实际 Qt 渲染与交互

- `toast-mainframe-package-dark-860x1000-font12.png`：真实 MainFrame、深色、12pt，实际点击性能页面开始按钮；缺包名产生右上角 Toast，无模态遮罩，输入框可继续编辑，模拟采集器未被启动。提示坐标为 `(556, 60, 280, 94)`。
- `toast-mainframe-action-light-860x800-font22.png`：真实 MainFrame、浅色、22pt，截图结果正文完整换行，“查看结果”按钮完整显示；实际点击只触发一次动作并关闭提示。提示坐标为 `(368, 60, 468, 216)`。
- 截图复制、删除确认、长错误及滚动至错误尾部的图像和测试输出位于相邻 `.tmp/toast-screenshot-20260906/` 目录。
- 自动化覆盖窄窗口、字体放大、长路径、长标题、重复提示、堆叠、窗口调整大小、悬停暂停、关闭释放和操作按钮。

渲染与测试使用模拟设备和内存配置，没有执行真实 ADB 操作。没有重新运行全量测试或构建 EXE；本轮未触及依赖、资源收集或打包边界。

## 人工查看

在 PyCharm 停止并重新运行 `main.py` 后，空包名点击开始采集可查看警告提示；截图完成可查看结果入口；查看截图时复制或触发删除确认，可检查底部信息持续保留。

完整调用检查清单见同目录 `audit.md`；其中行号记录的是本轮迁移前的调用快照。
