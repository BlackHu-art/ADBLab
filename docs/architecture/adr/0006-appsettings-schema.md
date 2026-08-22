# ADR-0006：AppSettings schema 版本化与遗留种子清理

- 状态：Accepted（Step A–C 主路径已落地；未来版本字段透传已闭环）
- 日期：2026-08-20
- 前置：ADR-0003（core 自足、原子持久化）

实施进度：Step A–C 已落地——`schema_version`（当前 3）+ 显式迁移链（v1 折算面板
比例并补齐缺失键、v2 剔除未知键）+ 未知键加载时剔除并 WARNING；`update()` 拒绝
写入 `schema_version`；更高版本文件只读已知键并保留版本号。种子 `app_settings.json`
已中性化（`save_directory` 为空、无旧像素值、monkey 参数与代码默认一致、补
`schema_version`）；`connected_devices.yaml` 清空为占位（历史真实设备标识移除）；
`controllers/_base.py` 死属性与空占位 `resources/package_info.yaml` 已删除。
知识库（DATA_FLOW/RISKS_AND_DEBT）已同步。

实现偏差已闭环（2026-08-21 后续复核）：高于当前版本的文件在 `_load()` 当下不会被改写，
后续保存保留较高的 `schema_version`；`_load()` 将未知字段缓存进 `_future_extra`，`_save_atomic`
在快照中合并回写，避免降级安装破坏新版本数据。决策 2 的“原样保留”已完整落地，
并有 `test_future_schema_version_keeps_known_values_and_version` 回归断言。

## 背景

设置持久化目前是"扁平字典 + 隐式迁移"：

- `core/settings_manager.py` 在 `_load` 时只读 `DEFAULTS` 已知键，未知键被静默
  丢弃（下次保存才真正从用户文件消失），没有 schema 版本字段，结构演进只能靠
  一次性启发式（如 `_legacy_panel_ratio` 把旧版左右像素宽度折算为
  `panel_split_ratio`，仅当文件里没有 `panel_split_ratio` 时触发）。
- 安装包内的遗留种子 `resources/app_settings.json` 仍携带作者本机路径
  `"save_directory": "E:/Download"`、旧像素宽度 `left/right_panel_width`
  （588/599）、与代码 `DEFAULTS` 不一致的 `monkey_params`（events 100000 vs
  默认 10000、throttle 2000 vs 300、缺若干新键、多一个已死键 `package_name`）、
  以及已无界面消费的 `confirm_dangerous_ops`。该文件仅在用户配置不存在时作为
  迁移源被读取，但内容本身是 2023 时代快照，首装用户会继承其中的本机路径与旧值。
- 遗留种子 `resources/connected_devices.yaml` 含历史真实设备标识（两台内网 IP
  与一台设备序列号，具体值已脱敏），违反 AGENTS.md"不得提交真实设备唯一标识"约定；
  `models/device_store.py` 仅在用户文件不存在时把它当迁移源读取。
- `resources/package_info.yaml` 为空占位，仅被 `controllers/_base.py` 的两个
  **只写不读**属性（`connected_devices_file`、`package_info`）引用，属死代码。

目标：为设置引入显式 schema 版本与迁移链，把遗留种子收敛为中性默认值，清理
资源目录中的真实设备标识与死引用；**已升级用户的行为零变化**（迁移只做结构
补齐，不改动用户已设置的值）。

## 决策

1. 设置 JSON 顶层新增 `"schema_version": 3`：
   - `CURRENT_SCHEMA_VERSION = 3` 定义于 `core/settings_manager.py`；
   - `_save_atomic` 的快照始终写入当前版本号；
   - 文件中无 `schema_version` 视为 v1（种子时代），有则按其值走迁移链；
   - `update`/`set` 拒绝写入 `schema_version`（忽略并记录 WARNING），版本只由
     加载/保存流程管理。
