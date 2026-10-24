# Home / Workspace 页面目录归位设计

日期：2026-10-24。状态：实施、独立任务审阅及最终综合审阅均已通过。

## 目标与边界

将 `gui/pages/fluent_pages.py` 中首页协作簇与工作区容器按完整类归位，使开发者能直接从功能目录找到实现。保持当前 UI、Qt 所有权、信号、路由、翻译与设置行为。用户已经授权持续自主重构和实际目录调整，本阶段不增加批准或提交步骤。

明确不做：按行数切方法 mixin、MainFrame 组合调整、WorkspaceFeatureHost 状态机改写、设置页或设置卡归包、导航服务抽象、依赖升级、资源或翻译词库改动、CI/打包流程改动。已归位的 Logcat、AppManager、FileExplorer、Performance、Media 不重复迁移或验收。设置既有 8 个布局失败不纳入本批修复，也不扩大其矩阵。

## 方案与选择

1. **采用：两个真实实现模块 + 原聚合模块静态重导出。** 首页四类一组，工作区三类一组，设置保留真实定义。得到清晰目录边界，同时以相同类对象维持旧 import、Qt `findChildren` 与信号身份。
2. 全部类直接迁移并让旧模块成为 facade：设置方法 globals 会换成新模块，破坏真实旧路径替换点；需要额外依赖契约，不属于本批。
3. 全文件 alias 到一个新模块或拆方法 mixin：前者不能表达多个职责目标，后者增加继承和依赖耦合；不解决实际目录责任问题。

方案 1 是在已经授权的目录重构范围内作出的实施选择；不冒充用户逐项指定的内部设计。

## 文件责任及单 owner

| 文件 | 归属与变化 |
| --- | --- |
| `gui/pages/home.py`（新增） | 完整定义 `ActionCard`、`ActionCardView`、`DeviceContextCard`、`HomePage`；保持类内代码、签名、顺序与信号 |
| `gui/pages/workspace_containers.py`（新增） | 完整定义 `GalleryPage`、`WorkspaceSectionPage`、`WorkspaceAreaPage`；仅承载滚动、布局所有权、领域路由投影及 host 激活 |
| `gui/pages/fluent_pages.py` | 移出以上 7 类，显式静态重导出同一对象；设置类、设置 helper 及其依赖继续在此实际定义/解析 |
| `tests/test_home_workspace_module_compatibility.py`（新增） | 新旧导入顺序、导出、真实定义/设置 globals、父子归属与翻译的窄契约 |

一个 Home/Workspace 实施 owner 独占以上四个文件。不要给首页和工作区各派一个同时修改 `fluent_pages.py` 的 owner。主任务负责正式文档、源码 packaging 自检及集成汇报；本草案作者仅写忽略目录。`gui/pages/__init__.py` 保持仅导出 `TaskCenterPage`，MainFrame 保持原 import 和构造位置。

## 导入与真实定义

`home.py` 不导入 `fluent_pages` 或 `workspace_containers`；`workspace_containers.py` 不导入 `fluent_pages` 或 `home`。后者从既有 `workspace_features` 导入 `WorkspaceFeatureHost`、`WorkspaceRoute`，不复制二者。依赖清单与源行见 `design-notes.md`。

旧模块使用静态导入，必要时写成 `from .home import HomePage as HomePage` 以声明重导出。禁止模块 `__getattr__`、`__setattr__` 转发、运行时 setattr 迁移方法、`sys.modules` 多目标代理、包装子类或修改类 `__module__` 来模拟旧定义。新类 `__module__` 自然为新实现路径；旧、新导入的 class 对象必须 `is` 相同。现有代码未发现对迁移类定义模块名的反射/序列化依赖，保留这一核实边界，不宣称第三方调用方已全部覆盖。

旧 `fluent_pages.__all__` 顺序和值保持：

```python
[
    "ActionCard", "ActionCardView", "AccentColorSettingCard", "ComboSettingCard",
    "DeviceContextCard", "GalleryPage", "HomePage", "SettingsPage",
    "WorkspaceAreaPage", "WorkspaceSectionPage",
]
```

