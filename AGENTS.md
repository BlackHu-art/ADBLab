# ADBLab Codex 约定

ADBLab 是基于 PySide6 的 Android 设备管理、测试、Remote 和 MobilePerf 桌面工具。

## 开始任务

1. 开始任务前，先读取 `docs/README.md`（知识库 MOC 入口）。
2. 根据任务类型读取对应知识文档；涉及核心逻辑时先阅读 `docs/project-knowledge/ARCHITECTURE.md`、`docs/project-knowledge/MODULE_MAP.md`、`docs/project-knowledge/BUSINESS_FLOW.md` 和现有测试。
3. 修改核心逻辑时，先追踪入口、调用链、失败路径、线程/进程清理和现有测试。

## 代码与命令

- Python 3.11 是 README/CI 标准；Black/Ruff 行宽 100，语法目标 py310。
- 短命令优先走 `CommandRunner`，长进程走 `ProcessRunner`；设备 shell 动态值必须校验/quote。
- PySide6 后台任务不得阻塞 UI；窗口关闭时断开信号并停止/等待 worker 和外部进程。
- 运行时可写数据使用 `utils/user_data.py`，不要写 PyInstaller 资源/安装目录。
- 解压外部 ZIP 必须使用 `utils.archive.safe_extract_zip()`。
- 应用版本只在 `utils/app_metadata.py` 修改。
- `APP_VERSION` 仅在推送到远端仓库时递增一次（默认补丁 +1），本地提交不修改版本号；
  主版本或次版本仅按用户要求或发布计划调整。当前基线：3.2.0。

常用门禁：

```powershell
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
git diff --check
```

## 禁止与安全

- 不修改或提交 `.git/`、`.idea/`、缓存、日志、`resources/icons/`、`scrcpy-win64-v3.3.1/`、`mobileperf/extlib/` 和平台二进制，除非任务明确要求且已确认来源。
- 不得提交或在文档/日志中复制密钥、密码、Token、私有证书、邮件正文/验证码或真实设备唯一标识；疑似泄露只记录文件位置和风险类型。
- 危险 ADB、文件删除、应用清除、进程终止和发布删除操作必须明确校验目标与失败结果。
- 不得把推测内容写成确定事实；无法从代码或验证确认时标记“待确认”。

## 文档与提交前检查

- 修改架构、接口、数据模型/存储、配置键、外部依赖或主要业务流程后，必须同步更新 `docs/project-knowledge/`；操作命令、门禁或风格规范变化同步 `docs/guides/`；新增决策写入 `docs/architecture/adr/`。
- 推送到远端前确认 `utils/app_metadata.py` 中的 `APP_VERSION` 相对上次推送已递增（默认补丁 +1），且本次没有复用历史版本；本地提交不修改版本号。
- 提交前确认测试通过、打包自检通过、`git diff --check` 无错误、没有意外生成文件和敏感数据。
- 修改构建/资源收集时，额外验证 PyInstaller 产物；修改 ADB/Remote/MobilePerf 时补对应单测并在授权设备上做最小实机验证。
