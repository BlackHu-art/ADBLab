# 应用动作与归档服务提取设计

日期：2026-10-24。实施、独立任务审阅及最终综合审阅均已通过。
承接本目录 preflight-notes.md、原 Qt worker 业务审计 B1 和查询服务阶段的最新工作树。
实施必须以主任务确认的查询阶段最终快照为基线，不能从 HEAD 恢复 worker。

## 目标与范围

把四个应用写动作以及备份/恢复的完整事务移至 `services/apps/actions.py`、`archives.py`。
AppManagerWorker 保留 Qt 生命周期、取消适配、operation 分派、用户准入、翻译及 Signal 发布。
查询服务的实现和用户政策不再复制；本轮不移动 worker 类/GUI 工厂、不处理文件浏览器服务。

选择完整事务加窄同步 callback：相比只提取命令构造，能单独验证发布、计数、取消和清理；
相比返回最终 DTO 再由 adapter 重放通知，保留日志/进度回调的位置以及原 try 捕获范围。
不创建通用事件总线、事务框架、依赖容器或每条通知一个事件类；也不新增 aggregate result DTO。
每个入口返回 None，业务结果由服务在原位置调用明确的通知函数，adapter 不解析日志判定成功。

## 文件、依赖与 owner

| 文件 | 责任 |
| --- | --- |
| `services/apps/actions.py`（新） | 四种完整写用例及共用 command_error；安全 token/权限校验、命令、结果判定和通知顺序 |
| `services/apps/archives.py`（新） | APK 路径获取、串行拉取、暂存压缩、原子发布；安全解压、用户复核、安装计数与终态 |
| `models/app_manager_worker.py` | 六个窄 wrapper，Qt 翻译/Signal、现有 run/_adb/_bind_current_user/取消机制；查询区保留已验收实现 |
| `tests/test_app_actions.py`、`tests/test_app_archives.py`（新） | 完整服务行为、命令、临时文件、同步回调与异常边界 |
| `tests/test_app_write_boundary.py`（新） | 阻断 Qt/GUI/models 后导入并实际 fake 执行服务 |
| 既有 restore/worker 测试的相关节点 | 真正 Signal 与现有调用接缝；仅三处归档私有依赖 patch 迁移 owner |

一个实施 owner 持有 worker，顺序完成动作、归档和 adapter 接入；完成本批再做一次独立 review。
主任务统一生产路径 Pyright、隔离数据目录的源码 packaging、自检记录与正式 docs 同步。
不改依赖、配置、版本、资源、CI、归档文件格式或 GUI 调度。包入口不聚合新服务。

actions 只运行时导入标准库、package_details.is_safe_package、现有 app_permissions.is_permission_name、
app_data_errors.clear_data_error_code。archives 使用标准库、actions.command_error、package_details
与 utils.archive.safe_extract_zip。`QueryExecutor`、`CommandResult` 只在 TYPE_CHECKING 中引用；
使用 future annotations，不引入第二个执行协议。当前 QueryExecutor 的名字虽含 Query，结构
已经准确覆盖 `_adb(*args, timeout=30, cancellable=False)`，可复用其类型而不复制实现。

## 冻结接口

以下函数全部同步；callback 不保留到返回之后，不创建线程、Timer、进程注册或 QObject。
代码使用 `from __future__ import annotations`；Callable 从 collections.abc 导入。

```python
# services/apps/actions.py
def command_error(result: CommandResult, fallback: str) -> str: ...

def modify_app(action: str, package: str, user_id: int, *, execute: QueryExecutor,
               log: Callable[[str], None], failure: Callable[[str], None],
               feedback: Callable[[str, str], None], completed: Callable[[str], None]) -> None: ...

def launch_app(package: str, user_id: int, *, execute: QueryExecutor,
               log: Callable[[str], None], failure: Callable[[str], None],
               completed: Callable[[str], None]) -> None: ...

def clear_app(package: str, user_id: int, *, execute: QueryExecutor,
              log: Callable[[str], None], failure: Callable[[str], None],
              permission_denied: Callable[[], None], completed: Callable[[str], None]) -> None: ...

def modify_permission(package: str, permission: str, action: str, user_id: int, *,
                      execute: QueryExecutor, log: Callable[[str], None],
                      failure: Callable[[str], None], completed: Callable[[str], None]) -> None: ...

# services/apps/archives.py
def backup_app(package: str, save_dir: str, user_id: int, *, execute: QueryExecutor,
               cancelled: Callable[[], bool], progress: Callable[[str, str], None],
               log: Callable[[str], None], feedback: Callable[[str, str], None],
               failure: Callable[[str], None], completed: Callable[[str], None]) -> None: ...

def restore_apps(files: Sequence[str], *, execute: QueryExecutor,
                 cancelled: Callable[[], bool], confirm_user: Callable[[], int | None],
                 log: Callable[[str], None], feedback: Callable[[str, str], None],
                 failure: Callable[[str], None], completed: Callable[[str], None]) -> None: ...
```

