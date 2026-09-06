# 性能采集诊断选项常显

日期：2026-09-06。本轮仅调整诊断区布局及对应测试、文档，保留工作树已有修改。

## 行为

- 保存位置下方直接展示诊断选项，使用小标题与透明容器，去掉原展开/收起按钮。
- 堆快照间隔、异常日志关键字、结束后拉取的设备日志复用原控件；最多三列，按宽度和字号重排。
- 配置运行锁覆盖全部诊断输入，方案回填及数据格式不变。非法数字仍保留原文并滚动定位，不会启动采集或提前提交其他字段。
- Monkey 参数仍由“同时运行 Monkey”勾选状态控制。

## 本轮自动检查

使用项目 `.venv/Scripts/python.exe`，Qt 测试设置 `QT_QPA_PLATFORM=offscreen`。

- 修改前基线：`-m pytest -q tests/test_performance_responsive.py`，51 passed，进程退出 0。
- 修改后：`-m pytest -q tests/test_performance_responsive.py tests/test_performance_library.py tests/test_feature_typography.py tests/test_dialog_languages.py`，102 passed，进程退出 0。包括正常/窄窗、大字体、明暗主题、三语言、方案回填、运行锁、校验焦点、滚动可达与关闭路径。
- 最终视觉复核发现 22pt 窄窗仍三列，随后只给诊断网格增加按标题自然宽度换列的约束。最终重新运行 `test_performance_responsive.py`，51 passed，进程退出 0；三场景重新渲染均退出 0。正常和英文高 DPI 仍三列，大字号改为两列，同排标签和输入对齐。
- `-m ruff check gui/dialogs/performance_launcher_form.py tests/test_performance_responsive.py tests/test_feature_typography.py tests/test_dialog_languages.py`：通过。
- `-m pyright gui/dialogs/performance_launcher_form.py`：0 errors / 0 warnings。
- `scripts/check_comment_language.py gui/dialogs/performance_launcher_form.py`：通过。
- `scripts/check_doc_links.py`：30 篇知识文档链接与 frontmatter 通过。
- 对本轮六个修改文件执行 `git diff --check`：通过；仅有仓库既有 LF/CRLF 转换警告。

测试存在 qfluentwidgets/Qt 的既有弃用警告，没有失败或原生崩溃。不累计修改前后用例数量。

## 范围与限制

生产修改：`gui/dialogs/performance_launcher_form.py`。关联测试：上述三个 UI 测试文件。文档：`docs/project-knowledge/ARCHITECTURE.md`、`docs/guides/TESTING_GUIDE.md`。

没有修改采集后端、依赖、资源、用户设置或用户数据格式；没有连接设备或启动真实采集，没有执行全量测试或重新打包。视觉验证记录见同目录 `VISUAL_VALIDATION.md`。
