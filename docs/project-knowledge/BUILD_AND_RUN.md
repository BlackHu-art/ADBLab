# 构建与运行

本页只记录能从仓库配置得到验证，或在 2026-07-23 实际执行过的命令。所有命令默认在项目根目录执行。

## 环境要求

| 项目 | 要求/状态 | 依据 |
| --- | --- | --- |
| Python | 3.11 为 README 与 CI 标准版本 | `README.md`、`Build-exe.yaml` |
| 语法兼容目标 | Black/Ruff 配置为 Python 3.10 | `pyproject.toml` |
| 主平台 | Windows 10/11 | README；Windows 内置 adb/scrcpy |
| GUI | PySide6 6.8.1.1 | `requirements.txt` |
| ADB/scrcpy | Windows 已内置；非 Windows 从 PATH 解析 | `utils/adb_resolver.py`、`models/remote/scrcpy_service.py` |
| 可选工具 | aapt 用于 APK 解析；Java 用于 chkbugreport JAR | `models/adb_app.py`、`models/adb_testing.py` |

## 安装

仓库 README 的安装命令：

```powershell
py -3.11 -m pip install -r requirements.txt
```

pytest 不在 `requirements.txt`，CI 使用：

```powershell
py -3.11 -m pip install pytest
```

项目没有 `setup.py`/`setup.cfg`/Poetry/PDM/uv/npm 构建入口，也没有单独的开发依赖文件。是否要求虚拟环境由团队待确认；仓库没有给出正式命令，本文不自行补写。

## 配置

- 不需要在仓库内创建普通运行配置。首次读取后，AppSettings 会把旧 `resources/app_settings.json` 迁移到用户配置目录。
- Windows 用户数据根默认是 `%LOCALAPPDATA%\ADBLab`；具体由 `utils/user_data.py` 决定。
- 默认保存目录由 `AppSettings.save_directory` 返回；未配置或目录不存在时使用用户主目录下 `ADBLab`。
- ADB 解析优先级为 Windows 内置 `scrcpy-win64-v3.3.1/adb.exe`，再到 PATH 中的 adb。
- Remote 的非 Windows scrcpy 必须由 PATH 提供。
- 临时邮箱只读取用户配置目录的 `mail.yaml`，也可通过 `ADBLAB_MAIL_CONFIG` 指定用户受控文件；
  签名材料可由进程环境注入。不要把真实凭据写入仓库配置或日志。
- 历史跟踪的 `core/mail/mail.yaml` 仍需仓库所有者轮换材料、停止跟踪并审查 Git 历史；
  不应复制或扩散其内容。

## 启动

GUI 启动命令来自 README，并由 `main.py` 入口确认：

```powershell
py -3.11 main.py
```

内部/诊断子模式：

```powershell
py -3.11 main.py --self-check packaging
py -3.11 main.py --mobileperf-worker --config <由 MobilePerfRunner 生成的配置路径>
```

第二条是内部 worker 入口，正常用户应通过 Performance Launcher 启动，不应手写含真实设备/包信息的配置并提交到仓库。

## 测试与检查

本次实际执行并通过：

```powershell
py -3.11 -m pytest --collect-only -q
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
```

结果：229 tests collected；229 passed in 2.83s；packaging self-check 的 PySide6、Requests、MobilePerf、icon/resources、Windows 内置 adb/scrcpy 和用户数据目录检查全部通过。

仓库 README 还建议：

```powershell
py -3.11 -m compileall -q main.py utils models mobileperf gui controllers core
git diff --check
```

`compileall` 会生成 `__pycache__`，本次知识库任务遵守“只创建文档”，因此未执行；`git diff --check` 应在文档全部生成后执行。

Ruff/Black 配置存在但依赖未声明、CI 未调用。若本机已经安装，可从 `pyproject.toml` 推导工具会使用行宽 100 和 py310 目标；仓库没有给出团队认可的固定执行命令，因此本页不把它们列为已验证门禁。

## 本地 PyInstaller 构建

README 提供的 Windows spec 构建命令：

```powershell
py -3.11 -m PyInstaller ADBLab.spec --noconfirm --clean
& .\dist\ADBLab\ADBLab.exe --self-check packaging
```

