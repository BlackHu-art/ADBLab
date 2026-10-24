# Qt worker 目录归位设计

日期：2026-10-24。状态：实施、任务独立审阅及全项目最终独立审阅均已通过。前置应用 actions/archives 与 file_operations 已验收，实际迁移基线为此后的最终 worker 快照；下文保留设计约束。

## 目的与前置关系

将 `models/app_manager_worker.py`、`models/file_explorer_worker.py` 的最终 Qt 实现分别归位到 `adblab/presentation/workers/app_manager.py`、`file_explorer.py`。每个类只定义一次，两个旧路径成为同模块身份兼容入口。GUI 直接引用新 owner；原页面的可替换工厂仍在原页面模块，业务服务不反向依赖 worker。

前置应用查询、actions/archives 和文件事务提取负责“业务从线程适配中分离”；本阶段只负责目录、导入与兼容。不得再次改服务接口、构造、命令、取消、发布或异常边界。TransferWorker 仍是完整 Qt/ProcessRunner 适配器，所有 reader/stop/wait/force_stop 状态随类整体移动，不能进一步拆服务。

实际收益是 Qt 适配职责有明确目录，新 worker 导入可以绕开 models 的 eager 聚合；不宣称测得启动提速、去掉 Qt 或消除全部旧入口成本。保留原位的成本最低，但在服务已分离的前提下，整模块一对一归位与现有 alias 约定一致，迁移面可控。

## 兼容方案比较与裁定

| 方案 | 身份与 patch 行为 | 成本/结论 |
| --- | --- | --- |
| 类静态 reexport | `OldClass is NewClass` 成立，类级 start patch 有效；但旧/新 module 不同，`old.monotonic = fake`、`old.load_app_metadata = fake` 不会改变新方法 globals | 需要迁移不少仍有实际消费者的 patch，且不满足本阶段要求的同模块身份；不采用 |
| **整模块 alias + TYPE_CHECKING 显式导出** | old/new module、类与方法 globals 是同一对象；保留构造前后 globals patch 和旧类 patch | 沿用 `gui/dialogs/file_explorer.py`、`app_manager_details.py` 等现有模式；采用 |
| 动态 ModuleType/属性同步、兼容子类、双份定义 | 需同步更多状态，可能改变 QThread/Signal 类身份 | 没有必要；禁止 |

每个旧文件基本形状如下；file_explorer 同理。TYPE_CHECKING 导出在实施前依据最终模块符号表生成显式行，不用 import *、动态 getattr 或通用代理。

```python
"""保留旧模型模块路径，与 Qt worker 实现共享身份和替换点。"""
import sys
from typing import TYPE_CHECKING

from adblab.presentation.workers import app_manager as _implementation

if TYPE_CHECKING:
    from adblab.presentation.workers.app_manager import AppManagerWorker as AppManagerWorker
    # 实施时补齐最终模块中确实保留的静态导出，不能复活已迁走的业务私有符号。

sys.modules[__name__] = _implementation
```

新实现不写旧路径到 sys.modules、不导入 models、不回读旧模块 globals。新入口先导入不会建立 models 包；随后显式导入旧入口才经过 models/__init__.py，再由 shim 完成 alias。旧入口先导入仍先加载 models 聚合，这是 Python 包导入机制和兼容成本，本批不修改 models/__init__.py。

旧模块的 `__name__/__spec__/__file__` 与类 `__module__` 反映真实新实现位置。保留导入路径、对象身份与行为，不伪造 __module__。当前两个 worker 没有基于 __file__ 的资源定位；实施前再搜一次，若前置提取新增路径依赖需重新评估，不能盲目改相对层数。

## 文件 owner 与允许改动

