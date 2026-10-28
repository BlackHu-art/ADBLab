# 修复验证记录

对象：`ui-design` 的 `574f0d2b39ae55ce126cb60db58cfefaa0d64a5e` 加本轮未提交修复。
执行时间：2026-10-28 至 2026-10-29。修复映射与兼容性见 [IMPLEMENTATION](IMPLEMENTATION.md)，
任务复核与完整命令、退出码、日志见 [REMEDIATION_EVIDENCE.json](REMEDIATION_EVIDENCE.json)。

## 隔离与范围

- 使用项目 `.venv/Scripts/python.exe`，未安装或升级任何依赖。现有 venv 继承系统 site-packages。
- 每次 pytest 获得同一个 Windows 文件锁，串行执行；单次创建临时用户、配置、缓存、日志与
  pytest basetemp，使用 offscreen，关闭 bytecode、pytest cache 和外部自动加载插件。
- 父进程审计钩子禁止网络、os.system/startfile 和非白名单进程。只允许 socketpair 内部回环
  （排除 5037）及项目 Python 合成子进程。最终增加实际基础 python/pythonw 路径，以支持 venv
  转发器之外的受控原生进程用例。子进程不自动继承 Python 审计钩子，已另行读其测试代码及清理，
  该环境不是操作系统级安全沙箱。未执行真实 ADB、安装器或编译器。
- 仓库外证据目录：`C:/Users/57289/AppData/Local/Temp/adblab-remediation-20261028-dqb367dq`。
  临时 runner 和 guard 的最终源码保存在证据 JSON；实际命令数组及每个退出码也一并保存。
- 基线对照来自 `git archive HEAD` 的独立临时导出，cwd/PYTHONPATH 与第一方导入根都指向导出；
  没有切换原分支或复用当前修改后的源码冒充旧基线。
- 按 TESTING_GUIDE 的增量策略选择直接、真实调用方和共享状态组合。改动影响范围可沿调用链界定，
  未触发正式发布、用户全量要求或未明共享边界，未运行全量套件。没有使用 `not ui` 推断纯单元或并行安全。

## 结果

每项红／绿及关联运行见文末运行索引。已通过的不同批次有重叠，不将通过次数相加成唯一测试数。

最终资源／关闭组合使用：

```powershell
.\.venv\Scripts\python.exe -B C:/Users/57289/AppData/Local/Temp/adblab-remediation-20261028-dqb367dq/run_tests.py LEAD-integrated-lifecycle-v2 tests/test_task_supervision_completion.py tests/test_native_process.py tests/test_native_capture_cleanup.py tests/test_installer_handoff.py tests/test_live_logcat_render_batches.py tests/test_phase2_mainframe_shutdown_gate.py tests/test_window_lifecycle.py tests/test_phase2_live_logcat_gate.py tests/test_installer_update_ui.py tests/test_mobileperf_runner_concurrency.py tests/test_performance_start_lifecycle.py tests/test_performance_package_lifecycle.py tests/test_performance_result_loading.py
```

**283 passed，110 条既有第三方弃用警告，58.35 秒，退出码 0。** 包括受控真实 Python 子进程、
管道继承／取消／超时、Qt 页与主窗实际销毁、安装失败拒绝授权和 MobilePerf 报告尾部场景。
首轮同组合为 23 failed / 260 passed：失败都来自基础 Python 路径被隔离器阻止；仅修正临时
白名单后原组合通过，没有修改测试断言或业务代码。

真实 Qt 窗口探针：40ms 停止截止时间后仍不销毁尚未 join 的子 QThread；释放后页面／窗口
destroyed 均观察到，进程退出码 0，无 Qt fatal，保留预期 residual 警告。它不证明永久阻塞磁盘可终止。

最终静态命令（精确展开文件列表见证据 JSON）：

