# 验证记录

基线：`574f0d2b39ae55ce126cb60db58cfefaa0d64a5e`。所有运行均由 Lead 串行安排；子 Agent 仅阅读并提出验证方案。

## 环境与边界

- Windows / Python 3.11.9；使用项目 `.venv/Scripts/python.exe`。实际 PySide6 6.8.1.1、QFluentWidgets 1.11.3、pytest 9.1.1、Ruff 0.16.3。
- `.venv/pyvenv.cfg` 的 `include-system-site-packages=true`；本轮验证使用当前实际依赖，并不等价于干净安装的可复现环境验收。未安装或升级依赖。
- 所有探针、脚本、缓存、日志位于 `C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm`；未写入生产目录。附录 EVIDENCE.md 保留探针源码和关键失败输出，便于临时目录失效后查证。
- 定向 pytest 通过临时 wrapper 重定向 LOCALAPPDATA、APPDATA、USERPROFILE、XDG_CONFIG_HOME、XDG_CACHE_HOME、TMP/TEMP；设置 QT_QPA_PLATFORM=offscreen、PYTHONDONTWRITEBYTECODE=1、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，禁用 pytest cache。
- 验证前逐项核对副作用。wrapper 通过 Python audit hook 禁止 socket.connect、os.system、os.startfile 及非本解释器子进程；Windows 系统版本只读查询在安装钩子前完成。受控 Python 子进程仅用于既有生命周期测试。
- Python audit hook 不证明可拦截 Qt/C 原生网络；所选测试另经源码核对并替换外部边界。没有运行真实 ADB、设备命令、客户端版本程序、安装器、正式构建或发布，没有访问真实用户配置／历史。
- Qt／线程／子进程／存储测试串行；没有把 not ui 当作纯单元集合，没有运行全量。只读审查未触发测试指南要求的代码改动全量条件。

## 结果总览

有效现有直接测试累计 **308 passed**（16 个完整测试文件及 i18n 的两个参数化测试共 6 项）。新增故障探针得到 **15 个预期契约断言失败、1 个 u0 对照通过**，支持 12 条发现；这是未修复缺陷的证据，不能写成项目测试已通过。其余确认项为静态控制流／时序证据。

两次验证设施错误单列：第一次 r1-direct 的拦截器过严，以及第一次 Logcat 全局关闭 probe 的 host 缺字段。两次均只修临时脚本后重跑，未改变项目、降低断言或新增 skip。

现有测试中的 SciPy/QDomDocument 弃用警告，以及早期临时探针未注册 ui marker 警告均保留于日志；不作为业务失败。

## 实际命令、退出码和输出

以下退出码为被测子进程真实 returncode；`run_validation.py` 外层脚本自身退出 0 不代表测试成功。执行目录均为仓库根。原始完整 stdout/stderr 保留在每条记录的临时日志中。

### source-text

- 退出码：`0`。通过：901 个文本文件；检查 UTF-8/NUL，不证明业务正确性。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\source-text.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B scripts/check_source_text.py
```

```text
Source text integrity passed: 901 file(s)
```

### ruff

- 退出码：`0`。通过：All checks passed；按当前 Ruff 配置检查，未写缓存。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\ruff.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B -m ruff check --no-cache .
```

```text
All checks passed!
```

### supervisor-probe

- 退出码：`1`。确认 F03：3 个断言失败，均是已失败结束任务被当作 ALREADY_STOPPED。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\supervisor-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\test_audit_supervisor.py --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\probe-supervisor
```

```text
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
E       assert <StopDisposition.ALREADY_STOPPED: 'already_stopped'> is <StopDisposition.FAILED: 'failed'>
E        +  and   <StopDisposition.FAILED: 'failed'> = StopDisposition.FAILED
3 failed in 0.12s
```

### r1-direct

- 退出码：`1`。受阻／验证脚本错误：93 passed、1 failed、10 errors。临时审计钩子误拦 platform.uname 的 cmd /c ver，并未接受 Windows executable=None 的受控 Python 子进程。不是项目缺陷结论。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r1-direct.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r1-direct\pytest tests/test_action_results.py tests/test_phase1_operations.py tests/test_device_batch_use_case.py tests/test_device_context.py tests/test_monkey_batch_state.py tests/test_screen_record_use_case.py
```

```text
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
1 failed, 93 passed, 10 errors in 1.68s
```

### r1-direct-v2

