# ADR-0007：应用用例与 Qt 适配归入现有职责目录

- 状态：Accepted
- 日期：2026-10-24
- 前置：ADR-0003（项目结构）、ADR-0004（服务边界）

## 背景

`adblab/application` 和 `adblab/presentation` 与根目录的 services、core、gui 并存，
相同职责需要跨两套目录寻找。单纯把两个子目录提升为新的顶层目录无法消除这一问题。
用户要求按职责归入已有目录，验证后移除整个 adblab 包。

## 决策

- 业务操作身份和结果归 `services/tasks/`，设备上下文与批次归 `services/devices/`；
  安装批次及 APK 选择协议归 `services/apps/`，录屏与 Monkey 用例分别归对应 service 模块。
- 通用取消及资源监督归 `core/tasks/`。Qt 监督器为显式叶子 `qt_supervisor.py`，
  纯包根不加载 Qt，资源终态与业务操作终态继续分别管理。
- GUI 运行时适配归 `gui/adapters/`，设备发现、应用和文件线程归 `gui/workers/`；
  新包根不聚合叶子，不通过 `gui/features` 的页面聚合加载 worker。
- 迁移完整实现，调整所有生产、测试和工具消费者。旧内部 `adblab.*` 源码导入路径退役，
  不保留同名文件、动态 import hook 或转发壳。原 `models.*_worker` 保留同模块别名，
  MainFrame 的扫描类保留同对象导出，页面工厂的实际全局依赖替换点保持。
- 不改变数据格式、用户目录、资源名、命令协议、信号、线程所有权或关闭流程。
  不新增生产依赖，不调整 CI/CD 和打包策略。

## 验证和后果

先在阻断旧命名空间的环境验证新实现和消费者，再删除旧包，最后验证物理缺席、测试收集、
源码打包自检及关键启动/关闭路径。模块位置和 `__module__` 真实反映新目录；仓库外若有
自行编写的 `adblab.*` 导入代码，需要改用新路径。项目现有持久化格式不保存这些 Python 路径。

完整逐模块映射见[设计](../../superpowers/specs/2026-10-24-adblab-responsibility-merge-design.md)，
验证证据和实施状态见[实施计划](../../superpowers/plans/2026-10-24-adblab-responsibility-merge.md)。
当前职责由[模块地图](../../project-knowledge/MODULE_MAP.md)维护，历史阶段文档保留原路径供追溯。
