# 本轮遗留清理证据

日期：2026-09-06。子任务范围：已授权的失效内部代码和阶段文件清理。

## 修改边界

开始时 `git status --short` 无输出。已阅读根 AGENTS、docs/README、文档约定和测试指南；没有更近的 AGENTS。
本清理子任务未改 CI、依赖、版本、正式 docs、用户数据、二进制、正式翻译资源，未触及并行任务负责的结果/方案文件。
“未改正式翻译资源”仅限定本清理子任务；总任务已由翻译代理新增结果/方案词条并同步三语言 TS、QM 和 RCC。
代码修改前的两个目标文件以 Git 提交 `a90b3e2e599cd7c06343a2ff151cd695e3b76ff1` 为来源，
可用 `git show <commit>:gui/widgets/device_context_bar.py` 和 `git show <commit>:tests/test_global_device_context.py` 追溯。
删除文件的路径、原大小和 SHA-256 位于 `cleanup-removed-manifest.json`；本轮冗余副本的最终清单位于 `cleanup-final-artifacts.json`。

## 1. 移除设备栏的隐藏旧按钮

修改：`gui/widgets/device_context_bar.py`、`tests/test_global_device_context.py`。

- `info_button`、`disconnect_button` 是旧版本按钮，构造后立即 hide，既不加入可见操作行，也不用于菜单尺寸或布局。
- 替代入口已存在：`info_action`、`disconnect_action` 由 `RoundMenu` 承载，直接连接 `info_requested`、`disconnect_requested`。
- MainFrame 只连接上述业务信号；没有消费旧按钮字段。
- 检查生产代码、测试、docs、包导出、字符串访问和 Qt 信号绑定后，唯一剩余外部消费者是 `test_more_menu_keeps_device_actions_and_selection_enablement` 中针对旧按钮的实现细节断言。
- 移除隐藏按钮构造、旧按钮点击转发和重复 enabled 同步；说明文字直接设置给 Action。
- 测试保留并迁到真实菜单点击：选中时单次发出原业务信号并关闭菜单；无选择时两个动作均禁用且点击不触发；说明文字保持原值。
- 现有 `test_more_menu_fully_contains_actions_and_accepts_real_clicks` 在 12/22 pt 下继续验证真实菜单项目的包含关系、可点击性与关闭行为。
- 未改变业务信号、设备选择、连接/断开语义及菜单公开行为。

## 2. 删除完成后的临时 i18n 批量生成工具和输入

以下六个具体文件均经 `git ls-files` 确认为 Git 跟踪，`git check-ignore` 未匹配；总原始大小 58,307 字节：

- `.tmp/localize_panels.py`
- `.tmp/build_panels_translations.py`
- `.tmp/panel-task-translations.tsv`
- `.tmp/panels-english.tsv`
- `.tmp/panels-source.txt`
- `.tmp/panels-sources.json`

证据：

- `localize_panels.py` 是在一次性面板本地化时直接重写 Python 源码的 AST 脚本，不是运行时翻译器。
- `build_panels_translations.py` 消费固定索引词表，输出写死到历史 Codex 会话目录，不具备当前仓库可重复构建入口的契约。
- 这组文件只有彼此之间的直接输入关系；没有应用 import、Qt 注册、测试、正式 docs、spec 或 workflow 消费者。
- `panels-source.txt` 记录旧源文件的行号及中文字符串，是扫描结果，不是用户设备记录或配置。
- 452 个扫描源词中，451 个已同时进入 `adblab.zh_CN.ts`、`adblab.en_US.ts`、`adblab.zh_HK.ts`；唯一不在词库中的单字“设”在原生成脚本里被明确排除。55 个追加词也已同时进入三词库。核对计数保存在删除清单 JSON 中。
- 本清理子任务保留正式 `.ts`、`.qm`、`gui/generated/translations_rc.py`，以当前词库为单一来源；后续总任务的新增词条由翻译代理统一更新。

替代流程已在 `docs/guides/BUILD_AND_RUN.md` 的翻译资源段落维护：

```powershell
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.zh_CN.ts -qm resources/i18n/adblab.zh_CN.qm
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.en_US.ts -qm resources/i18n/adblab.en_US.qm
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.zh_HK.ts -qm resources/i18n/adblab.zh_HK.qm
.\.venv\Scripts\pyside6-rcc.exe --compress 9 --threshold 0 resources/i18n/translations.qrc -o gui/generated/translations_rc.py
```

本清理步骤没有改词库，也没有自行生成翻译资源；总任务的词库更新和资源生成已独立完成。

## 3. 修正旧执行层归属说明