2. 显式迁移链 `_MIGRATIONS: dict[int, Callable[[dict], None]]`，按版本升序原地
   改造存储字典，每步只做**结构补齐**：
   - v1 → v2：由 `left/right_panel_width` 折算 `panel_split_ratio`（复用现有
     `_legacy_panel_ratio` 语义），补齐缺失的 `device_scan_interval_ms`、
     `device_log_split_ratio` 与全部 `SCRCPY_SETTING_DEFAULTS` 键；`monkey_params`
     与 `DEFAULTS["monkey_params"]` 深合并（用户已设值不动，仅补缺失键、删未知键）；
   - v2 → v3：未知顶层键删除（收集名单并 WARNING 一次性记录，取代现在的静默
     丢弃），`monkey_params` 内的未知键（含 `package_name`）删除；
   - 未知未来版本（大于 3）不迁移、不清键，仅记录 WARNING 并原样保留用户值，
     防止降级安装破坏新版本数据。
3. 遗留种子清理（`resources/app_settings.json`）：
   - `save_directory` → `""`（跟随 `AppSettings.save_directory` 的
     "用户主目录/ADBLab" 回退语义，不再携带作者本机路径）；
   - 删除 `left_panel_width`/`right_panel_width` 旧像素值（键本身仍是活跃设置、
     继续留在 `DEFAULTS` 与窗口布局读写中，仅从种子文件移除 588/599 历史值）；
   - `monkey_params` 与代码 `DEFAULTS` 对齐（含事件比例总和仍为 100%），删除
     `package_name`；
   - 补 `schema_version: 3` 与 `DEFAULTS` 中缺失的其余键；`confirm_dangerous_ops`
     保留但注释标注 deprecated（旧版本文件读入时仍兼容，界面已无消费）。
4. `resources/connected_devices.yaml` 收敛为空映射 `{}`（附带说明注释）：首装
   不再迁入任何历史设备；`DeviceStore.load` 对空映射已有安全路径（空快照、不写
   用户文件）。真实设备标识从此仓库中移除。
5. 删除 `controllers/_base.py` 的两个死属性（`connected_devices_file`、
   `package_info`）并删除空占位 `resources/package_info.yaml`；删除前 grep 确认
   无任何读取点（含测试）。
6. 迁移与种子清理不改变 `DEFAULTS` 结构本身；`_normalise_setting` 继续作为
   加载后逐键校验层（schema 迁移先跑、逐键校验后跑）。

## 实施步骤（每步独立提交、跑全量门禁）

- Step A：`schema_version` + 迁移链 + 未知键显式清理与日志（`settings_manager.py`
  及其单测扩展），种子 `app_settings.json` 对齐。
- Step B：`connected_devices.yaml` 清空、死属性与 `package_info.yaml` 删除。
- Step C：文档同步（`docs/project-knowledge/` 数据模型/存储条目 + 本 ADR 状态
  改 Accepted）。

## 后果

优点：

- 设置文件自描述，未来结构演进有确定迁移入口，回滚与降级行为明确；
- 首装用户不再继承作者本机路径、旧像素宽度与过期 Monkey 默认值；
- 仓库移除历史真实设备标识，符合安全约定；死代码与空占位文件出清。

代价与风险：

- 迁移链在已升级用户的真实文件上执行，需覆盖"无版本号种子、v3 现文件、未来
  版本文件"三类用例，防止迁移误删用户键（按决策 2 只删未知键并记录日志）；
- `connected_devices.yaml` 清空后，依赖旧种子迁移的老用户设备历史不再恢复，
  但该数据本就是本机历史缓存，影响可控；
- `confirm_dangerous_ops` 键保留为兼容项，删除需另行评估（涉及老版本升级时
  的未知键清理策略，不在本 ADR 范围）。

回滚：

- Step A/B 独立提交可分别回滚；迁移函数为纯字典变换，回滚后恢复原启发式路径；
- 种子文件修改仅影响"无用户配置"的首次安装，对已升级用户无回滚影响。

## 与既有决策的关系

- 延续 ADR-0003（设置原子写入、core 不依赖 Qt）与 ADR-0004（services 归一）；
- 与 ADR-0005（执行接口统一）无耦合，可并行实施；
- 遵守 AGENTS.md 敏感数据约定：本 ADR 是清理历史真实设备标识的合规动作。