- 退出码：`0`。修正临时验证脚本后同一范围 104 passed；未修改项目或测试。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r1-direct-v2.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r1-direct-v2\pytest tests/test_action_results.py tests/test_phase1_operations.py tests/test_device_batch_use_case.py tests/test_device_context.py tests/test_monkey_batch_state.py tests/test_screen_record_use_case.py
```

```text
104 passed, 1 warning in 1.44s
```

### native-cleanup-probe

- 退出码：`1`。确认 F02：1 failed；failed/still_alive=True/active_count=0/idle=True。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\native-cleanup-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\native-cleanup-probe\pytest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_native_cleanup.py
```

```text
        assert result.outcome == "failed"
observed failed still_alive True active_count 0 idle True
1 failed in 0.12s
```

### logcat-dialog-probe

- 退出码：`1`。确认 F06：1 failed；关闭协议完成后启动一个新导出替身。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-dialog-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-dialog-probe\pytest -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_logcat_dialog.py
```

```text
1 failed, 3 warnings in 0.98s
```

### archive-roundtrip-probe

- 退出码：`1`。确认 F08：1 failed；合成 APK 容器的备份成功、恢复安全策略拒绝。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\archive-roundtrip-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\archive-roundtrip-probe\pytest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_archive_roundtrip.py
```

```text
            if args[0]=="shell":return SimpleNamespace(success=True,stdout="package:/data/app/synthetic/base.apk",error="")
                return SimpleNamespace(success=True,error="")
            return SimpleNamespace(success=True,error="")
E       assert ('done', 'restore') in [('log', 'Backup: C:\\Users\\57289\\AppData\\Local\\Temp\\adblab-audit-20261028-l20c86vm\\archive-roundtrip-probe\\pyt...icious'), ('log', 'Restore incomplete: 0 succeeded, 1 failed'), ('error', 'Restore incomplete: 0 succeeded, 1 failed')]
events [('log', 'Backup: C:\\Users\\57289\\AppData\\Local\\Temp\\adblab-audit-20261028-l20c86vm\\archive-roundtrip-probe\\pytest\\test_successful_backup_meets_r0\\backup_org.example.synthetic.zip'), ('done', 'backup'), ('failure', 'Restore failed (1/1) for backup_org.example.synthetic.zip: ZIP archive compression ratio is suspicious'), ('log', 'Restore incomplete: 0 succeeded, 1 failed'), ('error', 'Restore incomplete: 0 succeeded, 1 failed')] install_calls 0
1 failed in 0.14s
```

### r2-direct

- 退出码：`0`。通过：55 passed；原生监督与并发直接测试，无真实 ADB。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r2-direct.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\r2-direct\pytest tests/test_adb_client_admission.py tests/test_native_capture_cleanup.py tests/test_command_outcomes.py tests/test_mobileperf_runner_concurrency.py
```

```text
55 passed in 9.69s
```

### data-handoff-probes

- 退出码：`1`。确认 F01/F04/F09：3 failed、1 passed；u0 是通过对照。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\data-handoff-probes.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\data-handoff-probes\pytest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_data_handoff.py
```

```text
3 failed, 1 passed in 0.29s
```

### logcat-shutdown-probe

- 退出码：`1`。受阻／探针替身缺字段：1 failed，fake host 缺 registry。此轮不作为产品失败证据，finally 已释放并等待线程。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-shutdown-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-shutdown-probe\pytest -c pyproject.toml -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_logcat_shutdown.py
```

```text
1 failed, 2 warnings in 1.21s
```

### logcat-shutdown-probe-v2

- 退出码：`1`。补齐临时 host 后确认 F05：1 failed；close_ready=True、export_running=True、page_disposing=True、active_count=0。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-shutdown-probe-v2.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-shutdown-probe-v2\pytest -c pyproject.toml -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_logcat_shutdown.py
```

```text
1 failed, 2 warnings in 1.07s
```

### data-delivery-direct

- 退出码：`0`。通过：100 passed；设备历史、安装交接、归档和性能解析；只有受控 Python 子进程，没有安装器执行。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\data-delivery-direct.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\data-delivery-direct\pytest tests/test_device_store_concurrency.py tests/test_installer_handoff.py tests/test_app_archives.py tests/test_mobileperf_parsers.py
```

```text
100 passed in 1.57s
```

### logcat-direct

- 退出码：`0`。通过：43 passed；Logcat 绘制/导出和主窗关闭现有测试。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-direct.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\logcat-direct\pytest tests/test_live_logcat_render_batches.py tests/test_phase2_mainframe_shutdown_gate.py
```

```text
43 passed, 99 warnings in 8.30s
```

### numeric-locale-probe

