# 测试指南

## 测试框架与现状

- 框架：pytest；`pyproject.toml` 把项目根加入 `pythonpath`。
- 测试目录：`tests/`，当前 4 个文件、229 个测试。
- 2026-07-23 使用 Python 3.11 实际运行：229 项全部通过，耗时 2.83 秒。
- 测试主要使用 monkeypatch、临时目录、轻量 fake/stub 和通过 `__new__` 构造的最小 Qt 对象；不要求真实 Android 设备。
- 没有覆盖率工具配置或覆盖率基线，不能由“229 项通过”推导语句/分支覆盖率。

## 测试目录

| 文件 | 规模/职责 | 主要类型 |
| --- | --- | --- |
| `tests/test_model_execution.py` | 约 3,941 行；启动、GUI 生命周期、命令/进程、Controller、ADB model、MobilePerf、App/File/Log 等综合回归 | 单元 + 轻量组件/契约测试 |
| `tests/test_remote_services.py` | Remote launch plan、scrcpy 参数/版本/预检、输入映射、面板启动停止和关闭 | service 单元 + 轻量 UI |
| `tests/test_file_explorer_service.py` | `ls` 解析、安全文件名、权限模式、命令构建 | 纯单元测试 |
| `tests/test_runtime_tools.py` | frozen/开发/onedir 工具路径、ADB 解析优先级 | 纯单元测试 |

README 引用的 `tests/test_performance_services.py` 当前不存在；旧性能测试已删除或合并，当前 MobilePerf 相关测试集中在 `test_model_execution.py`。

## 执行命令

实际验证过：

```powershell
py -3.11 -m pytest --collect-only -q
py -3.11 -m pytest -q
```

只跑无 Qt 纯逻辑的快速子集可使用 pytest 的文件选择能力，但仓库没有定义正式 fast marker；在 CI/提交前仍应执行完整命令。

## 覆盖分层

### 单元测试

- File Explorer：路径、quote、`ls -l` 变体、symlink、chmod 和命令契约。
- Remote：参数构建、FPS 解析、尺寸缓存、按键/滑动/旋转映射、窗口聚焦。
- 工具：ADB target、资源/运行时路径、ZIP 安全解压。
- parsers：设备列表、getprop、labeled sections、前台包名、APK 信息、包列表。
- MobilePerf：配置生成、事件比例/事件数、报告 sheet 名、停止文件、结果定位。

### 组件与接口测试

- `CommandRunner`/`ProcessRunner` 的返回、替换、停止、流参数和全局清理。
- Controller signal map、handler、批次更新、shutdown 和异步分派。
- DeviceStore/AppSettings 旧文件迁移。
- ScrcpyService 与 RemotePanel 的 service 边界。
- MainFrame 的延后启动、扫描 debounce、对话框复用和关闭路径。

### UI 测试

当前是轻量 Qt 行为测试，不是端到端自动化：主题切换、字体/图标、按钮状态、对话框 close cleanup、截图导航、App Manager 可见详情批次、Performance Launcher 表单/日志/状态等。

没有 Playwright/Selenium/Appium/QtBot 的完整用户路径测试，也没有截图对比。

### 集成测试

- 当前没有连接真实 ADB server/device 的自动化集成测试。
- 没有真实 scrcpy、aapt、Java、临时邮箱 API 或 PyInstaller 三平台运行集成测试。
- CI 的 Windows packaged self-check 是打包冒烟测试，但不启动 GUI、不连接设备。

### 性能测试

项目本身采集设备性能，但没有对 ADBLab UI/worker 的基准、负载、内存泄漏或长时间稳定性自动测试。

## Mock 机制

- pytest `monkeypatch` 替换 subprocess、路径解析、设置和 platform/frozen 状态。
- fake process 实现 `poll/terminate/kill/wait/stdout` 等协议，验证 ProcessRunner 和 MobilePerfRunner。
- `tmp_path` 隔离 JSON/YAML/截图/报告/临时配置。
- Qt 测试尽量直接调用方法并替换 widget/service，避免启动真实外部进程。
- 测试工作流 YAML 的关键文本/结构，防止打包模式和发布资产回归。

测试不得读取或断言 `core/mail/mail.yaml` 中的真实值；邮件测试应使用内存构造的匿名假数据和 mock HTTP。

## 当前覆盖缺口

1. 临时邮箱没有专门测试：timeout、重试、脱敏、配置缺失和打包路径均无覆盖。
2. DeviceStore 并发保存/崩溃原子性无测试。
3. AppSettings 动态 `scrcpy_*` 重启加载无测试；按当前实现预计失败。
4. Monkey 的 CommandRunner timeout 结果与外层异常处理不匹配，现有“重复超时失败”测试使用的 fake 语义没有覆盖真实 CommandRunner 行为。
5. AppManagerWorker 未覆盖 backup pull、restore install、permission command 失败后的 UI/operation result。
6. Controller 的重叠同名批次、并发截图/录屏和 `_pending_ops` 清理无压力测试。
7. Android 多版本/厂商 ROM 的 dumpsys、top、SurfaceFlinger、bugreport 输出变体无实机矩阵。
8. MobilePerf 多线程停止、报告完整性、长时间运行、断线重连和 `os._exit` 前落盘无集成测试。
9. 非 Windows scrcpy/ADB 和 macOS/Linux PyInstaller 产物只有构建/自检，没有真实功能验证。
10. CI 权限、第三方 action 固定和 Release 删除策略没有安全策略测试。
11. MainFrame 未显式 LogService shutdown、全局 QRunnable 未等待的关机边界无长任务测试。
12. 邮件、设备日志、bugreport、heapdump 的敏感信息处理无安全测试。

## 推荐新增测试

按优先级：

1. `test_email_service.py`：全 HTTP mock、固定 timeout、日志脱敏、缺配置、损坏 YAML、不可写用户目录。
2. `test_settings_persistence.py`：进程重建后保留 `scrcpy_*`，并验证未知键/schema 迁移策略。
3. `test_device_store_concurrency.py`：并发 upsert/save、故障注入、原子替换和 YAML 可恢复性。
4. Monkey 真实语义测试：让 CommandRunner 返回 `timed_out=True`，验证连续超时终止而不是捕获异常。
5. AppManagerWorker 错误传播表驱动测试：每个 ADB 步骤失败都不能发成功状态。
6. Controller operation-id 测试：两次并发截图、两批安装、两台设备录屏互不覆盖。
7. 可选硬件集成 job：至少一台测试设备，覆盖连接、包列表、截图、logcat、Remote 预检、5 分钟 MobilePerf。
8. PyInstaller Windows 打包测试加入 mail feature capability check；macOS/Linux 加 scrcpy 缺失的明确降级测试。

## 提交前门禁

最低门禁：

```powershell
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
git diff --check
```

若修改 PyInstaller/资源/入口，再执行 spec 构建和打包后 self-check。若修改 ADB 命令、Remote 或 MobilePerf，除单测外应在授权测试设备上执行最小实机验证，并确保日志不含真实敏感值。
