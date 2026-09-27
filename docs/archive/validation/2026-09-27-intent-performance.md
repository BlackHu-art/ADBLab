# Intent 与性能元数据验收记录

日期：2026-09-27。范围为会话批准的首批 Intent / Deep Link 与性能运行元数据，不含后续 APK、
Perfetto 或证据包功能。实现先在隔离 worktree 完成，再于当前项目仍干净、两端 HEAD 一致时
同步回当前工作区，逐文件校验字节一致；没有暂存、提交、推送或版本变更。

## 自动验证

使用隔离 worktree 的 `.venv`，继承原有运行依赖并单独安装项目固定版本测试工具；未安装或升级
系统 Python 的生产依赖。Qt 测试设置 `QT_QPA_PLATFORM=offscreen`。

最终集成命令（以该 venv 的 Python 执行）：

```text
python -m pytest -q tests/test_intent_commands.py tests/test_system_intent.py tests/test_performance_metadata.py tests/test_performance_library.py tests/test_performance_result_loading.py tests/test_i18n.py tests/test_responsive_panels.py::test_system_real_reflow_preserves_all_binding_state_validators_and_one_signal tests/test_action_feedback.py::test_intent_signal_uses_result_routing_duplicate_guard_and_close_boundary --tb=short
```

结果：**232 passed**。覆盖输入拒绝、远端 quote、旧入口、错误回显、类型化参数、请求目标快照、
重复请求、成功/失败/取消、关闭准入、异步附件加载、运行串档、元数据损坏/预算/停止，以及三语词库。
420 像素窄布局与 860 像素、18 号字体布局均通过控件边界检查并生成截图检查；这不是实际 Windows
桌面高 DPI 与云母效果的完整人工验收。第三方 SciPy/Qt 弃用警告保留。

- `python -m ruff check <本轮生产与测试 Python 文件>`：通过。
- `python -m pyright --project <临时环境配置> <11 个相关生产模块>`：0 errors；临时配置只让
  Pyright 定位 venv 继承的既有 site-packages，未修改项目类型标准。`startup.py` 历史上未列入
  默认检查，直接单独检查仍有旧 Optional 问题；新增元数据代码的相关类型错误已处理。
- `python scripts/check_comment_language.py <本轮生产文件>`：通过。
- `python scripts/check_doc_links.py`：通过。
- `git diff --check`：通过。
- 在当前项目执行 `python main.py --self-check packaging`：退出码 0，全部资源/依赖/工具检查通过。
  隔离 worktree 起初缺少忽略的运行时工具，故其自检未通过；同步后复用当前项目现有工具通过检查。
  未执行 PyInstaller 正式构建或发布。

更大范围的关联检查发现既有失败：
`test_action_feedback.py::test_task_center_exposes_running_plain_commands_without_native_operation`
期望任务中心按钮文本含计数，实际文字被截断。在修改前的原工作区复现相同失败，未纳入本轮修复，
也未删除或放宽断言。本轮不宣称整个仓库全量测试通过。

## 模拟器实际验证

目标由 MuMu 管理工具确认，为 Android 15 / API 35；未在记录中写入设备连接标识。

- 使用真实 `ADBModelCore._run` 与 Intent model：系统 Action + 等待结果、显式组件 + Flags、
  字符串/布尔/整数/小数广播参数通过；无接收者的自定义 URI 和不存在的组件正确返回失败。
- 从设备采集版本、环境后执行原子写入、读取、附件发现；设置应用版本为 `15 (35)`，
  错误运行标识被拒绝，新附件不包含序列号字段。
- 使用真实 `MobilePerfRunner` 启动独立采集 worker：2 秒采样，配置时长 60 秒，无 Monkey，
  约 15 秒后主动停止。退出码 0，生成非空报告和完整元数据，配置快照及 run_id 附件绑定正确；
  停止后进程与模式线程退出。验收临时目录在资源退出后清理。

模拟器验证执行协议、归档与生命周期，不作为真机性能数值基准。

## 审查收尾

独立 agent 审查 Intent 后端及 GUI，主任务检查性能差异。发现并修复广播 Bundle key 首尾空格
被规范化的问题；新增回归保留 `" key "` 与 `"key"` 两个独立键。版本索引不写语言相关说明句，
未知和超长摘要按已有字段边界处理，完整信息保留于元数据附件。

当前行为说明见 [Intent 业务流程](../../project-knowledge/BUSINESS_FLOW.md#系统工具中的-intent-调试)
和 [性能元数据](../../project-knowledge/DATA_FLOW.md#性能运行元数据)。
