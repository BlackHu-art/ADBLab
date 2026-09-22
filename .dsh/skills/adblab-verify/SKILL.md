---
name: adblab-verify
description: >-
  ADBLab（本仓库：Python 3.11 + PySide6 的 Android 调试桌面应用）的验证与门禁执行方式：
  如何按"先直接、再关联、必要时全量"选择 pytest 范围，如何跑 ruff / pyright / 注释语言 /
  文档链接 / 打包自检，Qt 测试的离屏约定，以及本机 PowerShell 输出、编码、目录边界上的已知坑。
  Use when running tests, reproducing a defect, confirming a change works, or asking which
  commands validate a change in this repo.
whenToUse: 需要为 ADBLab 选择并执行验证命令，或判断"改完算不算验证通过"时。
---

# ADBLab 验证与门禁

工作目录是仓库根；一律用仓库内解释器 `.venv\Scripts\python.exe`，不要用系统 Python。

## 1. 选择测试范围（先窄后宽，不默认全量）

1. **直接测试**：`.\.venv\Scripts\python.exe -m pytest -q tests/test_<area>.py`（可用 `::node` 收窄）。
2. **关联测试**：按调用链扩大。常见配对：
   - `core/exec.py`、`core/native_process.py` → `test_command_outcomes.py`、`test_model_processes.py`、`test_native_process.py`、`test_native_execution_boundary.py`
   - `models/adb_*.py` → `test_model_*.py`、`test_adb_injection_argv.py`
   - `controllers/` → `test_phase1_operations.py`、`test_phase2_*_gate.py`、`test_action_results.py`
   - `gui/dialogs/file_explorer*` → `test_file_explorer_*.py`、`test_file_app_device_admission.py`
   - `gui/panels/remote_*`、`services/remote/` → `test_remote_*.py`、`test_scrcpy_*.py`
   - 文案/翻译 → `test_i18n.py`、`test_application_languages.py`、`test_dialog_languages.py`
3. **全量**只在代码稳定后的条件性验收触发；触发条件与重跑规则见
   `docs/guides/TESTING_GUIDE.md#增量验证策略`，完整门禁清单见同文件`#完整门禁命令`。
   整理文档、修测试、长任务收尾、推 main 都不触发全量。

## 2. 静态与一致性检查

```powershell
.\.venv\Scripts\python.exe -m ruff check <changed-python-files>
.\.venv\Scripts\python.exe -m pyright <affected-production-paths>   # 仅在共享类型接口变化时
.\.venv\Scripts\python.exe scripts/check_comment_language.py <changed-production-paths>
.\.venv\Scripts\python.exe scripts/check_doc_links.py              # 改过 docs/ 时
git diff --check
```

- 生产代码注释与 docstring 必须是规范中文；技术标识保留原文。
- 不要运行 `compileall`，不要引入未配置的 mypy / pytest-qt / Sphinx / MkDocs。

## 3. Qt / UI 测试

- 需要离屏时先设 `$env:QT_QPA_PLATFORM = "offscreen"`（`tests/conftest.py` 也会 setdefault）。
- 项目**未配置 pytest-qt**：用 `QTest`、`QSignalSpy`、`QTimer.singleShot`，等待几何/状态用
  `tests/ui_geometry_helpers.py` 的 `wait_until` / `wait_for_stable_geometry`。
- 线程/关闭类改动必须覆盖：成功、失败、取消、重复启动、窗口关闭、晚到回调。
- 视觉项无法自动验证时，在汇报里给出人工检查步骤，不要声称已通过。

## 4. 打包与启动边界

仅当改动触及启动入口、依赖、资源收集、运行时路径或打包边界时：

```powershell
.\.venv\Scripts\python.exe main.py --self-check packaging
```

PyInstaller 构建（`.venv\Scripts\python.exe -m PyInstaller ADBLab.spec --noconfirm --clean`）
属于需要用户确认的操作，不要顺手执行。

## 5. 本机已知坑（Windows）

- PowerShell 或子进程输出的编码与终端不一致时可能出现乱码，不能据此判断文件损坏。
  先用 `scripts/check_source_text.py` 严格验证源文件，再核对读取与输出编码；不要猜测编码后覆盖文件。
- 中文提交信息、路径带空格（本仓库位于 `Program Files (x86)`）时注意引号。
- `mobileperf/extlib/`、`reference/`、`runtime-tools/`、`resources/icons/` 不参与 lint/覆盖率，
  也不要在未授权时改动。

## 6. 汇报纪律

说明：修改了什么与为什么、实际运行的命令与结果、**未运行/无法运行**的检查、用户可感知变化、
剩余风险与人工验证步骤。未验证不得写成"通过"；测试失败要给出真实输出片段而不是复述结论。