`command_error` 精确保留 error→output→fallback 优先级，前两者仍使用
`str(getattr(result, name, '') or '').strip()`。不把 stdout 混进优先级。
failure 通常是 worker._report_failure（先 log，再 error feedback）；feedback 是既有二参信号；
completed 是 operation_done.emit，只调用一次，自动 success feedback 仍由原 Signal 连接负责。
service 不另外发送 success feedback，不用 QThread.finished 表示业务成功。

所有动作 user_id 由已确认 run 准入提供；service 不自行探测/绑定用户，也不新增校验政策。
package 准入继续使用已提取的原 `is_safe_package`，不替换成严格 normalize_android_package。
`confirm_user` 是恢复安装前的窄边界：调用者必须依据固定的 expected user 完成复核，成功返回
同一已绑定用户，失败或取消返回 None，必要用户错误已经由该边界报告。返回 0 是合法成功，
service 必须使用 `is None` 判断，不能用 falsy 判断。

## adapter 接缝与单一用户政策

run 仍先按 queries.validate_loaded_user 校验六个写 operation（含备份/恢复），再调用
_bind_current_user。查询批次的例外和全部已验收查询逻辑不变。恢复的每次 install 前仍复核。

保留 `_adb` 原实现；写操作、pm path、pull、install 均不传 cancellable=True，也不传取消函数
给执行器，单次写已经开始后允许原执行器有界完成。四个 action 不新增 cancelled 参数或完成后
取消门禁；run 入口的预取消拦截维持，命令中途 abort 不抹去已经成功的动作结果。

worker 六个旧方法名及参数保持，只组装服务依赖。新增两个窄适配方法：

```python
def _report_clear_permission_denied(self) -> None: ...
def _restore_target_user(self) -> int | None: ...
```

前者在被调用时执行 `QCoreApplication.translate('ADBLab', CLEAR_DATA_PERMISSION_MESSAGE)`，
再发 error feedback；不在 service 调用前提前翻译。后者依次调用现有 `_bind_current_user()`，
失败返回 None，成功返回当时的 self.user_id（必要的 cast 只用于类型）；无新策略/新异常捕获。
service 每次确认成功后使用这次返回值构造 `--user`。如此保留旧实例 `_bind_current_user` patch，
也保留原来的“复核后读取 user_id”时点，而不是提前缓存一个绕过复核的值。

固定用户策略仍由 queries.bind_current_user 维护：用户变化拒绝，绝不自动改绑。若用户探测中
取消，_bind 返回 False，restore 直接返回，不额外补一条 Restore cancelled（这是当前行为）。
服务假依赖要遵守确认同一目标用户的契约；不能凭返回任意新用户来模拟允许切换。

## 四种 action 的精确行为

四个动作不引入 try/except；执行、日志、failure、feedback 或 completed callback 异常按原路径
传播。尤其不能先构造统一结果再延后读取 result/error 和通知，回调可以同步改变后续可见状态。

| 用例 | 命令与判定 | 原通知顺序 |
| --- | --- | --- |
| modify_app | disable→shell pm disable-user；enable→shell pm enable；uninstall→uninstall；force_stop→shell am force-stop，均显式 --user。无效包先拒绝，再校验动作 | 执行后先 `OK/FAIL: {action} {package}`；success 再 completed(action)；失败仅 feedback(error,command_error)，不能用 failure 重复写日志 |
| launch_app | 原 am start 参数和顺序，末尾独立 `2>&1`；非成功或 output 命中 `(?im)^Error(?:\s|:)` 都失败；Warning 可成功 | 失败用 `Failed to launch {package}: {error}` 的 failure；成功 log `Launched {package}` 再 completed('launch') |
| clear_app | 单次 shell pm clear --user；仅 !success 时检查既有 clear_data_error_code | 拒绝权限时 diagnostic 按 output,error 顺序去重连接，先完整失败 log，再 permission_denied callback；普通失败走 failure；成功 log `Cleared data: {package} — {stdout.strip()}` 再 completed('clear') |
| modify_permission | 先包名、再 grant/revoke、再 is_permission_name；原 permission 用 shlex.quote，不能收紧 Unicode/$/- 许可 | 非法权限固定中文提示；失败 `Failed to {action} permission {permission}: {error}`；成功 log `Permission {action}: {permission} — {stdout.strip() or 'OK'}` 再 completed('permissions_changed') |