| 文件 | 允许内容 |
| --- | --- |
| `adblab/presentation/workers/__init__.py`（新） | 仅中文说明，无 eager worker 导出，无 __getattr__，不新增包聚合 API |
| `adblab/presentation/workers/app_manager.py`（新） | 完整承接前置提取后唯一 AppManagerWorker 模块，生产逻辑/全局依赖原样移动 |
| `adblab/presentation/workers/file_explorer.py`（新） | 完整承接前置提取后六类及其实际残余依赖，TransferWorker 全类原样移动 |
| `models/app_manager_worker.py`、`models/file_explorer_worker.py` | 显式 TYPE_CHECKING 导出与整模块 alias，保留文件路径 |
| `gui/features/app_manager/page.py`、`details.py`、`icons.py` | 仅把 worker import 来源改新模块；icons 为 TYPE_CHECKING import |
| `gui/features/file_explorer/page.py`、`list.py`、`view.py`、`ops.py`、`transfers.py` | 仅把 worker import 来源改新模块，保留本地名字和工厂调用 |
| `tests/test_worker_module_compatibility.py`（新） | 双顺序身份、新入口导入边界、旧 globals 实际执行接缝 |
| models/__init__.py、adblab/presentation/__init__.py、业务服务、其余 GUI/旧测试 | 不改；旧测试继续验证旧入口 |
| docs / Pyright / packaging | root 统一集成；本 agent 不写正式 docs、不执行运行门禁 |

单 owner 顺序移动两个模块与导入，不与前置服务提取并发编辑原 worker。不能从 HEAD 拷贝：当前 app_manager_worker 已有查询阶段修改，前置阶段还会进一步改动它。

## 稳定类接口与生命周期

当前 AST 核实的构造如下；前置阶段承诺保持，实施前用最终快照再核对：

| 类 | 构造参数（省略 self） | 信号 |
| --- | --- | --- |
| AppManagerWorker | device_ip:str, operation:str, *, user_id:int\|None=None, **kwargs | log_message(str)、user_context_loaded(int)、apps_loaded(list)、app_details_loaded(dict)、app_detail_batch(str,str,str,str)、app_metadata_loaded(dict)、app_icon_loaded(str,bytes,str)、permissions_loaded(list,list,list)、backup_progress(str,str)、operation_done(str)、operation_feedback(str,str) |
| ADBWorker | device_ip:str, args:list, timeout:int=30 | result_ready(str,bool) |
| DirectoryListWorker | device_ip:str, path:str, use_root:bool | result_ready(object,bool) |
| TextReadWorker | device_ip:str, path:str, use_root:bool, byte_limit:int | result_ready(object,bool)、decoded_ready(object) |
| TextSaveWorker | device_ip:str, path:str, content:bytes, use_root:bool | 继承 ADBWorker.result_ready |
| LocalTextSaveWorker | path:str, content:bytes | 继承 ADBWorker.result_ready |
| TransferWorker | device_ip:str, args:list, cwd:str="" | progress(str)、result_ready(str,bool,str) |

保留原继承链、QThread.finished、原生 QObject 父子关系、实例 `.__new__` 的类身份、类级方法 patch、signal 定义次数和所有调用时点；不加 parent 参数。AppManager operation_done 的成功反馈连接不重接，user 准入/翻译留 adapter。四文件事务的 marker/args/decoded_available/同步回调继承前置设计，不能在移动中重新调整。

TransferWorker 保留 `_process_key=transfer_{id(self)}`、ProcessRunner 实例、_proc、_aborted、_run_entered/_run_finished、cwd 默认当前目录以及全部方法。request_stop 只是请求；run 启动后再次检查取消；stdout reader 可被停止唤醒；live process 不注销；wait_stopped 复核实际存活和 QThread join。pull 仍调用 SafeFileDownload，不加一层通用服务。

页面负责 worker setParent、finished/QueuedConnection、UI 绑定、列表/代际、deleteLater 与 TaskSupervisor 关闭屏障，均原位。新目录不取得页面 ownership，也不创建共享 worker 注册表。

## GUI 工厂与真实 patch 边界

AppManager page 的 AppManagerWorker 名字带明确测试接缝注释，batch 的延迟导入仍读取 `.page.AppManagerWorker`，icons 实际创建也延迟从 `.page` 读取；details 自己的 AppManagerWorker 保持独立工厂。只改 page/details 的类来源及 icons 类型 import，不把 batch/icons 改成直接引用新类，从而绕开页面 patch。

FileExplorer page 的 `_run_adb/_run_transfer` 继续用 page 本地名字，list 的 DirectoryListWorker、view 的 TextReadWorker、ops 的两个保存 worker、transfers 的类型/适配引用保留各自模块名字。旧 gui.dialogs alias 继续和这些 feature 模块同对象；不改其 shim。

