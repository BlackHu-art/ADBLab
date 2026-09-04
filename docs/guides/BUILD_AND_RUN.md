# 构建与运行

本页只记录当前可执行的安装、运行、检查和构建方式。所有命令默认在项目根目录执行。

## 环境要求

| 项目 | 要求/状态 | 依据 |
| --- | --- | --- |
| Python | 3.11 为 README 与 CI 标准版本 | `README.md`、`Build-exe.yaml` |
| 语法兼容目标 | 静态检查与格式配置目标为 Python 3.10 | `ruff.toml`、`pyproject.toml` |
| 主平台 | Windows；精确版本兼容矩阵待确认 | README；Windows 内置 adb/scrcpy；CI 未覆盖 OS 版本矩阵 |
| GUI | PySide6；精确版本见依赖清单 | `requirements.txt` |
| ADB/scrcpy | Windows 内置；scrcpy 在非 Windows 走 PATH；ADB 解析器已按平台门控（Windows 用内置 adb.exe、非 Windows 走 PATH） | `utils/adb_resolver.py`、`services/remote/scrcpy_service.py` |
| 可选工具 | aapt 用于 APK 解析；Java 用于 chkbugreport JAR | `models/adb_app.py`、`models/adb_testing.py` |

## 安装

仓库内开发环境统一命名为 `.venv`。在 Windows PowerShell 中创建环境并安装完整开发工具链：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

依赖按用途逐层包含：

- `requirements.txt`：PySide6、PyYAML、psutil 等应用运行依赖。
- `requirements-build.txt`：包含运行依赖，并增加 PyInstaller。
- `requirements-dev.txt`：包含构建依赖，并增加 pytest、Ruff、coverage、pytest-cov、
  pytest-xdist、pre-commit 和 pyright。

只运行源码时可以改装 `requirements.txt`；执行本地打包时安装 `requirements-build.txt`。开发、
测试和提交前检查统一安装 `requirements-dev.txt`。项目没有根级 `setup.py`/`setup.cfg`、
Poetry、PDM 或 npm 构建入口。

虚拟环境提示：若 venv 由 `uv venv`（未加 `--seed`）等工具创建，环境内可能没有 pip 模块，
PyCharm 等 IDE 执行 `pip install -r requirements.txt` 时会报 `No module named pip`。此时运行
`.venv\Scripts\python.exe -m ensurepip --upgrade` 补种 pip 即可。

## 配置

- 不需要在仓库内创建普通运行配置。首次读取后，AppSettings 会把旧 `resources/app_settings.json` 迁移到用户配置目录。
- Windows 用户数据根默认是 `%LOCALAPPDATA%\ADBLab`；具体由 `utils/user_data.py` 决定。
- 默认保存目录由 `AppSettings.save_directory` 返回；未配置或目录不存在时使用用户主目录下 `ADBLab`。
- ADB 解析器已按平台门控：Windows 优先内置 `scrcpy-win64/adb.exe`，不存在时回退
  PATH；非 Windows 直接解析 PATH 中的 adb，避免把仓库内 Windows PE 当成 adb 执行。
- Remote 的非 Windows scrcpy 必须由 PATH 提供。
- Remote 的 `scrcpy_*` 表单键通过 `core/settings_manager.py::SCRCPY_SETTING_DEFAULTS` 白名单
  纳入 `DEFAULTS`，可跨会话保存与恢复；主应用不再读取任何外部服务配置。

## 启动

GUI 启动命令来自 README，并由 `main.py` 入口确认：

```powershell
.\.venv\Scripts\python.exe main.py
```

内部/诊断子模式：

```powershell
.\.venv\Scripts\python.exe main.py --self-check packaging
.\.venv\Scripts\python.exe main.py --mobileperf-worker --config <由 MobilePerfRunner 生成的配置路径>
```

第二条是内部 worker 入口，正常用户应通过 Workspace 的 System/Performance 内嵌页启动，不应手写含真实设备/包信息的配置并提交到仓库。

## 测试与检查

