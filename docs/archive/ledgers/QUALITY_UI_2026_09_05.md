# 2026-09-05 质量与 UI 改进验收记录

本记录只描述当日 `ui-redesign` 本地工作树的验收，不代表后续代码或正式发布状态。开始时基于
`2297744`，已有 6 个未提交文件；原始差异已另存补丁，实施后所有修改保持未暂存、未提交。

## 实施范围

在既有 PySide6 + Fluent 技术栈与三工作区导航改动上，完成有失败证据的业务、数据和资源归属
问题修复，提取内部共享导航组件，并调整首页、页头、设备上下文和功能页的响应式布局。未改变
应用版本、生产依赖版本、配置 schema 或发布流程。

当前实现细节分别维护在 [架构](../../project-knowledge/ARCHITECTURE.md)、
[业务流程](../../project-knowledge/BUSINESS_FLOW.md)、
[数据流](../../project-knowledge/DATA_FLOW.md) 和
[模块地图](../../project-knowledge/MODULE_MAP.md)，本记录不重复维护这些事实。

## 冻结后的验收

| 项目 | 当时结果 |
| --- | --- |
| 完整 pytest，Qt offscreen | 1349 通过、1 跳过，286.11 秒；跳过项要求 Windows 原生插件 |
| Windows 原生 Qt 定向回归 | 27 通过，18.51 秒，包含上述离屏跳过项 |
| 全项目 Ruff | 通过 |
| 全项目 Pyright | 0 错误、0 警告、0 信息 |
| 中文注释检查 | 默认受控范围和本轮 services 修改均通过 |
| Windows PyInstaller 构建 | 使用现有 ADBLab.spec 构建成功；产物位于仓库外独立目录 |
| 真实产物 packaging 自检 | 退出码 0，17 项全部通过，标准错误为空 |
| 界面证据 | 42 张最终或仍适用的布局截图，覆盖宽窄窗、浅深主题、大字体及不同缩放比例 |

首次完整测试曾出现 17 个失败和 1 个清理错误；继续修复对象归属、排队关闭、行高和控件测量，
并补齐测试替身的真实状态契约后，才形成上述最终通过记录。原有有效断言保留，未以跳过测试或
放宽误差完成验收。pytest 仍产生上游 Qt 控件相关弃用警告；本轮没有升级生产依赖消除警告。

原始补丁、两轮完整日志、JUnit、原生 Qt 日志、视觉探针和打包材料留在任务附件的 `quality-run/`。
最终证据文件为 `full-pytest-final.txt`、`pytest-final.xml`、`native-ui-final.txt`、
`static-checks-final.json`、`ui/UI_VALIDATION.md`、`package-final-validation.md` 和
`package-final-verification.json`；较早没有 `final` 标识的构建与测试材料仅保留为过程证据。

## 验证边界

设备操作使用替身，UI 使用空设备或虚构离线会话，没有连接真实 Android 设备执行安装、录屏、
投屏或性能采集。原生 Windows 截图使用实际 Qt 插件，但采用合成屏幕适配并关闭 Mica；真实多
显示器 DPI 切换、Mica / DWM 效果及 macOS / Linux 运行效果未验证。打包自检验证资源与导入等
边界，不等同于实机业务或分发验收。测试环境和数据隔离方式见
[测试指南](../../guides/TESTING_GUIDE.md)。

仍需外部条件或产品决策的项目继续以
[风险与技术债](../../project-knowledge/RISKS_AND_DEBT.md) 为单一账本。本次本地软件验收
不替代这些项目的后续确认，也不表示已发现和消除所有潜在问题。