- 退出码：`1`。确认 F12：2 failed；de_DE 小数及 en_US 分组端口被 GUI 接受而后端拒绝。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\numeric-locale-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\numeric-locale-probe\pytest -c pyproject.toml -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_numeric_locale.py
```

```text
2 failed, 1 warning in 0.79s
```

### test-isolation-probe

- 退出码：`1`。确认 F14：1 failed；原测试受控包装，记录到不应有的 version 调用，未执行程序。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\test-isolation-probe.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\test-isolation-probe\pytest -c pyproject.toml -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_test_isolation.py
```

```text
            return SimpleNamespace(success=True,output='Android Debug Bridge version 1.0.41\nVersion 1.0.0',error='')
1 failed, 1 warning in 1.18s
```

### display-ci-probes

- 退出码：`1`。确认 F15/F16：2 failed；真实标签计数陈旧、合成不固定 Actions 引用被原门禁放行。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\display-ci-probes.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\display-ci-probes\pytest -c pyproject.toml -p tests.conftest C:/Users/57289/AppData/Local/Temp/adblab-audit-20261028-l20c86vm/test_audit_display_ci.py
```

```text
2 failed, 33 warnings in 1.70s
```

### translation-resources

- 退出码：`0`。通过：6 passed；三语言内嵌词库与 TS 全条目/格式占位符、GUI tr 字面量覆盖。不是整个 i18n 测试文件运行。
- 原始日志：`C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\translation-resources.log`。

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\pytest_guard.py S:\CodeSpaces\PyCharm\ADBLab -q -p no:cacheprovider --basetemp C:\Users\57289\AppData\Local\Temp\adblab-audit-20261028-l20c86vm\translation-resources\pytest tests/test_i18n.py::test_embedded_catalog_matches_editable_source_and_preserves_format_fields tests/test_i18n.py::test_visible_ui_literals_have_catalog_entries
```

```text
6 passed, 1 warning in 2.27s
```

## 未运行与不能推导的结论

- 无全量 pytest、Pyright 全量或正式打包；未改共享接口，未为审查触发无关构建。Ruff／文本检查通过不代表所有运行行为通过。
- F10 两组测试竞态及 F13 非 Windows 置顶尚无动态复现；F07 reader 生命周期依据源码和现有延迟 reader 用例，未新增真实应用退出探针。F11 构建并发窗口未执行 fake 编译器实验。
- 没有真实 Android 多用户、厂商输出、Root 文件、断连清理、长采集、签名 APK 恢复；没有 Windows 原生窗口树销毁崩溃、高 DPI 桌面视觉、Linux/macOS 窗口管理器、真实升级／卸载验收。
- 翻译测试核对内嵌 QRC 词库与全部 TS 条目；没有重新编译独立 QM 或执行发行产物。第三方二进制仅审集成边界，不证明内部安全或运行兼容。
- 性能没有跑硬件基准，不报告启动／排序／内存收益或故障发生频率。

## 工作区与报告终验

终验脚本位于临时目录 `final_checks.py`。首次运行返回 1，仅因为 EVIDENCE.md 中复制的失败输出有 3 行行尾空格（556/618/631）；原始文件指纹、Git 状态、文档链接均已通过。只清理本轮报告的空格后重新运行；没有更改探针断言、项目或原始日志。

原始清单 2,488 个文件 SHA-256 无变化；当前分支 ui-design、HEAD 574f0d2b39ae55ce126cb60db58cfefaa0d64a5e 与开始一致。Git diff --stat 为空，未跟踪项仅原有两张 PNG、docs/design/ 及本轮新增 docs/reviews/。766 个自有 Python 文件无未审项，五份必需报告均存在。

终验实际命令及首次检查输出（重跑采用同一命令）：

```powershell
git branch --show-current
```
退出码：0

```text
ui-design
```

```powershell
git rev-parse HEAD
```
退出码：0

```text
574f0d2b39ae55ce126cb60db58cfefaa0d64a5e
```

```powershell
git status --short
```
退出码：0

```text
?? demo_a_20261026_233520.png
?? demo_b_20261026_233520.png
?? docs/design/
?? docs/reviews/
```

```powershell
git diff --stat
```
退出码：0

```text
(无输出)
```

```powershell
git diff --check
```
退出码：0

```text
(无输出)
```

```powershell
S:\CodeSpaces\PyCharm\ADBLab\.venv\Scripts\python.exe -B scripts/check_doc_links.py
```
退出码：0

```text
OK: 105 个项目知识文档的链接与 frontmatter 全部通过
```

最终复查：`final_checks.py` 退出码 **0**；原始 2,488 个文件指纹无差异、105 份文档检查通过、报告行尾空格为零、766 个自有 Python 文件无未审项。原始结构化输出保留于 `FINAL_CHECKS.json`。