无效包/动作、fallback 错误文案和四种命令的 timeout 默认 30 保持当前源码；权限拒绝不重试、
不提权、不卸载。launch 不改用 monkey，不把整个命令交给宿主 shell。

## backup 完整事务与取消位置

1. 包名不合法即 failure；progress(package,'Fetching APK paths') 后执行一次
   `execute('shell', f'pm path --user {user_id} {package}')`，不加取消。
   失败立即 failure；路径按每个非空行 replace('package:','').strip() 保留原序列、不去重。
   空路径 failure `No APK for {package}`。
2. 外层 TemporaryDirectory(prefix=f'bk_{package}_') 包含整次拉取与归档；创建后先 progress
   `Pulling N APKs`，然后串行 pull(path,tmp)，默认 timeout30，不加 cancellable。
   每条 pull 前 cancelled 为真就静默返回。即使已有 pull 失败，也要等后续 pull 完成再聚合；
   若下一条之前取消，则沿用静默退出，不另补先前失败摘要。
3. 全部 pull 返回后先聚合失败，原错误文案 `Backup failed for {package}: X/N APK pulls failed; first`。
   失败优先于紧接着的取消。只有没有失败才检查最后 pull 后取消：log `Backup aborted for ...`，
   feedback('info',`Backup aborted: ...`)，不查数量、不压缩、不成功。
4. os.walk(tmp) 递归计数 `name.lower().endswith('.apk')`，数量必须等于原 paths 长度。
   不改为按 basename 去重或只查顶层；数量不符按原 expected/found failure。
5. 在原 try 内创建 save_dir、final_path=backup_{package}.zip 和位于 save_dir 的
   TemporaryDirectory(prefix='.adblab_backup_')；shutil.make_archive(archive_base,'zip',tmp)。
   压缩结束后再次检查 cancelled，发上述 log/info 后返回，旧 ZIP 必须保持。
6. 未取消才 os.replace(staged_path,final_path)。这是唯一发布点；不能直接写 final ZIP、
   预先删除旧文件或改用跨目录 move。退出内层临时目录后，原 try 才结束。
7. try 外 log `Backup: {final_path}`，再 completed('backup')，之后才退出外层临时目录。

完整调用位置按原行为保留：progress 回调取消不会跳过紧接的 pm path；它会在第一个 pull 前
被看到。最后成功日志回调取消不会阻止 completed，因为原本这里没有新门禁。

### backup 的异常范围

- 外层临时目录的构造/退出、获取路径、progress、pull、失败聚合、最后 pull 后的 log/info、
  os.walk 及计数失败报告均在压缩 try 外；异常传播，不能统一改成 Backup failed。
- 只有 makedirs→内层 TemporaryDirectory→make_archive→压缩后取消 log/info→replace→
  内层清理在 try 内，异常变为 `failure(f'Backup failed for {package}: {exc}')` 然后返回。
  except 中 failure 本身再抛错就传播，不能吞掉。
- 若 replace 已成功但内层 cleanup 抛错，原行为是文件已替换、报告失败、无 done；不偷偷回滚。
  外层 cleanup 在 done 之后抛错则保留已发出的 done 并传播。日志/完成回调异常也不回滚发布。
这些罕见时序是重构兼容基线，不代表理想行为，本轮不做行为修正。

## restore 完整事务、用户与计数

空 files 静默返回。内部三个计数归同一个服务调用：installed（成功安装 APK 数）、succeeded
（完成归档数）、failed（失败归档次数）。不用最终 DTO 在 worker 再计算，不排序/去重文件。

每个归档开始在 try 外做 cancelled 检查，取消发 log 再 warning，文本固定为
`Restore cancelled: {installed} APKs installed, {succeeded} archives completed`，然后返回。
app 名用 basename(zp).replace('backup_','').replace('.zip','')，不规范化大小写。

每归档 try 内完整持有 TemporaryDirectory(prefix=f'rs_{app}_') 与 ZipFile(zp,'r')，通过
`utils.archive.safe_extract_zip` 解压并关闭 ZIP；解压后取消则按上述格式报告/返回。
扫描 `f.endswith('.apk')`（区分大小写，与 backup 不同），无 APK 抛原 RuntimeError。
仅当 APK 数>1 且某 APK 的精确 basename.lower()=='base.apk' 才 split 安装。
ZIP 文件名/父目录名含 base.apk、not-base.apk 不触发 split，.APK 不纳入候选。