`ADBLab.spec`：

- 入口为 `main.py`。
- 收集 `resources/`、`icon.ico`、`scrcpy-win64-v3.3.1/`、`mobileperf/`。
- 收集全部 `mobileperf` 子模块。
- 生成 windowed、onedir 的 `ADBLab`。
- 不收集 `core/mail/mail.yaml`；临时邮箱按设计从用户域配置或显式环境注入读取。

本次未实际执行完整 PyInstaller 构建；源码模式 packaging self-check 已通过。完整构建会创建 `build/` 和 `dist/`，不符合本次只创建文档的范围。

## CI/CD

### Build 工作流

`.github/workflows/Build-exe.yaml` 在 `main` push 或手动触发时：

1. 从 `utils.app_metadata.APP_RELEASE_TAG` 读取版本。
2. 使用 Python 3.11 安装 requirements。
3. Windows 运行 `python -m pytest -q`；macOS/Linux 只运行 source packaging self-check。
4. PyInstaller 构建 Windows onedir、macOS/Linux onefile。
5. Windows 运行打包后 self-check。
6. 压缩并上传三平台制品。
7. Release job 单独使用 `contents: write`；若同版本 Release 或远端 tag 已存在则失败，保持发布不可变。

工作流默认权限为 `contents: read`，使用的第三方 Actions 固定到已核验的 40 字符 commit SHA。
CI 使用 PyInstaller CLI 参数而不是 `ADBLab.spec`，两套打包描述需要同时维护。

### 提交版本规则

- `utils/app_metadata.py` 是版本号唯一事实来源。
- 每个 Git 提交必须包含一次 `APP_VERSION` 更新，并使用未出现过的新版本号。
- 未指定发布级别时递增补丁版本；主版本和次版本只按明确的发布计划调整。
- 不允许把多个提交共用一个版本，也不允许只修改 README、工作流或发布标签中的派生版本。
- 创建提交前应先比较 `HEAD` 中的版本，确认本次版本已递增，再执行测试、打包自检和差异检查。

### Auto-Clean 工作流

`.github/workflows/Auto-Clean.yaml` 已改为手动只读的 **Retention Audit**：只列出 workflow runs
和 releases，不带 schedule、不删除 run/release/tag，权限为 `actions: read` 和 `contents: read`。
真正的保留期删除若未来需要，必须另行设计审批和保护环境。

## 调试方法

- 普通 ADB 失败：先运行 packaging self-check 确认 adb 路径，再观察主界面 LogPanel。
- 设备扫描：检查 `continuous_device_scan` 和 `device_scan_interval_ms`；扫描会在有活跃 CommandRunner 命令时跳过一次轮询。
- Remote：观察预检 warning、scrcpy stderr/FPS 状态；Windows 确认内置 scrcpy 完整，非 Windows 确认 PATH。
- MobilePerf：使用 Performance Launcher 的日志与结果目录；停止会先生成 stop 文件并最多等待报告，再强制停止。
- 高并发/关闭问题：重点检查对话框 `closeEvent`、`ProcessRunner` 全局进程表、QThread 是否仍运行。

## 常见问题

| 问题 | 已确认原因/处理 |
| --- | --- |
| 找不到设备 | ADB 不可用、设备未授权/offline、网络 target 不完整；连接目标必须含 port |
| APK 信息解析失败 | `aapt` 不在 PATH 或 APK 不存在 |
| bugreport 转换失败 | Java 或 JAR 不可用；保留原始输出再排查 |
| 非 Windows Remote 无法启动 | CI 产物不内置 scrcpy，需系统提供 |
| Remote 设置重启后恢复默认 | `scrcpy_*` 不在 AppSettings DEFAULTS 白名单，当前很可能无法载入，待修复验证 |
| 打包后临时邮箱未配置 | 在用户配置目录创建受控 `mail.yaml` 或使用显式环境注入；源码树配置不会被读取 |
| README 中找不到 Performance 旧目录 | README 仍引用已删除的旧性能模块；当前实现是 `performance_launcher.py` + `models/mobileperf/` + `mobileperf/` |