| 实际旧消费 | 目录迁移后策略 |
| --- | --- |
| app_worker.monotonic / load_app_metadata / load_app_icons | 整模块 alias 使重新赋值仍命中真实方法 globals；构造后、执行前 patch 保留 |
| worker._adb / _read_current_user / _bind_current_user | 类实现原样移动，实例 patch 保留 |
| old_file.CommandRunner / ProcessRunner / SafeFileDownload 或对应类方法 | 仍保留在最终 worker 的实际绑定不变；模块重绑定由 alias 保证，类方法 patch 由同对象保证 |
| old worker Class.start 等 | 旧新类同对象，GUI 导入的新类仍被类级 patch 命中 |
| gui.dialogs.app_manager.AppManagerWorker 与 details 独立工厂 patch | 保留两处页面本地工厂，既有兼容测试不改 |
| gui.dialogs.file_explorer.ADBWorker/TransferWorker 与 file_explorer_list.DirectoryListWorker patch | 保留原页面/协作模块本地工厂，既有兼容测试不改 |
| 前置阶段已迁到 services.apps.archives 或 services.file_operations 的私有依赖 patch | 继续真实 service owner，不由本阶段恢复旧 worker 的已移除符号 |

边界说明：对旧 worker 模块 `AppManagerWorker = Fake` 的赋值会同步新 worker 模块同名属性，但不能倒推重绑 GUI 已经 `from ... import AppManagerWorker` 得到的本地名字；旧实现也是如此。不要宣称整模块 alias 能改变所有已导入引用。页面工厂 patch 与共享类方法 patch 是两个现有、不同的接缝。

## 导入与资源边界

新包 __init__ 仅说明；但导入任何 `adblab.presentation.workers.*` 仍会先执行 presentation/__init__.py，当前 eager 导出 QtTaskSupervisor，并进一步加载 application 的现有聚合。这部分不改，不宣称新入口只有一个 class 或完全懒加载。允许 PySide6/QtCore、core.exec、file worker 的 core.log_service、纯业务服务及原 utils 依赖；禁止新入口反向引入 models、controllers、gui feature/page、qfluentwidgets。

旧入口 models/__init__.py 当前导出 ADBAdvanced、ADBApp、ADBDevice、ADBModelCore/async_command、ADBNetworkMixin、ADBSystemMixin、ADBTesting、DeviceStore。旧优先导入必有这个成本；新优先探针必须先在旧入口尚未导入时证明无 models，再单独验证旧入口身份。两顺序不能共用已经预载入 models 的 pytest 进程。

资源通过原 resource_path/runtime工具接口，用户数据继续原 utils/user_data，服务 helper 不移动。无需因新目录重写工具根或新增打包 hiddenimports；静态 import 可达性由源码依赖对照核实，兼容测试验证新旧导入，root 源码 self-check 检查既有工具/资源边界。以上均不证明真实 PyInstaller 产物已完整收集，产物验收另算。

## 验收与非目标

目录迁移应满足“最终旧模块实现 AST = 新实现 AST”，只允许 module docstring 的归属表述差异；方法正文、装饰器、基类、Signal、全局依赖名/绑定保留。旧 shim 与新 __init__ 独立检查。GUI 八个文件仅改变 worker import 的来源及现有 Ruff 规则要求的排序/换行，名字、alias与作用域不变；移除该条导入后其余完整 AST 和导入相对顺序相同。排序变化后再验证实际导入与页面工厂，不能顺手改工厂/关闭。

最小新测试证明两个 leaf、两种导入顺序、父包属性、类身份、module globals 的实际 fake 执行，以及新入口不加载旧 models/GUI。既有精确节点验证原工厂与 Transfer 生命周期。前置服务业务测试不默认全量重跑；如 parity/关联失败指出业务变化再扩大。此阶段不改配置/用户数据/格式/版本/依赖/CI，不提交，不运行设备操作。

## 主任务裁定

范围及补充裁定见正式实施计划；源码自检使用全部数据环境变量隔离，不仅草案简写的两个目录入口。