扫描和 split 判定后再次取消检查；split 调 confirm_user 一次后 install-multiple --user U -r *apks，
timeout120；普通 APK 每条先取消、再 confirm_user、再 install --user U -r path，timeout120。
任何 confirm_user 返回 None 就立即返回，不新增汇总，不把已发的用户错误重复报告。
命令不传取消；失败用 command_error 抛 RuntimeError('install[-multiple] failed' fallback)，
本归档停止后续安装，但进入失败处理后允许下一归档继续。

成功单包 installed+=1，split installed+=len(apks)，不可回滚。退出临时目录成功后 succeeded+=1，
再 log `Restored (i+1/N): basename`，这两项仍在 try 内。发生 Exception 则 failed+=1，
调用 failure(`Restore failed (i+1/N) for basename: error`)；failure 抛异常仍传播。

末尾先 cancelled 检查：最后一个安装返回成功后即使已取消，也先保留安装计数、退出临时目录、
succeeded 与 Restored 日志，再发布取消 warning，不发 done。若最后安装失败且也取消，先原失败
反馈，随后取消 warning 优先于 incomplete。未取消且 failed>0 则 log incomplete 摘要，
feedback 级别是 succeeded>0 ? warning : error，无 done；全部成功才 log complete 后 completed('restore')。

### restore 的异常范围

归档前取消 callback 与 app 名计算在 try 外。try 包含解压/扫描/所有中途取消 callback、
confirm_user、安装、临时目录清理、succeeded 递增和 Restored 日志。故 Restored 日志 callback
抛错时，该归档已 succeeded+=1，随后也 failed+=1；不能“修正”成互斥计数。清理失败在成功计数前
则不计 succeeded。return 时 cleanup 抛错也会被当前归档 except 捕获，可能进入下一归档。
末尾 cancelled/incomplete/complete/completed 在归档 try 外；异常直接传播。
不要扩大 except 到整个 restore，也不要用 callback 包装器吞掉调用方异常。

## 安全、依赖替换与清理

`safe_extract_zip` 仍是唯一 ZIP 解压入口，读取当前真实实现已有的目标路径、成员数、总字节、
压缩比限制。本轮不改 utils/archive.py，也不额外宣称它已有未核实的符号链接拒绝策略。
除用户指定成功发布的 ZIP 外，临时内容仍由原嵌套 context manager 清理；不捕获异常后删用户旧 ZIP。

为保持职责清晰，本轮选择把文件依赖 patch 迁到真实 archives owner，不向服务暴露纯为测试存在的
extractor/archive_builder 参数。`tests/test_app_manager_restore_cancellation.py` 的导入及三处
patch 改为 services.apps.archives.safe_extract_zip / services.apps.archives.shutil.make_archive；
仍验证真实 worker 的取消和信号，不移除测试或放松断言。
新服务测试同样替换 archives 的 tempfile/os/shutil 窄边界，只操作 tmp_path 内的文件。

保留 worker `_adb`、`_read_current_user`、`_bind_current_user` 的显式实例/类方法替换。
worker 不再持有 os/shlex/shutil/tempfile/zipfile/re 等只为已迁业务使用的导入；逐项核对剩余用途再删。
`_command_error` 全部内部消费者迁出后可删除，服务共用 actions.command_error；无外部 patch 证据，
不建立永久私有别名。`_safe_pkg`/is_safe_package 若剩余无消费者同理清理。
不新建 globals 查找、ModuleType 代理或旧模块任意属性转发。

## 验证与未验证边界

新服务采用 fake executor 与真实临时文件完整执行；独立子进程在 import 前阻断
PySide6/qfluentwidgets/gui/models/adblab.presentation，验证 actions 与 archives 的导入及成功/取消/
失败路径，不只做 AST 导入扫描。真实 `_adb` 的 core/exec.py._log_if_slow 仍可能加载 Qt 日志，
不宣称真实设备执行完全无 Qt。

只跑计划内新测试与 AST 核对的现有精确节点；不跑整个 test_model_apps、phase0、clear_data 或
worker_users 混合套件，不重复已验收查询阶段。GUI 忙碌预算保留一个已存在的关联节点。
主任务统一 Pyright 和源码 packaging（临时 LOCALAPPDATA/XDG_CONFIG_HOME；检查实际 legacy 读取边界）。
真实 Android 用户切换/安装、设备中途取消、宿主文件系统故障、真实窗口关闭和 PyInstaller
产物不由 fake、离屏或源码 self-check 证明；以上为设计时的验证约束；实际结果及未验证项见正式实施计划末尾。

## 主任务裁定

范围及补充裁定见正式实施计划；源码自检使用全部数据环境变量隔离，不仅草案简写的两个目录入口。
