# Controller 模型创建与依赖装配设计

状态：2026-10-24 已完成代码实施、集成验证和独立审阅。用户已授权持续全项目重构与多 agent 并行执行；
本设计经独立 builder check 后实施，实际结果见[实施计划](../plans/2026-10-23-controller-model-composition.md)。
整体进度见[持续重构路线图](../plans/2026-10-23-project-refactor-roadmap.md)。

## 目标和现状

将 `_ADBControllerBase` 内硬编码的四模型创建提取为可注入工厂；保留构造顺序、对象身份、信号、
关闭、设置和设备历史语义。沿用 Python 3.11、PySide6 与当前依赖，不引入 DI 框架。

现有事实来源：`controllers/__init__.py`、`controllers/_base.py`、`models/adb_model.py` 和四模型构造：

1. 公开门面先选择 APK picker 和设备生命周期适配器，均支持后绑定窗口。
2. base 保存适配器，创建 signals、ActionResults，读取 AppSettings 单例。
3. 按 `ADBDevice → ADBApp → ADBTesting → ADBAdvanced` 顺序无参创建模型。
4. 建立锁、OperationManager 和用例，再连接四条完成信号、四条进度信号。
5. 设置窗口兼容属性，建立 Monkey 状态与四槽 executor，建立 handler map，最后按需加载 DeviceStore。

模型构造不执行 ADB/启动业务任务，但分配 QObject、锁和线程池。普通池全局共享，每模型 long_pool
独立；Testing/Advanced 各持有 ProcessRunner，Advanced 还有以自身为 parent 的双槽录屏池。
Controller 构造仍可能因设置与历史加载访问磁盘，不能称为无 I/O。

## 方案比较与决定

| 方案 | 收益与代价 |
| --- | --- |
| **无参模型工厂注入（采用）** | 原位置调用，保持构造时序；测试可注入四模型，base 不再选择具体实现；改动集中于 Controller |
| MainFrame 预先创建模型包再注入 | 能让 GUI 拥有装配细节，但提前分配资源，改变 settings/模型顺序与构造失败边界，还会改动共享 GUI 替身 |
| settings、executor、用例、store 一次性纳入依赖容器 | 范围涉及不同生命周期和持久化副作用，本阶段缺乏必要性且增加兼容成本 |

主 agent 决定第一种。MainFrame 原调用可以沿用公开 Controller 的默认装配入口；本阶段不新增
GUI 参数，也不为形式上的显式装配搬动资源创建。后续若有生产替代模型，仍可传入工厂。

## 接口与实现边界

新增 `controllers/model_dependencies.py`，只负责模型创建，属于 Controller 装配层：

```python
@dataclass(frozen=True)
class ControllerModels:
    device_model: ADBDevice
    app_model: ADBApp
    testing_model: ADBTesting
    advanced_model: ADBAdvanced

ControllerModelFactory = Callable[[], ControllerModels]

def create_controller_models() -> ControllerModels: ...
```

采用现有模型具体类型；不定义覆盖全部模型方法的巨大 Protocol。默认工厂在调用线程按原顺序无参
创建，每次返回新的四个实例；不缓存模型、不读取设置/历史、不接信号、不启动任务、不负责 shutdown。

公开 `ADBController.__init__` 在现有关键字末尾新增
`model_factory: ControllerModelFactory | None = None`。仅 `is None` 使用默认工厂，不提前调用。
base 的 `__init__` 新增必填关键字 `model_factory: ControllerModelFactory`，在原四个构造行的位置
调用一次，将结果赋给原四个 `*_model` 属性。创建函数异常原样传播，不回退或重试。

模型包只在构造期间使用，不保存第二份业务/关闭读取源；现有 mixin、信号接线和 shutdown 继续读取
四个原属性。模型选择从 base 移除，ProcessRunner 的全局兜底 import 仍保留。

工厂契约：由 GUI 线程同步调用；注入模型属于本 Controller，尚未启动任务、未预连 Controller 信号，
不得跨 Controller 共享已关闭或在用实例。模型仍无新增 parent、moveToThread、Timer 或后台初始化。
不新增运行时反射校验或自动销毁机制；调用方须遵守静态接口与资源契约。

## 必须保持的行为

- 四模型创建的先后顺序及其在 settings 之后、业务用例/信号/executor/历史之前的位置不变。
- 原八条连接的位置、顺序、Qt 默认连接类型不变；结果、进度和晚到回调仍走原分派屏障。
- 旧构造、显式假值 picker/lifecycle、新假值 factory、history 默认读取与 preload 跳过均兼容。
- ActionResults、OperationManager、各 use case、锁、代次、executor、window_owner 留在原位置。
- shutdown 仍先关闭结果准入，四模型全部 begin_shutdown，再 Testing/Advanced shutdown、全局进程兜底、
  executor 排空、四模型等待、Device/Testing 残留核验；逐项尝试后抛首错，不跳过后续清理。
- 构造失败不伪造成功或自动换回默认模型。当前没有完整的部分构造回滚，本阶段不新增有启动副作用的
  资源、不声称解决该缺口；失败时部分 `self.*` 尚未发布的内部状态不定义为可用 Controller。
- 不改变模型实现、ADB 命令、用户交互、配置、历史路径/字段/格式、平台支持、生产依赖和 CI。
- 现有 `__new__` 后改写四个模型属性的内部测试仍有效；不为迁移删除断言、放宽标准或新增 skip。

## 并行与验收

冻结上述名称、字段和签名后分三个独立文件组：工厂及测试、门面/base 接入及测试、信号/关闭回归。
主 agent 管理文档、基线、跨组接口、一次集成验证和独立审阅。组内可独立修改；跨组仅消费已冻结接口，
不得顺手修改其他组的文件。Qt 测试放在各自子进程且隔离设置/存储，不访问实机或并行跑完整 GUI 集合。

验收关注工厂一次调用、模型新鲜实例和线程归属、默认兼容、异常不回退、四模型信号各投递一次、
关闭仍读取当前属性及顺序/首错传播。先取旧公开构造/关闭基线，再测新增文件与受影响消费者。
MainFrame 与共享 GUI helper 不变，不自动重复完整布局、字体或全量 pytest。

新增运行时模块需源码 packaging 自检；类型检查报告真实分析文件数。文档状态不能把设计/静态核对
写成实现验收。实机和完整 PyInstaller 构建不属于本阶段自动验证。