新 `home.__all__` 为 `["ActionCard", "ActionCardView", "DeviceContextCard", "HomePage"]`；新容器模块 `__all__` 为 `["GalleryPage", "WorkspaceSectionPage", "WorkspaceAreaPage"]`。

保留 `_SettingsPathLabel`、`_SettingsContentLayout`、`SettingsPage`、`_LocalizedSwitchSettingCard`、`ComboSettingCard`、`AccentColorSettingCard` 的真实类定义与类体。设置依赖 `set_client_preference`、`invalidate_adb_path_cache`、`reset_adb_program_cache`、`clear_client_probe_cache`、`is_mica_supported` 必须仍由旧模块字典运行时解析。不得把旧替换测试统一改 patch 新路径来获得通过。

## 行为不变量

- `ActionCard.activated`、`DeviceContextCard.manageRequested/refreshRequested`、`WorkspaceAreaPage.routeChanged` 保持原 Signal 声明。键盘/鼠标激活仅调用一次原 callback；字体变化保持已有控件身份、焦点和布局。
- 首页保留所有快捷路由、`lambda route=key` 绑定、`_global_device_bar` 存在时隐藏局部设备卡、独立首页的设备按钮、横幅与 viewport mask。MainFrame 继续拥有 page/frame callback；不新建业务状态。
- Gallery 的 `scroll=True/False` 与传入 scroll area 的重用保持；True 分支沿用显式 `show()`，False 分支保留原隐藏状态，不新增显示行为。实施前原类刻画已确认此差异。WorkspaceSection 的滚动 wrapper、透明背景、正文 margin 与 reset 行为不变。
- WorkspaceArea 继续以 `WorkspaceRoute` 保存稳定位置，queued/pending route 保留未消费 payload，首次真实 activate 后不回放；无效 section/feature 不切页、不激活；activate/deactivate 幂等和会话不 dispose 的语义不变。
- 所有 QObject parent、layout 接管、字体绑定槽和持有对象关系原样迁移，不引入新 timer/worker/全局缓存。页面销毁仍由现有宿主和 Qt 承担。
- 所有文案继续调用 `gui.i18n.tr`，其固定 context 是 `ADBLab`；不存在因 Python 定义模块变化需要重建 qm 的理由。保留 objectName、accessibleName/Description 与原文案。
- 保留 Gallery 来源/许可声明：两个新模块文档说明源自原 Gallery 移植并指向 `THIRD_PARTY_NOTICES.md`；不修改资源许可或词库。

## 验收与验证范围

先补新路径兼容测试，再完整迁移 7 类。以旧路径继续运行现有 Home/Workspace 行为测试，避免把既有消费者全部改为新路径而失去兼容证明。新测试单独从新路径导入，证明真实实现可直接使用。

直接集合为新兼容文件、`test_home_banner.py`、`test_page_layout.py`、`test_workspace_route_payload.py`；Workspace host、MainFrame 构造替换及设置 globals 的关联测试精确选节点，详见计划。不整跑设置排版、主窗布局或全部功能簇。若已有相同代码基线的新鲜结果，主任务可复用，并在记录中明确出处。

静态核对迁移前后 7 个 ClassDef 与保留设置 ClassDef 的 AST 一致（忽略行号），作为一次性迁移审计，不把 AST 全文匹配变成长期测试。Ruff、中文注释检查、相关 Pyright（新模块类型导出需核对）及 diff 检查按实际文件运行。

主任务仅在集成后集中运行源码 packaging 自检，必须通过子进程 `env` 将 `LOCALAPPDATA`、`XDG_CONFIG_HOME` 指向新临时目录，避免 `.self_check` 进入真实用户目录；不得把该环境写进全局配置。源码自检不等价于 PyInstaller 产物、真实桌面、高 DPI 或设备验证。

实施完成后由主任务最小同步 `MODULE_MAP.md` 的顶层页面/工作区实现路径、`UI_IMPLEMENTATION.md` 首页与容器链接，以及路线图/阶段记录；设置文档仍指旧实现。无需改变业务路由表、数据流或架构所有权事实。正式文档检查由主任务运行。

## 主任务执行裁定

预审通过，详细裁定保存于本阶段忽略目录builder-check.md；本节与正式计划中的补充裁定优先。