日常修复按 [TESTING_GUIDE 的增量验证策略](TESTING_GUIDE.md#增量验证策略) 选择直接和受影响模块
测试；发布验收或人工质量验收使用的唯一完整命令清单见
[完整门禁命令](TESTING_GUIDE.md#完整门禁命令)。dev 推送 main 本身不触发本地全量测试，
`pytest --collect-only` 只用于发现和选择测试。

`compileall` 与 Ruff、测试导入和 Pyright 的职责重复，还会生成 `__pycache__`，不属于默认门禁；
只有排查明确的解释器编译问题时才对具体目标临时运行。`git diff --check` 应在本次修改全部完成后执行。

Ruff 的规则、排除项和逐文件例外只以 `ruff.toml` 为准。

## 本地 PyInstaller 构建

README 提供的 Windows spec 构建命令：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller ADBLab.spec --noconfirm --clean
& .\dist\ADBLab\ADBLab.exe --self-check packaging
```

`ADBLab.spec`：

- 入口为 `main.py`。
- 通过白名单收集图标、迁移种子、Bugreport JAR、二维码、第三方许可、`icon.ico` 和
  `scrcpy-win64/`，不把旧演示图或无关文档带入产物。
- 通过 hidden imports 收集全部 `mobileperf` 子模块，不再把 `mobileperf/` 源码目录作为 data
  重复打包；运行配置由 `MobilePerfRunner` 临时生成。
- 生成 windowed、onedir 的 `ADBLab`。

完整 PyInstaller 构建会创建 `build/` 和 `dist/`；仅修改源码或文档时可先运行 packaging
self-check，修改 PyInstaller、资源收集或入口时必须额外验证完整产物。

## CI/CD

### Build 工作流

`.github/workflows/Build-exe.yaml` 在 `main` push 或手动触发时：

1. 从 `utils.app_metadata.APP_RELEASE_TAG` 读取版本。
2. 使用 Python 3.11 安装 `requirements-build.txt`（包含运行依赖和 PyInstaller）。
3. Windows 额外安装 `requirements-dev.txt`，运行 `python -m ruff check .` 和
   `python -m pyright`；编译发布工作流不执行 pytest。macOS/Linux 运行 source packaging self-check。
4. PyInstaller 构建 Windows onedir、macOS/Linux onefile。
5. Windows 运行打包后 self-check。
6. 压缩并上传三平台制品。
7. Release job 单独使用 `contents: write`；现存同版本 Release 或远端 tag 会使发布失败，防止直接
   覆盖。发布完成后执行 "Retain latest 5 version tags"，删除超出最新 5 个的旧版本 tag 及其
   Release；被保留策略删除的历史版本不再受“存在性检查”保护，但仓库版本规则仍禁止复用版本号。

工作流默认权限为 `contents: read`，使用的第三方 Actions 固定到已核验的 40 字符 commit SHA。
CI 使用 PyInstaller CLI 参数而不是 `ADBLab.spec`，两套打包描述需要同时维护。

### 提交版本规则

- `utils/app_metadata.py` 是版本号唯一事实来源。
- `APP_VERSION` 仅在 dev 代码推送到 main 分支时递增一次（默认补丁 +1），本地与 dev 提交不修改版本号。
- 主版本和次版本只按明确的发布计划调整；当前值直接读取 `utils/app_metadata.py`。
- 不允许把多次推送共用一个版本，也不允许只修改 README、工作流或发布标签中的派生版本。
- 推送前应先比较上次推送时的版本，确认本次版本已递增；本地验证继续按增量策略选择，推送 main
  本身不触发本地全量测试。发布验收按完整门禁执行；CI Build 只执行静态检查、打包和产物自检。

### Auto-Clean 工作流

`.github/workflows/Auto-Clean.yaml` 已改为手动只读的 **Retention Audit**：只列出 workflow runs
和 releases，不带 schedule、不删除 run/release/tag，权限为 `actions: read` 和 `contents: read`。
真正的保留期删除若未来需要，必须另行设计审批和保护环境。

## 调试方法

- 普通 ADB 失败：先运行 packaging self-check 确认 adb 路径，再观察主界面 LogPanel。
- 设备扫描：检查 `continuous_device_scan` 和 `device_scan_interval_ms`；扫描会在有活跃 CommandRunner 命令时跳过一次轮询。
- Remote：观察预检 warning、scrcpy stderr/FPS 状态；Windows 确认内置 scrcpy 完整，非 Windows 确认 PATH。
- MobilePerf：使用 System/Performance 内嵌页的日志与结果目录；停止会先生成 stop 文件并最多等待报告，再强制停止。
- 高并发/关闭问题：重点检查功能页 `request_dispose()`、Workspace 会话 registry、TaskSupervisor、
  `ProcessRunner` 全局进程表和 QThread 是否仍运行；瞬态表单再单独检查 `closeEvent`。

## 常见问题

| 问题 | 已确认原因/处理 |
| --- | --- |
| 找不到设备 | ADB 不可用、设备未授权/offline、网络 target 不完整；连接目标必须含 port |
| APK 信息解析失败 | `aapt` 不在 PATH 或 APK 不存在 |
| bugreport 转换失败 | Java 或 JAR 不可用；保留原始输出再排查 |
| 非 Windows Remote 无法启动 | CI 产物不内置 scrcpy，需系统提供 |
