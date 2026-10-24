# 设置 schema 与迁移边界设计

日期：2026-10-24。状态：实施、独立任务审阅及最终集成审阅均已通过。

## 意图与授权范围

把设置的默认值、字段规范化和历史字典迁移移到独立包，让纯规则可独立调用，并让
`gui/i18n.py` 的语言选择不再为了一个纯函数加载设置 manager、解析配置路径。
不宣称启动性能提升。用户已授权持续架构/目录调整与自主推进；本草案按该授权选择方案，
不是声称用户逐项选择了下面的实现细节。设计阶段只形成草案，后续实施与验证见配套计划的验收记录。

前置的保存生命周期已完成独立审阅。这里以当前工作树为基线，不以 HEAD 或旧审计的生命周期
结论为基线。manager 的 `AppSettings` 类体、错误 sink 与文件路径保持原位、原行为。

## 备选与选择

| 方案 | 收益与代价 | 结论 |
| --- | --- | --- |
| 只抽出语言/比例两个函数 | 可解决 i18n 导入，但默认值和迁移规则仍混在 I/O owner 中；以后继续拆分会反复调整边界 | 过窄，不选 |
| `core/settings/schema.py` + `migrations.py`，保留原 manager | 两个清楚且可独立测试的职责；旧消费者不批量迁移；保持现有状态和 patch 接缝 | 选择 |
| 同时把 manager 搬入新包，拆 storage/writer/repository | 完整目录归包，但将刚验收的路径、单例、线程归属和测试替换点一并迁移，收益不足以覆盖当前风险 | 留待另有需求，不选 |

## 最小目录与依赖方向

```text
core/settings/__init__.py     仅中文包说明；不导入 manager 或其他模块
core/settings/schema.py       默认值、选项、字段规范化
core/settings/migrations.py   版本识别、原地历史字典变换、未知键诊断
core/settings_manager.py      唯一状态/I/O/生命周期 owner + 旧入口兼容
gui/i18n.py                   只把 normalise_language 的 import 改到 schema
```

方向：`manager -> migrations -> schema`、`manager -> schema`、`i18n -> schema`。
schema 继续复用 `utils.adb_resolver.CLIENT_SOURCE_TOKENS` 与
`utils.console_colors.normalise_console_level`，不复制枚举和控制台级别逻辑。
这些 utils 的导入链有资源/缓存路径辅助模块及锁定义；本阶段保证“不调用路径解析、不创建
AppSettings、不访问设置文件、不加载 Qt/LogService”，不承诺依赖树完全不含路径模块或锁。

## 精确迁移与接口

源行号以本设计读取的当前文件为准，执行时按符号定位。

| 源 `core/settings_manager.py` | 目标 | 旧入口策略 |
| --- | --- | --- |
| 54–67 `SCRCPY_SETTING_DEFAULTS`、`UI_SCALE_OPTIONS`、`LANGUAGE_OPTIONS` | schema，同名 | 显式重导出同一对象 |
| 70–85 `normalise_language(value: Any) -> str`、`normalise_ui_scale(value: Any) -> str \| float` | schema，同名 | 显式重导出同一函数对象 |
| 88–136 `DEFAULTS`、`_FONT_SIZE_RULES` | schema，同名 | `DEFAULTS` 同对象重导出；私有规则也可显式别名，不能复制 |
| 139–265 `_normalise_integer`、`_normalise_adb_client`、`_normalise_setting` | schema；前两者保留私有名，后者新名 `normalise_setting(key: str, value: Any) -> Any` | 前两者显式别名；`_normalise_setting(key, value)` 为调用 schema 的薄委托 |
| 268–288 `_legacy_panel_ratio`、`_stored_schema_version` | migrations，新名 `legacy_panel_ratio(left_width: Any, right_width: Any) -> float`、`stored_schema_version(stored: dict) -> int` | 旧私有名显式别名；原签名与结果不变 |
| 291–324 `_migrate_1_to_2`、`_migrate_2_to_3`、`_run_migrations` | migrations，去前导下划线 | manager 保留原参数的私有 wrapper |
| 326–358 `_prune_unknown_keys`、`_MIGRATIONS`、`CURRENT_SCHEMA_VERSION` | migrations | 清理入口 wrapper；版本同对象导入；迁移表只有新模块的一份 |
| 24–51 路径、sink、`_log_error`；361–688 `AppSettings` 类体 | 原位 | 不改变定义、控制流、锁、返回值或异常 |
| `gui/i18n.py:10` 的 import | `from core.settings.schema import normalise_language` | 其余语言逻辑不改；`main.py:298` 本阶段保留旧路径 |

新迁移模块接口采用显式 reporter，类型为 `Reporter = Callable[[str, str], None]`：

```python
def migrate_1_to_2(stored: dict, report: Reporter) -> None: ...
def migrate_2_to_3(stored: dict, report: Reporter) -> None: ...
def run_migrations(stored: dict, from_version: int, report: Reporter) -> None: ...
def prune_unknown_keys(stored: dict, report: Reporter) -> None: ...

_MIGRATIONS: dict[int, Callable[[dict, Reporter], None]] = {
    1: migrate_1_to_2,
    2: migrate_2_to_3,
}
CURRENT_SCHEMA_VERSION = max(_MIGRATIONS) + 1  # 仍为 3
```