| 命令 | 范围 | 结果 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B -m ruff check --no-cache <files>` | 54 个修改／新增 Python 文件 | 退出 0 |
| `.venv/Scripts/python.exe -B scripts/check_comment_language.py <files>` | 21 个生产／构建 Python 文件 | 退出 0 |
| `.venv/Scripts/python.exe -B -m pyright -p <temp>/pyright-local.json <files>` | 21 个生产／构建 Python 文件 | 退出 1，5 条既有诊断，下面列出 |
| `.venv/Scripts/python.exe -B scripts/check_source_text.py` | Git 可见第一方文本 | 退出 0，913 个文件 |
| `.venv/Scripts/python.exe -B scripts/check_doc_links.py` | 文档链接与 frontmatter | 退出 0，109 个文档 |
| `git diff --check` | 当前跟踪文件差异 | 退出 0；仅已有 LF/CRLF 提示 |

Pyright 默认配置不能定位现有 system-site-packages 的 Qt 类型。临时 overlay 只加入运行解释器
实际查到的包路径，继承原规则；没有改仓库配置、安装依赖或降低诊断等级。

## 已确认仍存在的基线失败

以下六个 UI 节点在当前修复与 pristine HEAD 使用相同环境均失败；保留原断言，未顺手改布局：

| 测试节点 | 实际失败 |
| --- | --- |
| `test_main_window_layout.py::test_app_manager_fits_inside_small_workspace_page` | 滚动条 maximum 为 0，预期大于 0 |
| `test_workspace_consolidation.py::test_merged_panels_keep_every_card_and_responsive_control[RemotePanel-expected2-aliases2]` | HeaderCardWidget 数量 0，预期 2 |
| `test_navigation_rendering.py::test_shared_content_keeps_round_corner_when_material_changes[Light]` | 圆角背景颜色不符 |
| 同节点 `[Dark]` | 圆角背景颜色不符 |
| `test_navigation_rendering.py::test_route_animation_and_device_bar_visibility_keep_same_theme_surface[True-Light]` | appManagerPage 材质颜色／alpha 不符 |
| `test_responsive_panels.py::test_system_real_reflow_preserves_all_binding_state_validators_and_one_signal` | battery_spy.count 为 0，预期 1 |

A1 的七模块扩大运行达到 600 秒上限（退出 124），未完成，不能当作通过。其后使用失败节点及
代表性组合定位；另一条 home-scroll 组合失败在孤立运行通过，仍保留顺序敏感边界，未宣称整组清洁。

Pyright 当前与 pristine HEAD 的两个文件均得到相同 5 条诊断：

- `gui/main_frame.py:40`：`isValid` unknown import symbol。
- `gui/main_frame.py:637`：`None.installEventFilter` optional member。
- `mobileperf/android/tools/androiddevice.py:461`：`os.path.join` 两条重载／None 参数诊断。
- `mobileperf/android/tools/androiddevice.py:490`：`None.readline` optional member。

类型检查状态是**失败且基线一致**，不是零错误通过。当前与基线日志均保存在证据 JSON。

## 环境受阻与未执行

F1 的 Actions 引用门禁直接集 **58 passed**。扩大整份 `tests/test_ci_contracts.py` 是
**120 passed / 13 failed**：12 个 Bash 用例因 `shutil.which("bash") is None`，1 个标准用户
验收流程测试被 `AUDIT_BOUNDARY_BLOCKED:external_process` 拒绝。未跳过、削弱断言或触发真实 CI。
精确节点保留在该运行日志和 F1 报告。

`main.py --self-check packaging` 未执行／受阻：已检查 `main.py:298` 与
`utils/tool_check.py::_check_scrcpy_bundle`，它会运行真实 ADB version、scrcpy、AAPT2 及本地
helper；与本轮禁止真实工具的执行边界冲突。替身和摘要测试不能替代该自检或冻结产物验收。

同样未执行：真实 javac/d8、PyInstaller/Inno、真实升级／卸载、网络下载、Android 设备命令、
Linux/macOS 物理窗口管理器测试、长期性能采集和真实磁盘故障。没有正式构建、发布或推送。

## 后续验证顺序

1. 单独定位六条 UI 基线断言及组合顺序问题、五条类型诊断，先确认预期再修复，保持原断言强度。
2. 在具备 Bash 的隔离开发／CI 环境重跑工程测试；先核对标准用户验收脚本副作用，再开放专门窗口。
3. 在一次性构建环境运行真实 helper 编译与 packaging 自检，冻结产物另外验收。
4. 授权设备覆盖 Android 用户切换、FPS 目标、APK split 往返、采集停止／断线；隔离 Windows 账户
   覆盖真实升级失败 helper、退出、安装和旧数据保留；Linux/macOS 检查置顶、焦点、隐藏与最小化状态。

<!-- RUN_INDEX -->

## 实际运行索引

下表保留所有尝试，包括初始失败、命令错误和受阻；精确命令、原始输出及每步修正说明见证据 JSON。

| 标识 | 退出码 | 秒数 | 原始结果摘要 |
| --- | ---: | ---: | --- |
| A1-red-delayed | 0 | 1.55 | 1 passed, 1 warning in 1.12s |
| B1-red | 1 | 0.7 | 6 failed, 26 deselected in 0.38s |
| A1-red-delayed-explicit | 1 | 1.7 | 1 failed, 1 warning in 1.27s |
| B2-red-publish | 1 | 0.52 | 5 failed in 0.23s |
| B1-green-direct | 0 | 1.17 | 32 passed in 0.83s |
| B2-red-validator | 1 | 0.51 | 12 failed in 0.19s |
| B1-green-recovery | 0 | 1.23 | 36 passed in 0.90s |
| B2-green-direct | 0 | 2.19 | 62 passed in 1.87s |
| A1-green-direct | 1 | 8.2 | 2 failed, 60 passed, 48 warnings in 7.66s |
| B1-green-final | 0 | 1.22 | 37 passed in 0.88s |
| B2-green-restore | 0 | 0.5 | 4 passed in 0.18s |
| B1-associated | 0 | 1.03 | 57 passed in 0.65s |
| B2-final-direct | 0 | 2.27 | 66 passed in 1.94s |
| B2-related-consumers | 0 | 2.5 | 27 passed, 1 warning in 2.03s |
| A1-green-nodes | 0 | 1.86 | 2 passed, 1 warning in 1.40s |
| A1-green-associated | 124 | 600.02 | TIMEOUT 600s |
| B1-fix1-red | 1 | 0.68 | 4 failed, 37 deselected in 0.36s |
| C1-red | 1 | 0.43 | 9 failed, 6 passed in 0.14s |
| A1-green-direct-complete | 0 | 7.16 | 62 passed, 48 warnings in 6.64s |
| C1-green-direct | 0 | 0.42 | 15 passed in 0.11s |
| C1-associated | 0 | 1.56 | 16 passed, 1 warning in 1.13s |
| A1-collect-location | 0 | 2.21 | 详见原始输出 |
| A1-collect-nodes | 0 | 2.3 | 366/367 tests collected (1 deselected) in 1.85s |
| B1-fix1-green | 0 | 1.26 | 41 passed in 0.94s |
| B1-fix1-associated | 0 | 0.8 | 57 passed in 0.48s |
| A1-related-helper-representatives | 1 | 61.23 | 1 failed, 9 passed, 3617 warnings in 60.32s (0:01:00) |
| A1-related-failure-details | 1 | 12.15 | 4 failed, 1 passed, 259 warnings in 11.56s |
| A2-direct | 0 | 2.05 | 6 passed, 1 warning in 1.70s |
| A2-related | 0 | 1.33 | 10 passed, 2 warnings in 0.98s |
| C2-red-default | 1 | 0.45 | 3 failed in 0.17s |
| C2-green-default | 0 | 0.82 | 42 passed in 0.57s |
| C2-green-expanded | 0 | 0.86 | 47 passed in 0.58s |
| A1-baseline-five | 1 | 14.01 | 5 failed, 264 warnings in 13.47s |
| C2-green-contracts | 0 | 1.14 | 58 passed in 0.86s |
| C2-close-associated | 0 | 3.79 | 8 passed, 1 warning in 3.44s |
| C3-red-core | 1 | 0.38 | 1 failed in 0.13s |
| C3-green-core | 0 | 0.35 | 1 passed in 0.10s |
| C3-red-ui | 1 | 1.15 | 3 failed, 1 warning in 0.82s |
| C3-green-ui | 0 | 1.08 | 3 passed, 1 warning in 0.75s |
| C3-red-commit | 1 | 0.37 | 1 failed in 0.12s |
| C3-green-direct | 0 | 4.3 | 55 passed, 4 warnings in 3.89s |
| E1-red | 1 | 0.51 | 11 failed, 18 passed in 0.24s |
| E1-green | 0 | 0.43 | 29 passed in 0.17s |
| E1-associated | 0 | 3.57 | 73 passed in 3.31s |
| C3-associated | 1 | 9.26 | 2 failed, 114 passed, 5 warnings in 8.78s |
| E1-final | 0 | 3.39 | 102 passed in 3.12s |
| C3-associated-final | 0 | 9.21 | 116 passed, 5 warnings in 8.76s |
| E2-red | 1 | 2.17 | 3 failed, 1 warning in 1.82s |
| E2-green | 0 | 2.1 | 3 passed, 1 warning in 1.74s |
| E2-scoped | 1 | 3.55 | 1 failed, 50 passed, 66 warnings in 3.19s |
| E2-baseline | 1 | 2.38 | 1 failed, 32 warnings in 1.99s |
| E2-final | 0 | 2.74 | 50 passed, 35 warnings in 2.38s |
| D1-red | 1 | 1.53 | 3 failed, 5 warnings in 1.18s |
| D1-green | 0 | 7.95 | 46 passed, 101 warnings in 7.56s |
| D2-red-readers | 1 | 0.56 | 1 failed in 0.30s |
| D2-green-readers | 0 | 0.63 | 1 passed in 0.38s |
| D1-coverage | 0 | 12.7 | 57 passed, 106 warnings in 12.30s |
| E3-red | 1 | 1.84 | 2 failed, 1 warning in 1.49s |
| D2-red-budget | 4 | 0.39 | 1 error in 0.13s |
| E3-green | 0 | 1.78 | 15 passed, 1 warning in 1.43s |
| E3-related | 0 | 16.11 | 42 passed, 1243 warnings in 15.70s |
| D2-red-budget-fixed | 1 | 0.47 | 1 failed, 1 passed in 0.21s |
| D2-red-page | 1 | 1.34 | 1 failed, 1 warning in 1.00s |
| D2-red-page-fixed | 1 | 1.47 | 1 failed, 1 warning in 1.11s |
| D2-green-direct | 1 | 10.32 | 2 failed, 42 passed, 1 warning in 9.95s |
| D1-final | 0 | 17.25 | 103 passed, 106 warnings in 16.79s |
| D2-green-direct-v2 | 1 | 10.66 | 2 failed, 42 passed, 1 warning in 10.27s |
| D2-green-direct-v3 | 0 | 10.38 | 44 passed, 1 warning in 10.03s |
| D1-stubs | 0 | 1.59 | 2 passed, 1 warning in 1.22s |
| D1-start-red | 1 | 1.32 | 1 failed, 4 warnings in 0.96s |
| D1-start-green | 0 | 3.95 | 23 passed, 107 warnings in 3.58s |
| D2-related | 0 | 30.34 | 198 passed, 4148 warnings in 29.95s |
| D2-red-submit | 1 | 0.46 | 1 failed in 0.20s |
| D2-green-submit | 0 | 0.44 | 1 passed in 0.17s |
| D2-final-direct | 0 | 24.61 | 193 passed, 7 warnings in 24.16s |
| D1-native-gate-red | 1 | 1.44 | 1 failed, 1 warning in 1.04s |
| D2-green-join-proof | 0 | 0.66 | 1 passed in 0.40s |
| D1-native-gate-green | 0 | 9.54 | 31 passed, 2 warnings in 9.12s |
| E4-red | 1 | 2.09 | 8 failed, 32 deselected, 1 warning in 1.71s |
| E4-green | 0 | 1.47 | 10 passed, 30 deselected, 1 warning in 1.04s |
| D1-gate-final | 1 | 33.91 | 12 failed, 125 passed, 110 warnings in 33.37s |
| E4-final | 0 | 1.42 | 16 passed, 28 deselected, 1 warning in 0.99s |
| E4-verified | 0 | 1.45 | 16 passed, 28 deselected, 1 warning in 1.01s |
| D1-installer-isolated | 0 | 3.87 | 1 passed, 4 warnings in 3.41s |
| D1-gate-bounded | 0 | 18.3 | 105 passed, 107 warnings in 17.84s |
| D1-owner-red | 0 | 3.99 | 2 passed, 4 warnings in 3.41s |
| D1-owner-repro | 0 | 4.41 | 2 passed, 4 warnings in 3.93s |
| D1-owner-sharedprefix | 0 | 12.17 | 32 passed, 5 warnings in 11.68s |
| D1-owner-nativeprefix | 1 | 19.25 | 1 failed, 6 passed, 4 warnings in 18.78s |
| D1-owner-exact-red | 1 | 17.84 | 2 failed, 4 warnings in 17.34s |
| F1-red-enumeration | 1 | 1.44 | 50 failed, 76 deselected in 1.17s |
| D1-owner-exact-green | 0 | 5.32 | 2 passed, 4 warnings in 4.87s |
| D1-installer-integrated | 0 | 20.34 | 137 passed, 110 warnings in 19.87s |
| F1-green-enumeration | 0 | 0.63 | 51 passed, 75 deselected in 0.37s |
| D2-fix1-red | 1 | 1.69 | 2 failed, 1 warning in 1.34s |
| F1-green-file | 1 | 3.87 | 13 failed, 120 passed, 1 warning in 3.52s |
| F1-green-final | 0 | 0.65 | 58 passed, 75 deselected in 0.40s |
| D2-fix1-green | 0 | 2.73 | 2 passed, 1 warning in 2.38s |
| D2-fix1-direct | 0 | 13.08 | 47 passed, 1 warning in 12.72s |
| D2-fix1-associated | 0 | 28.64 | 122 passed, 4148 warnings in 28.21s |
| F2-red | 1 | 0.49 | 2 failed, 3 passed in 0.22s |
| F2-green | 0 | 0.38 | 5 passed in 0.13s |
| F2-related | 0 | 0.35 | 2 passed in 0.10s |
| LEAD-integrated-lifecycle | 1 | 36.66 | 23 failed, 260 passed, 110 warnings in 36.11s |
| LEAD-integrated-lifecycle-v2 | 0 | 58.86 | 283 passed, 110 warnings in 58.35s |
