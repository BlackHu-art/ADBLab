# API 与命令边界

## 入站 API 结论

当前项目不存在对外提供的 HTTP/REST/WebSocket/RPC API，也没有 Web server、路由表、端口监听器、消息消费者或鉴权中间件。应用入口只有桌面 GUI 和两个本地 CLI 子模式：

| 类型 | 入口 | 参数 | 输出/作用 | 鉴权 | 测试 |
| --- | --- | --- | --- | --- | --- |
| GUI | `main.py` 无子命令 | Qt/用户输入 | 启动 MainFrame | 依赖本机用户和 ADB 授权 | `test_model_execution.py` 部分覆盖 |
| MobilePerf worker | `main.py --mobileperf-worker --config <path>` | config 路径 | 运行采集子进程 | 无应用级鉴权 | runner/startup tests |
| 打包自检 | `main.py --self-check packaging` | 固定 target | 检查导入、资源、工具和用户目录 | 无 | CI + 实际验证 |

因此本文件的 HTTP 表描述的是**应用调用的外部 API**，不是 ADBLab 对外提供的 API。

## 外部临时邮箱 HTTP API

统一基址定义在 `core/mail/email_service.py::EmailService.BASE_URL`。以下信息只记录路径和数据类型，不记录任何请求签名、Token、指纹值、账号或邮件内容。

| 方法 | 路径 | 入口代码 | 请求参数 | 响应 | 鉴权/请求材料 | 核心调用链 | 测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| POST | `/rand_account` | `EmailService.get_random_email()` | 空 JSON | 随机临时邮箱账号对象 | 用户域签名配置；内存指纹 | task → get_random_email → 内存状态 | `test_email_service.py` |
| POST | `/list` | `EmailService.get_email_list()` | 当前账号与分页/查询类载荷 | 邮件摘要列表 | 用户域签名配置 | fetch_and_process_email → list | `test_email_service.py` |
| POST | `/detail` | `EmailService.get_email_detail()` | 邮件标识与账号上下文 | 邮件详情/正文 | 用户域签名配置 | fetch_and_process_email → detail → extract code | `test_email_service.py` |

边界约束：运行时不读取源码树 `mail.yaml`，配置来自用户目录或显式环境注入；所有 POST 强制
connect/read timeout；日志不记录 payload、response、账号、正文、验证码、指纹或签名。仓库历史
跟踪配置的轮换/清理，以及服务方协议、授权、数据处理条款和限流策略仍待所有者确认。

## ADB 命令接口地图

ADB 是项目实际最重要的外部操作 API。参数通常以数组传给 subprocess，设备 shell 内的复合命令由 service/model 构造。

| 能力组 | 主要入口 | 典型外部接口 | 输入 | 输出 | 校验/保护 | 测试 |
| --- | --- | --- | --- | --- | --- | --- |
| 设备发现/连接 | `ADBDevice` | `adb devices/connect/disconnect/pair/reboot` | device/target | 文本、设备列表 | connect target 有 IPv4/IPv6+port 校验 | 有 |
| 设备属性 | `ADBDevice.get_device_info_async` | `getprop`、`dumpsys`、`wm` | device | 属性字典 | 批量 labeled section 解析 | 有 |
| 应用生命周期 | `ADBApp`、`ADBSystemMixin` | `pm`、`am`、`monkey` | package/APK/action | CommandResult | package 校验不统一；批量 worker 有部分校验 | 有，实机缺 |
| 输入控制 | `ADBAdvanced`、`ADBBridge` | `input tap/swipe/text/keyevent` | 坐标、文本、key code | 结果或乐观布尔 | 低延迟持久 shell；设备执行未回读 | 有 |
| 文件与传输 | File Explorer/model | `shell ls/cp/mv/rm/chmod`、`push/pull` | 设备/本地路径 | 列表/文件/状态 | 安全文件名、shell quote；删除确认 | 有 |
| 网络/端口 | `ADBNetworkMixin`、Controller file mixin | `forward/reverse/tcpip/pair/ping/netstat` | host/device port | CommandResult | connect target 校验；其他端口校验不完整 | 部分 |
| 日志与诊断 | `ADBTesting`、LiveLogcat | `logcat`、`bugreport`、ANR pull | package/tag/path | 流、文件、目录 | ZIP 安全解压 | 有 |
| 截图/录屏 | `ADBTesting`、`ADBAdvanced` | `exec-out screencap`、`screenrecord` | device/path/time | PNG/MP4 | PNG 签名检查和回退 | 有 |
| 性能采集 | MobilePerf monitor | `top`、`dumpsys meminfo`、SurfaceFlinger、`/proc` | package/device/interval | CSV 采样 | 移植内核校验较弱、命令实现独立 | 部分 |
| 任意 shell/intent | SystemPanel/ADBSystemMixin | `adb shell ...`、`am start/broadcast` | 用户文本 | CommandResult | 已知高影响入口接入统一危险确认；参数校验仍不完整 | 部分 |

## scrcpy 进程接口

`models/remote/scrcpy_args.py` 将 `ScrcpyConfig` 转为参数数组，`ScrcpyService.build_launch_plan()` 先检查版本、ADB 预检和可选编码器，再由 `ProcessRunner.start()` 启动。stderr 用于状态/FPS 解析。Windows 使用内置可执行文件，非 Windows 使用 PATH；没有网络服务端暴露。

## 文件与进程接口安全约定

- 主应用短命令优先使用参数数组，不启用宿主 shell。
- 设备 shell 复合命令必须在 service/model 层集中构造并对动态路径使用 quote。
- 外部 ZIP 必须用 `utils.archive.safe_extract_zip()`，防止目录穿越。
- 长进程应注册到 ProcessRunner；带 UI 生命周期的复合 worker/process task 还应注册到
  TaskSupervisor。只有确认退出后才能移除 tracking，timeout 必须保留 residual snapshot。
- MobilePerf 内核仍存在 `shell=True` 和直接 Popen 的遗留例外，详见 [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md)。
