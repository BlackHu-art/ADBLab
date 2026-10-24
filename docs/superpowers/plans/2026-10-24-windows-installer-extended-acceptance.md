# Windows 安装生命周期补充验收

日期：2026-10-24。用户已授权继续补齐剩余标准用户、真实旧应用升级和故障注入，直接修复并验证。
本计划延续[已批准设计](../specs/2026-10-24-windows-installer-design.md)与
[首轮验收记录](2026-10-24-windows-installer.md)，不改变业务、版本或数据格式。

## 边界与选择

- 标准账户仅在一次性 GitHub hosted Windows runner 创建，明确核验 SID、未提升且不属于
  Administrators 的令牌、加载的用户 profile、HKCU/HKU 与快捷方式。不得使用开发机账户或
  以过滤的管理员令牌代替；父子进程不传递密码文本，环境按白名单重建。
- 官方 v3.3.1 仅有 ZIP，没有历史正式 setup。固定官方 ZIP 的字节数、SHA256 与 tag，使用
  原始应用载荷封装验收专用旧安装器，运行旧应用后升级到当前正式安装器。证据只能称
  “真实旧应用载荷跨版本升级”，不能声称测试了不存在的历史正式安装器。
- 故障测试采用测试专用编译宏和阶段屏障；生产入口编译时拒绝故障宏。对实际安装事件进行
  进程中断、文件共享冲突、受管文件修改和安装中启动验证。它们不等同电源中断、磁盘硬件
  损坏或所有交互取消，不承诺每个失败点均原子回滚。
- 优先接口：在现有 Build workflow 增加 `codex/installer-acceptance-*` 推送触发；此类分支
  固定只构建、不发布。仅 main push 保持原自动发布规则；手动发布仍只允许 main。
  用本次验收分支推送启动新提交检查，读取状态、日志和产物继续使用 GitHub 接口。

## 实施与验收

1. 标准账户启动器与身份检查：仅本机解析/替身测试；真实建号和安装仅在 CI。
   所有子进程失败、身份错误、超时与清理失败必须传播；不回退管理员运行。
2. 固定旧版载荷：验证下载完整性与安全解压，隔离 staging 编译，不修改生产版本接口；
   验证旧/新冻结入口、清单与用户数据/未知文件保留。
3. 故障矩阵：元数据发布前后、载荷复制中、退役清理、current/ready 提交窗口与卸载删除/
   后置清理；检查失败状态、锁释放、严格恢复目标及恢复后完整摘要。
4. 集成 CLI：标准用户下运行基础验收、故障矩阵、真实旧载荷升级、默认位置及桌面快捷方式
   安装；屏障期间启动真实应用应拒绝，完成后恢复正常；正式修复替换测试卸载器后卸载。
5. CI 接线、直接回归与独立审阅；提交推送本轮修改，按失败日志修复，直至配置场景实际通过。
   最后更新现状文档与已执行/未执行范围，不用本地 helper 通过代替真实事件。

## 文件归属与验证

- `scripts/windows_installer/standard_user.py`、PowerShell 启动器与只读快捷方式探针：账户和
  系统集成验收；对应 `tests/test_windows_installer_standard_user.py`。
- `tests/fixtures/windows_installer/legacy_*`：固定旧版实验；对应 `tests/test_windows_installer_legacy.py`。
- `tests/fixtures/windows_installer/fault_*` 与受条件保护的 ISS 屏障：故障矩阵；
  对应 `tests/test_windows_installer_faults.py`。
- `scripts/check_windows_installer_extended.py`、Build workflow：串联与失败门禁；
  对应扩展验收及既有 CI 契约测试。

基线：既有验收器、升级夹具、CI 契约集合 **108 passed**（12.58 秒），一个既有 SciPy 弃用警告。
修改按各自直接测试验证，集成后再运行安装器关联集合、静态/文档门禁；真实构建与生命周期
由隔离 CI 执行。当前状态：首次远程功能场景通过，但 PowerShell 收尾失败；已修复并准备复验，
不能将首次作业记为成功。

## 本地预检记录

- 扩展入口、标准账户、旧载荷和 CI 契约组合 **139 passed**；关联的安装协议、manifest、
  builder、基础验收、Inno 准备与产物检查 **240 passed、1 skipped**。跳过项是 Windows
  不直接执行 shebang 程序的既有平台用例；CI 契约运行时临时加入已安装 Git Bash 的目录，
  不修改全局 PATH。组合中的一个 SciPy 弃用警告来自既有依赖。
- 源码 `main.py --self-check packaging` 通过；受影响 Python 路径 Pyright 与全仓 Ruff 通过。
- 官方旧资产 `ADBLab-win-x64-v3.3.1.zip` 实下载后为 **158029557 bytes**，SHA256 为
  `fd2cd65e1c7f756eb926b52bcd0d3ba4a7f5cb16050dba8b2bfbe2b3cd661a36`。真实旧载荷安全解压、
  staging 和测试模板编译通过，未在开发机安装。由于本机默认 urllib TLS 握手失败，本地纯编译
  验证以已通过同一摘要校验的 ZIP 流代替下载传输；远程仍需验证实际下载及安装。
- 独立审阅发现屏障放行后卡住时，单纯重写 crash 动作不能停止真实引擎。修复采用精确引擎
  句柄和本轮专属 Windows Job；命令在启动器加入 Job 后才放行，失败时终止并确认后代退出。
  不按名称结束进程。故障直接测试 **38 passed**，与 manifest 组合 **84 passed**。
  独立复审的原生清理/摘要节点 **10 passed**，额外模拟 Job 加入失败确认目标没有启动、
  gate 已退出且错误传播；原问题已关闭，未发现新增阻断。成功摘要同时写入 Actions 日志，
  便于接口核对实际阶段证据。

## 首次远程验收与收尾修复

- 提交 `2868777bf423a4d12b9b40d2dc290f4f5420e687` 通过专用分支 push 启动
  [运行 40082325208](https://github.com/BlackHu-art/ADBLab/actions/runs/40082325208)。三个非 Windows
  平台成功；Windows 静态门禁、非 UI 测试（**3986 passed、72 skipped、4487 deselected**）、
  冻结探针、setup 构建和基础安装验收成功，Release 跳过。
- Windows job `120838273737` 日志确认标准身份、标准账户基础生命周期、18 个故障事件、
  真实 3.3.1 旧载荷升级、默认位置/HKCU/HKU/快捷方式、实际安装中启动互斥、正式修复后
  卸载及用户数据保留均输出 PASS。该次 CI 旧新清单差集为 **0 个退役文件**，不能宣称其执行了
  真实旧载荷退役删除；退役路径清理由独立 A/B/C fixture 和故障 fixture 实际覆盖。
- 子进程完成后，PowerShell 的两个裸 `GetAwaiter().GetResult()` 把 `VoidTaskResult` 输出到
  成功流，与真实退出码组合为 `Object[]`，最终 `[int]$exitCode` 转换失败。作业失败并阻断
  Windows 压缩、上传，未发布产品。修复仅为两处显式 `[void]`，保留异步异常传播。
- 新增真实 `MemoryStream.CopyToAsync` 的成功/失败退出码回归，先 **2 failed** 后通过；
  标准账户、扩展入口与 CI 契约组合 **110 passed**，一个既有 SciPy 弃用警告。独立复审确认
  修复和新回归通过，额外故障 Task 探针确认异步错误仍会抛出。四项本地静态/文档门禁通过。