v1 步骤接受 report 但不调用，统一迁移步骤调用协议，避免按具体版本硬编码调度。
`run_migrations` 按原 range/get 顺序执行 `migration(stored, report)`；不盖 schema_version。
新函数不捕获 reporter 异常，不缓存/默认绑定 reporter，不定义 sink。
manager 的 `_migrate_1_to_2(stored)`、`_migrate_2_to_3(stored)`、
`_run_migrations(stored, from_version)`、`_prune_unknown_keys(stored)` 每次调用都读取当前
manager `_log_error` 并显式传入；manager `_log_error` 原来的 sink 异常容错不变。

旧模块 `_MIGRATIONS` 若保留则只导出新表的同对象别名，不能建立第二张 dispatch 表。
当前全仓未发现直接访问/patch 此私有表的消费者；其条目签名将增加 reporter，这是内部协议
变化，不承诺旧私有表条目的单参数调用继续成立。旧私有**函数**入口则全部
保留原签名。实现评审若要求兼容未知表调用者，应重新决定此接口，不能悄悄增加第二份表或全局
reporter。推荐保留别名作为检查入口，并在变更说明明确这一内部边界。

## 必须保持的不变量

1. `manager.DEFAULTS is schema.DEFAULTS`，SCRCPY 字典和语言/比例元组也同对象；原键顺序、
   内容和容器类型不变。`DEFAULTS` 通过 `**SCRCPY_SETTING_DEFAULTS` 建立时的浅合并行为不变，
   不声称两字典后续修改会双向同步。构造/reset/v1 补值/Monkey 正规化继续在原位置 deepcopy。
2. 所有字段规则照搬：bool 与整数区分、字体范围、比例 clamp、语言精确匹配、显示比例选择、
   ADB 路径 `os.path.isabs` 的宿主平台语义和 512 字符上限、scrcpy/字体 128 字符上限、
   save_directory 首尾空白、Monkey throttle `ms` 及未知嵌套字段保留。不能借机修正 NaN、
   任意对象或非字符串 dict 键等历史边缘行为。实际 JSON 键是字符串。
3. 缺失/bool/非整数/非正版本仍视为 1；受支持版本依次 migration 再 prune 再逐键规范化。
   v3 本身不会因补默认值或规范化就立即回写；v1/v2 迁移和 legacy 路径复制继续由 manager
   决定立即或 deferred 保存。migrations 不读取/写入文件、不决定未来版本的加载策略。
4. 高于 3 时 manager 不调用 migration/prune；保留 `_seen_version`、顶层 `_future_extra`、
   Monkey 未知字段。已知字段仍规范化，主动保存/close 将未知字段合并回写。未来文件来自
   legacy 且用户文件缺失时，仍可按既有规则复制到用户目录；不是绝对禁止保存。
5. 清理警告仍先顶层后 Monkey，每类一次，名称按原规则排序，级别和英文文本逐字不变。
   v1→v3 已经清过键，manager 再 prune 不应重复诊断。`set_error_sink` 后换 sink 和
   monkeypatch manager `_log_error` 都在后续调用生效。
6. manager 仍是唯一 AppSettings 类/单例、锁、Timer 集合、active saves、冻结快照、路径、
   json/tempfile/os.replace 与错误 sink owner。保留原 `__all__`，包括未列在其中但被显式
   导入的 `normalise_*` 与 `_normalise_setting`。不改 `sys.modules`，不更改类的 __module__。
7. `_load/update/reset/close` 类体不需要修改。运行时未知键、schema_version 警告在状态锁外、
   closed 拒绝规则、future reset 语义和失败重试冻结快照均维持当前实现。

## 验收与限制

新增纯 schema/migration 用例验证转换语义、源 dict/默认值不被意外共享，以及 reporter 的
顺序/文本/调用时绑定。独立解释器带临时环境和阻断器证明新模块不导入 manager、LogService、
PySide6/qfluentwidgets，不调用 user_config_path/resource_path；新 i18n 用例允许 Qt，但禁止
manager/LogService，调用真实 resolve_language，证明迁移带来实际依赖收益。

现有 persistence 全文件是首要回归；新增兼容测试覆盖新旧对象身份与 wrapper。
关联覆盖只选 typography 的四个 settings 节点、console schema 节点、startup diagnostics
两个设置 sink 节点、i18n 三个语言选择节点，以及已存在生命周期文件（因 manager 的共享
normalizer/global 常量仍被 close 流程消费）；不重复关闭 UI/布局代表组合或再次调查旧失败。

无 main/spec/resource/runtime-path 修改，新 Python 模块通过静态导入可达。主任务决定与并行Remote
归包稳定后集中执行一次源码packaging自检，覆盖新增导入组织边界；子进程数据环境指向临时目录，
不重复owner检查，也不执行PyInstaller构建。若实际实施扩到main比例入口或资源收集，重新界定。

实施后的 docs 由 root 单独维护 DATA_FLOW/MODULE_MAP 中规则事实来源与旧门面，必要时在
ARCHITECTURE 增加一处依赖边界。此设计 agent 不编辑 docs，历史 ADR 不改。
不运行全量、实际设备、真实用户配置、真实桌面或正式构建；不升级依赖，不改 schema 版本。