`models/base/__init__.py` 原 docstring 声称该包提供统一命令执行和进程生命周期管理；当前包内仅有 `focus_detector.py`，其执行依赖已直接来自 `core.exec`。
只把模块说明改为实际的模型共享能力及 `core.exec` 归属。保留 `__init__.py` 包入口和所有导入行为。

## 经审查明确保留

- `gui/main_frame.py::_onCurrentInterfaceChanged`：虽然项目内没有直接调用，活动 `.venv` 安装的 `qfluentwidgets/window/fluent_window.py` 第 328/432 行会将 `stackedWidget.currentChanged` 连接到该重写方法；属于 Qt/父类动态入口。
- `gui/features/*.py`、`gui/widgets/responsive_controller.py` 等轻量导出层：是实际导入路径或公开 facade，不能按文件小或转发实现判定失效。
- `models/base/__init__.py`：包结构仍有消费者，仅修正文案。
- `AppSettings` 旧 schema/宽度迁移、`DeviceStore` 旧 YAML 来源、兼容取消和布局入口：存在迁移或调用契约，未删除。
- 所有本轮开始前已有的 `.tmp/` 历史图片、baseline、探针、VALIDATION 和 Qt 退出异常证据，以及 `docs/archive/`：保留追溯用途，未遍历删除。本轮新建、可从上述 Git 提交恢复的副本按下一节精确清理。
- `.venv/`、`venv/`、reference、IDE 配置、缓存、真实设备数据、平台二进制和正式资源：不在清理范围。

## 4. 收尾清理本轮冗余副本和一次性词库工具

主任务明确授权的 8 个精确目标共包含 15 个文件，合计 1,453,731 字节。删除前已核对每个解析后的绝对路径和所有成员均位于 `.tmp/next-stage` 或 `.tmp/run-library-20260906` 对应目录；用原生 PowerShell `Remove-Item -LiteralPath` 删除。

| 精确目标 | 文件数 | 字节 | 来源与保留入口 |
| --- | ---: | ---: | --- |
| `.tmp/next-stage/cleanup-baseline/` | 2 | 52,838 | 设备栏及直接测试的干净 HEAD 副本 |
| `.tmp/run-library-20260906/i18n-baseline/` | 7 | 1,297,577 | 三语言 TS/QM 和生成 RCC 的干净 HEAD 副本 |
| `.tmp/run-library-20260906/performance_launcher.baseline.py` | 1 | 32,277 | `gui/dialogs/performance_launcher.py` 的干净 HEAD 副本 |
| `.tmp/run-library-20260906/performance_launcher_form.baseline.py` | 1 | 47,333 | 对应 form 模块的干净 HEAD 副本 |
| `.tmp/run-library-20260906/performance_launcher_run.baseline.py` | 1 | 10,141 | 对应 run 模块的干净 HEAD 副本 |
| `.tmp/run-library-20260906/performance-baseline.patch` | 1 | 0 | 本轮开始时为空的 diff 记录 |
| `.tmp/run-library-20260906/catalog_inventory.py` | 1 | 3,020 | 本轮词库增量核对的一次性工具 |
| `.tmp/run-library-20260906/sync_run_library_catalogs.py` | 1 | 10,545 | 本轮新增词条的一次性生成工具；正式词库和上文构建命令保留 |

12 个源码/资源副本均核对为上述 Git 提交内容一致（允许 Git 换行转换）；逐文件 SHA-256、字节数、来源路径和比对结果保存在 `cleanup-final-artifacts.json`。最终截图和 render 脚本全部保留，未清理缓存或任何既存历史目录。

## 验证

环境：仓库 `.venv`，Qt 菜单测试显式设置 `QT_QPA_PLATFORM=offscreen`、`QT_SCALE_FACTOR=1`。

1. 修改前与修改后各运行一次：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q tests/test_global_device_context.py::test_more_menu_keeps_device_actions_and_selection_enablement tests/test_device_context_bar_presentation.py::test_more_menu_fully_contains_actions_and_accepts_real_clicks
   ```

   两次均 **3 passed，exit 0**。出现已安装 qfluentwidgets 的 Qt API 弃用警告，无失败。

2. 临时翻译工具删除后的正式资源关联检查：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q tests/test_i18n.py tests/test_ci_contracts.py::test_packaging_uses_explicit_resource_allowlist_and_keeps_licenses
   ```

   **29 passed，exit 0**。

3. `ruff check` 覆盖修改的两处生产文件和测试：通过。
4. `pyright gui/widgets/device_context_bar.py`：0 errors、0 warnings。
5. 中文注释检查覆盖两个生产路径：通过。
6. 限定本子任务文件的 `git diff --check`：通过。

未运行全量 pytest、正式构建或 ADB 实机测试；本轮未触及执行边界、资源收集和发布入口，不触发这些验证。正式 docs 汇总由主任务统一负责。
