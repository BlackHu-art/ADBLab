---
status: current
last_verified: 2026-09-04
related: [MODULE_MAP.md, DATA_FLOW.md, ARCHITECTURE.md]
---

# 主要业务流程

本页只保留用户触发、主流程、失败/取消和清理语义。模块位置见
[MODULE_MAP](MODULE_MAP.md)，数据生命周期见 [DATA_FLOW](DATA_FLOW.md)，线程与应用关闭见
[ARCHITECTURE](ARCHITECTURE.md)。

## 1. 启动、导航与设备发现

- **触发**：运行 GUI 入口；worker 和打包自检子模式不会创建主窗口。
- **主流程**：创建 QApplication、主题和 MainFrame；构建 Home、三个业务宿主页、Tasks、Logs、
  Settings 七个物理页面，Remote 归入设备与控制。主左栏以设备、应用、系统三个折叠分组组织功能
  叶节点；宽屏直接展开树，窄屏使用 qfluentwidgets 原生 Flyout，内容区不显示模块下拉框。面板内部
  AdaptiveCategoryStack 的 Pivot/ComboBox 保持隐藏。复杂功能按路由、
  设备和代次懒创建；ADB 在后台预热并按设置执行设备发现。
- **失败与恢复**：字体、字号和窗口尺寸在边界外时回退到安全值；扫描失败只标记 unavailable，
  保留最后成功设备列表，不自动重启 ADB Server。慢速元数据回调只有在设备拓扑 generation 仍匹配
  时才写入和发布。

## 2. 连接设备与读取信息

- **触发**：用户输入 ip:port/[IPv6]:port 连接，或请求刷新设备。
- **主流程**：UI 与 Controller 校验目标，ADB 执行 connect/devices/getprop 等命令，Controller
  汇总属性并写入 DeviceStore，随后更新首页和三个业务主页面的设备上下文。设备页复选项组成
  多设备批量操作目标；单设备深层功能和 Remote 使用独立的会话设备。会话候选列出全部在线设备
  并保留已有离线会话；恰好一个批量目标或仅一台在线设备时可自动选定，多个批量目标或无批量
  目标且多台在线时要求显式选择。
- **失败与恢复**：不完整目标在执行前拒绝；超时和非零退出形成失败结果；offline/unauthorized
  设备只展示可确认信息，不用空结果覆盖最近成功快照。

## 3. 应用管理与安装批次

- **触发**：安装、卸载、启停、清数据、权限、备份/恢复、批量安装或打开 App Manager。
- **主流程**：普通动作经 Controller/ADB model；App Manager 在固定设备的内嵌功能会话中用
  worker 加载列表和详情。安装批次为每次请求创建 operation 和 unit 身份，按 owner/generation
  接受结果，支持部分失败、取消和失败项重试。
- **失败与清理**：输入或目标校验失败时不启动 worker；worker 在开始前收到中止请求就不执行设备
  操作。备份先写 staging，恢复安装失败不会报告成功；晚到或错代批次结果直接丢弃。高影响动作
  当前不二次确认，安全边界依赖目标校验和真实失败传播。

## 4. Monkey、截图、录屏与诊断

- **Monkey**：校验参数后启动并跟踪进程，同时监测前台包。用户中止或连续探测失败会停止进程并
  清理日志资源；未知前台状态不按成功处理。
- **截图**：每批请求按 operation/task 隔离，校验目标、路径和 PNG artifact 后汇总。成功结果后台
  追加到 ScreenshotPage；不在该页时只显示“查看结果”提示，不抢占导航。取消会原子标记未完成
  unit，晚到回调被丢弃。
- **录屏与诊断**：录屏按批次管理启动、停止和拉取；本地视频拉取成功但远端清理失败时保留文件并
  单独报告清理错误。bugreport 解压使用安全 ZIP 边界。

## 5. Live Logcat

- **触发**：在 System 中为一台设备打开 LiveLogcatPage，可选择包过滤。
- **主流程**：worker 消费单一 logcat 流并在 producer 侧批量；包过滤周期刷新全部 PID，只发布
  当前 generation 的匹配行。切走页面暂停绘制但继续消费。
- **失败与清理**：包未运行或 PID 查询失败时 fail-closed 并重试，不退化为其他应用日志。显式
  关闭会话或应用关闭才停止进程、reader 和 PID 刷新线程；资源归零前页面保持释放屏障。

## 6. 文件浏览与传输

- **触发**：从 Devices 打开固定设备的 File Explorer，执行浏览、pull/push、编辑、复制、移动、
  删除、chmod、APK 安装或脚本操作。
- **主流程**：服务层校验名称和路径；短命令走 CommandRunner，传输走 ProcessRunner；成功后刷新
  目录。切走页面保留路径、预览和仍需继续的任务。
- **失败与清理**：未选设备显示空态，离线会话禁止新操作；非法名称、.. 和失败结果不会进入
  成功刷新。显式关闭会话中止 worker，尚未进入执行体的任务不会启动。

## 7. Remote

- **触发**：在设备与控制中进入屏幕镜像或按键与手势，为 Remote 会话选定一台设备后启动 scrcpy。
- **主流程**：Remote 使用独立于设备页批量复选的会话设备；多候选且无当前会话时先显式选择。
  预检后生成 LaunchPlan，ProcessRunner 启动 scrcpy；stderr/FPS reader 和 watchdog 更新状态，输入只
  发送给该会话设备的持久 ADB shell。已启动的 Remote 运行保持绑定原会话设备，不被后续候选刷新改向。
- **失败与清理**：无会话设备、离线会话、预检或前置设置失败都拒绝后续动作。关闭时先停止输入
  准入，再等待 executor 和 warmup producer，最后关闭持久输入会话；非 Windows 缺少 PATH scrcpy
  时明确失败。

## 8. MobilePerf

- **触发**：在 System/Performance 选择设备和包，配置采样后启动。
- **主流程**：页面生成运行配置，Runner 创建独立临时目录和子进程，双管道 reader 排空输出；
  只有退出码成功且本次生成非空报告时才显示完成。切走页面不停止采集。
- **失败与清理**：启动失败立即恢复 UI；停止先写 stop 标记并等待报告，超时后强制停止。旧报告、
  空报告或非零退出不能伪装为成功。

## 9. 任务中心

- **活动项**：只来自 OperationManager 当前快照，不代表 Monkey、录屏、MobilePerf 等全部后台工作。
- **历史项**：MainFrame 当前把兼容 operation_completed 信号写入进程内有界 TaskHistoryStore；
  应用重启后清空。
- **取消**：按钮总是调用 OperationManager.request_cancel()；MainFrame 当前只为安装批次和截图
  追加资源停止路由，其他任务是否真正停止取决于其自身执行边界。

## 10. 页面会话与应用关闭

- 主左栏功能叶节点切换概览分类时复用同一面板内容；切换深层功能只调用功能页 deactivate()，
  同一 feature/device/generation 返回时复用页面。用户
  显式关闭才执行 request_dispose()；旧代次在 worker 或进程归零前不能重激活。
- 应用关闭先封闭新任务准入，再并发广播扫描、各业务主页面、面板和 Controller 停止，并在共享
  deadline 内后台等待。单个资源登记失败不会跳过其他资源。
- finalizer 记录仍未退出的 residual、保存配置并完成窗口关闭；超时不被描述为资源已归零。
  瞬态消息/输入/短表单只结束该次交互，不创建长期页面会话。
