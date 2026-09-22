# 2026-09-22 项目文件与文档核对（归档）

本报告记录基于 `5897d64` 工作树进行的文件用途检查、文档校准与清理。任务开始时工作树干净，
Git 跟踪文件共 2068 个。清单检查覆盖跟踪文件；正文核对重点是当前知识库、运行与测试指南、
仓库技能及其代码入口，不表示逐行审计全部业务实现。

当前事实以[知识库入口](../../README.md)和代码为准；本报告不作为后续任务的门禁清单。

## 清理与保留

- 删除 `ADBModelCore._fetch_device_info()` 这一失效私有实现。检查了直接调用、字符串引用、
  handler 映射、MRO、反射入口和相关测试，未发现当前消费者。设备信息读取已由
  [设备信息模块](../../../models/adb_device.py) 中的 `_fetch_basic_properties()`、
  `get_device_overview_info()` 和 `_read_info_command()` 承担。
- 未发现证据充分、可以直接丢弃的完整业务文件。空的 `mobileperf/extlib/__init__.py` 是包标记；
  构建与校验脚本仍有消费者；许可、ADR 和设计预览保留。设计预览中的重复图像具有方案与图标
  验收追溯用途，没有仅凭哈希相同删除。
- 未清理忽略目录中的虚拟环境、缓存、构建产物、IDE 配置和本地参考资料，也未改动运行时工具、
  平台二进制与图标资源。

下列实施记录由 `docs/superpowers/plans/` 移入 `docs/archive/ledgers/`，逐一与原文件进行
内容哈希核对，正文完全一致；归档索引同步更新：

| 记录 | 归档原因 |
| --- | --- |
| [ADB 执行链](../ledgers/2026-09-08-adb-execution-gaps.md) | 已执行的查询取消、能力验证、截图与采样实施记录 |
| [多系统兼容性](../ledgers/2026-09-22-cross-platform-compatibility.md) | 保存当时的实现和验证结果，现状已由知识库维护 |
| [Windows 工具包迁移](../ledgers/2026-09-22-windows-tool-bundle-migration.md) | 保存目录迁移与清理证据，当前准备方法由构建指南维护 |

归档不代表完成原记录中尚未执行的平台或设备验收。相关缺口继续由
[风险账本](../../project-knowledge/RISKS_AND_DEBT.md)维护。

## 文档校准

- 以启动分派和原生进程实现核对内部参数，将旧的 `--native-launch` 修正为
  `--adblab-native-launch`。
- 以 CI、打包配置和工具解析器核对平台说明：Windows/Linux x64 使用内置 ADB/scrcpy，
  macOS 发现外部工具；根 README 补充新检出源码的工具准备入口。
- 以 scrcpy 启动计划核对 direct 模式的准入条件，说明不满足条件的计划仍使用选定的原生 ADB。
- 以翻译安装、自检实现和测试补充资源生命周期、加载失败诊断与内嵌词库验证；仓库 i18n 技能
  移除重复的旧生成命令，指向显式使用 zlib 的[构建指南](../../guides/BUILD_AND_RUN.md)。
- 校正仓库技能中的结果身份、关闭顺序、ADB 发现说明、测试路径和 PowerShell 编码表述。
- 风险账本移除已删除私有方法的条目，修复表格断行，并区分 MobilePerf 顶层受监督 worker 与
  子进程内 Monkey/logcat 客户端的清理责任；未将待验收的收尾场景标为已解决。

## 当时的验证

本轮生产代码仅删除无消费者的设备信息旧入口，因此直接验证设备 model；文档调整验证链接、
frontmatter、源码文本与引用。未扩大到全量测试、GUI 或打包验收。

本机实际可用的项目解释器是 `venv\Scripts\python.exe`，没有 `.venv`；以下命令使用前者。
当前开发环境约定仍以[构建指南](../../guides/BUILD_AND_RUN.md)为准。

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q tests/test_model_device.py` | 删除前 23 passed；删除后 23 passed |
| `python -m ruff check models/adb_model.py` | 通过 |
| `python scripts/check_comment_language.py models/adb_model.py` | 通过 |
| `python scripts/check_doc_links.py` | 通过；包括新增本报告及归档目标 |
| 对 4 份仓库技能、设计预览说明、图片资源说明调用同一链接检查器 | 6 份文档通过 |
| `python scripts/check_source_text.py` | 通过 |
| 对文档中的显式 Python 路径与符号引用做 AST 核对 | 27 处引用涉及 20 个源文件，未发现缺失符号候选 |
| `git diff --check` | 通过 |
| 独立只读复核 | 删除入口和归档移动无新增问题；发现的文件尾空行已修正 |

链接检查不解析正文行为或标题锚点，静态引用核对也不能替代运行验收。本轮没有执行全量 pytest、
PyInstaller 构建、桌面视觉验收或真实设备操作；没有更改版本、依赖、CI/CD 或创建提交。
