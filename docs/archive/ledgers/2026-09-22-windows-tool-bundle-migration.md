# Windows 工具目录迁移实施方案

> **For agentic workers:** 使用 superpowers:executing-plans 按任务实施；独立审查可并行进行。勾选框只在取得对应验证证据后更新。

**Goal:** 移除源码库中的 `scrcpy-win64/`，由准备脚本生成 `runtime-tools/windows-x86_64/`，保持 Windows 源码运行与发行包的 ADB、投屏能力。

**Architecture:** 复用现有平台工具清单、准备脚本和资源解析接口。Windows 官方 ZIP 与 Linux tar.gz 仅在解压分支不同；应用运行时不下载，发布包携带当前平台的完整工具。

**Tech Stack:** Python 3.11、标准库 urllib/zipfile/tarfile/hashlib、现有 safe_extract_zip、pytest、PyInstaller。

**Spec:** 本任务中已讨论的 Windows 工具迁移目标，具体边界以本文“范围与验收目标”为准。实现与本机自动化验证已完成；Windows 原生运行验收仍待对应环境。

## Global Constraints

- 接续当前工作树的 Linux 适配改动；执行前重新检查差异，保留所有已有修改，不提交、推送或改写 Git 历史。
- 固定 scrcpy/server 4.1；迁移不升级 ADB、DLL、生产依赖或应用版本。
- 完整保留官方包内容及许可证，不只复制两个 exe，也不只复制 required_files。
- 外部 ZIP 使用 [safe_extract_zip](../../../utils/archive.py)；不修改其应用恢复、bugreport 等其他消费者。
- 保持 Python 3.11、Windows x64/Linux x86_64 的当前支持范围；macOS/ARM 继续使用系统工具。
- 保持源码、onedir、onefile 路径规则；用户数据与 onefile 缓存继续使用既有用户目录。
- 保持自定义 ADB 路径和 bundled/runtime_cache 配置语义，不做设置迁移、旧缓存清理或启动时下载。
- 测试遵循 [增量验证策略](../../guides/TESTING_GUIDE.md#增量验证策略)，不重跑整个历史脏工作树的验收。

## Review Focus

1. 首次准备、离线 ZIP、损坏 ZIP 的行为不同；校验失败不得开始发布文件，CLI 失败必须阻断构建。由任务 1 的 ZIP 与 CLI 回归覆盖。
2. 有效目录应直接复用；--check 不联网、不创建、不修复。由任务 1 的网络禁止替身和目录快照覆盖。
3. 复制期间遇到 Windows 文件占用，允许报告失败并重试，不能宣称整包原子替换或回滚。由任务 1 的复制故障注入及最终 Windows 原生检查覆盖。
4. 新目录多了一层 runtime-tools；源码、onedir、onefile 和 server 同目录关系都必须保持，测试不能受执行主机架构影响。由任务 2 的参数化路径及 backend 回归覆盖。
5. 移除旧文件后，新检出仓库仍能检查文档、准备完整工具和构建；第三方许可证链接不能依赖尚未生成的目录。由任务 3 的资源、文档和干净副本验收覆盖。

## 范围与验收目标

- 仓库不再跟踪旧目录的 16 个文件；生成的 Windows 工具位于已被 .gitignore 忽略的 runtime-tools 下。
- Windows 开发者先运行工具准备脚本，再运行 main.py；发行包用户不需要额外安装工具。
- 正常准备支持下载和 --archive；再次运行复用通过校验的文件；--check 只读验证现有文件。
- 打包收集当前平台工具，不能把 Windows 包混入 Linux 产物。
- 旧目录缺失时，内置 ADB 和 scrcpy 均解析到新目录；自检不能被系统 PATH 或旧缓存掩盖。
- 官方包准备、源代码路径和模拟打包测试可以在 Ubuntu 检查；Windows 可执行文件、DLL 加载及真实投屏必须由 Windows 环境验收。

## 代码审查结论

| 当前代码 | 已确认事实 | 实施结论 |
| --- | --- | --- |
| [tool_manifest.py](../../../utils/tool_manifest.py) | Windows 仍指向 scrcpy-win64，未配置 URL、SHA256、归档根目录 | Windows 清单必须补齐元数据并切换目录 |
| [prepare_runtime_tools.py](../../../scripts/prepare_runtime_tools.py) | 下载临时文件和解压分支固定为 tar.gz；CLI 未捕获 BadZipFile | 增加显式格式字段、ZIP 分支与正常失败处理 |
| [adb_resolver.py](../../../utils/adb_resolver.py)、[scrcpy_service.py](../../../services/remote/scrcpy_service.py) | 均使用 bundle.directory | 不重写解析逻辑 |
| [runtime_tools.py](../../../utils/runtime_tools.py)、[tool_check.py](../../../utils/tool_check.py) | 接受嵌套目录；自检校验文件、server 摘要及版本命令 | 保留逻辑，补新目录测试 |
| [packaging_manifest.py](../../../scripts/packaging_manifest.py) | 打包 source 和 destination 均取 bundle.directory | 清单改变即可传递到 spec 和 CLI |
| [build_app.py](../../../scripts/build_app.py)、[ADBLab.spec](../../../ADBLab.spec)、[CI](../../../.github/workflows/Build-exe.yaml) | 已按准备工具、构建 helper、构建应用的顺序执行 | 无需增加一套构建步骤或发布流程 |
| [adb_client_card.py](../../../gui/widgets/adb_client_card.py) | bundled/runtime_cache 已映射到当前实际来源 | 无需修改配置格式或 UI |

本轮只读探针已在内存中替换 Windows 清单目录，确认 ADB 候选、scrcpy 解析和打包资源都跟随新目录。临时归档探针确认共享 ZIP 解压器会在写文件前拒绝越界路径。

### 固定下载来源

- 官方包：[scrcpy-win64-v4.1.zip](https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-win64-v4.1.zip)。
- 官方摘要：[SHA256SUMS.txt](https://github.com/Genymobile/scrcpy/releases/download/v4.1/SHA256SUMS.txt)。
- SHA256：`5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db`。
- 根目录：`scrcpy-win64-v4.1/`；归档大小 11,305,298 字节。
- 上轮已核对 GitHub Release digest、官方摘要文件和实际下载摘要，一致。
- 与仓库的 16 个文件比较：15 个逐字节一致，VBS 仅 CRLF/LF 差异；二进制、DLL、server 和许可无本地功能定制。

### 失败与兼容边界

- 现有 copytree 发布并非整包原子更新：复制中途失败可能留下部分修复的文件；最后更新 receipt 不能当作完整回滚。
- 本轮保持“失败返回非零、构建停止、校验不通过、关闭占用程序后可重试”的契约。文件占用时不自动杀 ADB，也不新增目录切换或恢复系统。
- 多进程并发准备没有保证；额外旧文件也不会自动清除。本次固定版本、新目录迁移无需引入跨进程锁或版本升级清理。
- 有效目标会先被复用，因此此时 --archive 指向不存在文件也不会读取；不新增强制覆盖选项。
- onefile 新缓存自然位于 runtime/<APP_VERSION>/runtime-tools/windows-x86_64；旧缓存留存，不影响新路径。
- 自定义绝对 ADB 路径若指向旧目录，删除后应明确失效，由用户重新选择；不静默改写。
- helper 仍单独构建到 build/runtime-helpers；ZIP 准备不会生成 helper。scrcpy backend 继续用 exe 同目录 server，保留 4.1 白名单及 native 回退。

## Task 1：为准备脚本增加 ZIP 支持

**Files**

- 修改：utils/tool_manifest.py（只追加格式字段，此任务暂不切换 Windows 清单）。
- 修改：scripts/prepare_runtime_tools.py。
- 测试：tests/test_prepare_runtime_tools.py；Linux 既有回归保留在 tests/test_platform_tools.py。
- 复用：utils/archive.py，保持其公共实现不变。

**Interfaces**

- 保持 `prepare_bundle(bundle, *, root: Path, archive: Path | None = None, check_only: bool = False) -> Path`。
- ToolBundle 末尾追加 `archive_format: Literal["tar.gz", "zip"] = "tar.gz"`，保留现有位置参数含义与 Linux 默认行为。
- 新增内部 `_extract_bundle(bundle: ToolBundle, archive: Path, destination: Path) -> None`；调用方先验证 SHA256，再进入该函数。

- [x] **先补 ZIP 回归并确认失败。** 使用以下合成包夹具，不在单元测试中下载或执行 PE：

```python
def _windows_zip(tmp_path, *, omitted=(), extra=None):
    from dataclasses import replace
    from zipfile import ZipFile
    from utils.tool_manifest import WINDOWS_BUNDLE
    import hashlib

    archive = tmp_path / "offline-package.bin"
    contents = {name: name.encode() for name in WINDOWS_BUNDLE.required_files}
    contents.update({"scrcpy.png": b"png", "launcher.bat": b"echo test"})
    contents.update(extra or {})
    with ZipFile(archive, "w") as package:
        for name, content in contents.items():
            if name not in omitted:
                package.writestr("scrcpy-win64-v4.1/" + name, content)
    bundle = replace(
        WINDOWS_BUNDLE, directory="runtime-tools/windows-x86_64",
        url="https://example.invalid/pinned.zip", archive_format="zip",
        archive_root="scrcpy-win64-v4.1",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    return bundle, archive, contents


def test_windows_zip_offline_preparation_and_reuse(tmp_path, monkeypatch):
    from scripts import prepare_runtime_tools as prepare
    from unittest.mock import Mock
    import json

    network = Mock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr(prepare.urllib.request, "urlopen", network)
    bundle, archive, contents = _windows_zip(tmp_path)
    root = tmp_path / "project with spaces"
    target = prepare.prepare_bundle(bundle, root=root, archive=archive)
    for name, content in contents.items():
        assert (target / name).read_bytes() == content
    receipt = json.loads((target / ".bundle.json").read_text())
    assert set(receipt["files"]) == set(contents)
    assert prepare.prepare_bundle(bundle, root=root, check_only=True) == target
    assert prepare.prepare_bundle(bundle, root=root, archive=root / "absent") == target
    network.assert_not_called()
```

- [x] **实现按清单格式分派。** 在清单导入 Literal；格式字段追加到末尾。准备脚本使用 ZipFile/BadZipFile，直接运行脚本时仍先注入 ROOT，再导入 utils.archive。解压助手可按以下结构实现：

```python
def _extract_bundle(bundle: ToolBundle, archive: Path, destination: Path) -> None:
    from utils.archive import safe_extract_zip

    if bundle.archive_format == "zip":
        with ZipFile(archive) as package:
            safe_extract_zip(package, destination)
        return
    if bundle.archive_format != "tar.gz":
        raise ValueError("不支持的工具归档格式")
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        for member in members:
            output = destination / member.name
            if (not output.resolve().is_relative_to(destination.resolve())
                    or not (member.isfile() or member.isdir())):
                raise ValueError("工具归档包含不安全成员 (archive)")
        package.extractall(destination, members=members, filter="data")
```

下载临时名称改为 download.archive；不根据离线文件扩展名猜测格式。保留摘要校验、临时解压、必需文件检查、整包复制、最后写 receipt 的顺序。CLI 异常组加入 BadZipFile；I/O 错误提示包含检查目录权限、关闭占用工具后重试，不宣称已回滚。

- [x] **补下列确定失败场景并验证输出。**

| 输入/故障 | 断言 |
| --- | --- |
| ZIP SHA 错误 | ValueError；事先记录的目标文件字节与 receipt 均未变化 |
| 正确摘要但缺 SDL3.dll，或 archive_root 错误 | 复制目标前失败，目标不变 |
| 成员名 ../../outside | ValueError；目标外文件和前置正常成员均未落盘 |
| 文件内容为非 ZIP，摘要按该内容计算 | main 返回 1、stderr 有工具准备失败，目标不存在 |
| 准备后删除 DLL、修改 server 或写坏 receipt | --check 失败且目录快照不变；网络替身调用次数为 0 |
| copytree 故障注入：写入一个文件后抛 PermissionError | main 返回 1、无新 receipt；--check 失败；解除故障后再次准备并检查成功 |

CLI 测试通过替换 prepare.ROOT 和 utils.tool_manifest.get_tool_bundle 指向合成包隔离仓库；复制故障只发生于 tmp_path。原有构建测试继续断言准备步骤失败不会调用后续 helper/PyInstaller。

归档失败用例必须使用尚未准备或已经损坏的目标；有效目标会按复用契约直接返回，不读取 --archive。目录快照只记录合成测试文件，不扫描用户数据。

- [x] **运行直接测试。**

```bash
.venv/bin/python -m pytest -q tests/test_prepare_runtime_tools.py tests/test_platform_tools.py tests/test_build_app.py
```

预期 ZIP 新测试通过，Linux tar、SHA、权限及链接拒绝回归继续通过。此任务不运行真实构建。

## Task 2：切换 Windows 清单并验证实际消费者

**Files**

- 修改：utils/tool_manifest.py。
- 更新契约：tests/test_ci_contracts.py、tests/test_build_app.py、tests/test_remote_services.py、tests/test_runtime_tools.py。
- 补充回归：tests/test_platform_tools.py。
- 关联检查：utils/adb_resolver.py、services/remote/scrcpy_service.py、utils/tool_check.py；默认无需生产逻辑改动。

**Interfaces**

- 沿用 get_tool_bundle(platform=None, machine=None) -> ToolBundle | None。
- 沿用 bundled_tool_path(bundle_dir, *relative_parts, verify_tree=False) -> str。
- 新目录值在清单单一来源维护；调用方不新增 Windows 路径常量。

- [x] **先添加固定清单断言，再修改 Windows 配置。**

```python
def test_windows_bundle_is_pinned_to_generated_zip():
    from utils.tool_manifest import get_tool_bundle
    bundle = get_tool_bundle("win32", "AMD64")
    assert bundle.directory == "runtime-tools/windows-x86_64"
    assert bundle.archive_format == "zip"
    assert bundle.archive_root == "scrcpy-win64-v4.1"
    assert bundle.sha256 == "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"
    assert bundle.url == (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v4.1/scrcpy-win64-v4.1.zip"
    )
```

WINDOWS_BUNDLE 使用关键字明确填写新目录、URL、SHA256、archive_root 与 archive_format；保留已有 adb/scrcpy 文件名、required_files、scrcpy_version 和 server_sha256。Linux 版本和摘要不变。

- [x] **更新真实消费者的旧目录断言。** 更新 spec/CLI 资源集、Windows scrcpy resolver 调用参数、由 bundle 参数构造的 ADB 缓存路径期望。平台测试显式固定 machine 为 x86_64/AMD64，避免测试运行主机决定结果。

- [x] **给路径测试增加新嵌套目录。** 参数化 Windows 源码、onedir、onefile 用例；Linux 继续由现有回归及真实产物自检覆盖。旧目录保留为通用资源接口的样例。

必须断言：源码位于资源根/new-directory；onedir 位于 _internal/new-directory 且不创建缓存；onefile 位于用户缓存/new-directory 且复制同目录 DLL/server。旧目录不存在、PATH 为空时仍返回新路径；不执行真实 Windows 二进制。

- [x] **运行直接与关联测试。**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_platform_tools.py tests/test_runtime_tools.py \
  tests/test_adb_resolver.py tests/test_build_app.py tests/test_ci_contracts.py \
  tests/test_remote_services.py::test_scrcpy_service_resolves_bundled_windows_executable \
  tests/test_remote_services.py::test_scrcpy_service_resolves_path_scrcpy_on_non_windows
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_scrcpy_backend.py::test_fast_plan_binds_only_scrcpy_child_environment \
  tests/test_scrcpy_backend.py::test_unsupported_launch_selects_native_before_any_process
```

关联 backend 的原因是 server 路径必须继续与 exe 同目录；保留现有 bundled/runtime_cache 别名、显式客户端无静默回退测试。只有这些检查暴露真实问题时，才调整对应消费者。

## Task 3：迁移文档、移除旧文件并完成平台验收

**Files**

- 删除：scrcpy-win64/ 中已核验的 16 个受 Git 跟踪文件；执行前复查文件没有新增修改。
- 清理已无消费者的常量：utils/runtime_tools.py 的 WINDOWS_TOOL_BUNDLE、scripts/packaging_manifest.py 的 WINDOWS_DATA。
- 当前文档：docs/guides/BUILD_AND_RUN.md、docs/guides/ADB_FAST.md、THIRD_PARTY_NOTICES.md。
- 目录排除说明：ruff.toml、scripts/check_source_text.py、scripts/check_comment_language.py、tests/test_source_text.py；按新 runtime-tools 目录更新。
- 协作说明中的当前目录示例：AGENTS.md、.dsh/skills/adblab-verify/SKILL.md，仅更新工具目录名，保留授权与验证规则。

**Interfaces**

- .gitignore 已覆盖 /runtime-tools/，无需再加 Windows 专项规则。
- build_app、spec 和 CI 保持现有准备顺序与失败退出码。
- 普通运行入口保持 main.py；发行包不引入下载依赖。

- [x] **先准备完整新包。** 使用清单指定的官方下载与 SHA256，在临时目录解压后准备到已忽略的新目录；校验全部 16 文件及 receipt，并与旧目录逐文件比较。确认新路径测试不依赖旧目录。
- [x] **更新使用说明与许可链接。** Windows 首次开发运行增加准备命令，说明 --archive/--check；保留 helper 的独立构建说明。许可证文档链接使用上游固定 v4.1 来源，避免指向未生成的 runtime-tools 文件；发行包仍携带实际 LICENSE.txt。
- [x] **移除旧跟踪文件及无消费者常量。** 不删除用户缓存，不修改自定义设置，不运行 Git 历史清理或暂存/提交命令。迁移后的 Git 差异应只有预期旧文件删除和相关改动。
- [x] **审查剩余引用。** 真实消费者不得指向旧目录。保留诊断/脱敏路径样例、Linux 不选择 Windows PE 的负例及历史记录；不把全文匹配为零作为验收标准。官方归档名 scrcpy-win64-v4.1.zip 仍然有效。
- [x] **执行文档与静态检查。**

```bash
.venv/bin/python -m ruff check utils/tool_manifest.py utils/runtime_tools.py \
  scripts/prepare_runtime_tools.py scripts/packaging_manifest.py \
  scripts/check_source_text.py scripts/check_comment_language.py \
  tests/test_platform_tools.py tests/test_runtime_tools.py tests/test_build_app.py \
  tests/test_ci_contracts.py tests/test_remote_services.py tests/test_source_text.py
.venv/bin/python -m pyright utils/tool_manifest.py scripts/prepare_runtime_tools.py
.venv/bin/python scripts/check_comment_language.py utils/tool_manifest.py \
  utils/runtime_tools.py scripts/prepare_runtime_tools.py scripts/packaging_manifest.py
.venv/bin/python -m pytest -q tests/test_source_text.py
.venv/bin/python scripts/check_doc_links.py
.venv/bin/python scripts/check_source_text.py
git diff --check
.venv/bin/python main.py --self-check packaging
```

若实际少改或多改文件，同步收窄或补齐静态检查参数。最终整合时只重跑因本任务新改动而受影响的用例；上一任务未改变的结果不重复验证。

- [x] **检查干净源码副本。** 副本排除旧 scrcpy-win64、runtime-tools、build、dist 和用户配置；文档检查及 build_app --dry-run 应通过且不联网；完成准备及 helper 构建后再进行源码打包自检。不要用 git clean 清理当前工作树。
- [ ] **在 Windows 验证真实运行。** 使用项目 .venv，先执行 scripts/prepare_runtime_tools.py 及 --check；已有合格包下重复准备不下载。模拟工具占用只使用自有测试进程，释放后验证重试成功。构建 Windows onedir 和 onefile，分别执行产物 --self-check packaging，并在工具不在 PATH、无网络时重复自检。源码与产物实机检查投屏启动、停止及重新启动。

Windows 构建命令（执行阶段在 Windows 项目环境运行）：

```powershell
./.venv/Scripts/python.exe scripts/prepare_runtime_tools.py
./.venv/Scripts/python.exe scripts/prepare_runtime_tools.py --check
./.venv/Scripts/python.exe scripts/build_app.py --name ADBLab-win-onedir --onedir
./dist/ADBLab-win-onedir/ADBLab-win-onedir.exe --self-check packaging
./.venv/Scripts/python.exe scripts/build_app.py --name ADBLab-win-onefile --onefile
./dist/ADBLab-win-onefile.exe --self-check packaging
```

## 交付与未验证项

交付时汇报：新增 ZIP 准备能力、目录及开发步骤变化、删除文件范围、实际测试命令和结果、Windows 实机与设备验证状态。当前 Ubuntu 的静态检查和路径替身只能证明代码与资源契约，不能替代 Windows PE/DLL、文件锁、Qt 窗口或设备联调。

## 执行记录（2026-09-22）

- ZIP 新回归先确认 12 项失败，再修复通过；新 Windows 路径契约先确认 6 项失败，再通过。
- 已准备并核对官方 Windows 包，删除旧目录的 16 个文件；Linux 工具目录及包版本保持不变。
- 用户追加并确认宿主文案：Windows / Ubuntu / macOS 下自动选择，其他 Linux 显示 Linux。
  已修改客户端卡片折叠摘要及自动推荐行，保留 ADB 客户端探测、执行环境检测、忙态和手动选择；
  三种语言词条及编译资源已同步，离屏折叠/展开截图检查通过。
- 最终整合 264 项测试通过，覆盖准备脚本、资源/路径、客户端刷新、Qt 执行环境、翻译及展开布局。
  输出含现有 SciPy/Qt 第三方弃用警告；未运行全量。
- 修改范围 Ruff、生产路径 Pyright、中文注释、源码文本完整性、文档链接及 git diff --check 通过。
- 干净源码副本没有旧工具目录、runtime-tools 或 build：文档检查、构建预览通过；只读工具检查
  按预期失败且未创建目录；离线准备与独立 helper 构建后，清空 PATH 的源码自检通过。
- 当前源码及新 Linux onefile 产物在清空 PATH、隔离配置/缓存后通过 --self-check packaging。
  Linux 构建仍报告宿主缺少 libxcb-cursor.so.0；X11 桌面运行需要该系统库。
- 独立代码审查未发现 P0–P2 问题。Windows 工具准备、摘要和模拟 Windows 路径已验证，
  未在 Ubuntu 执行 Windows PE；Windows DLL、原生文件锁及设备投屏仍未实测。
- 全部修改保留在当前工作区，未提交、推送或清理 Git 历史。

最终整合命令：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_prepare_runtime_tools.py tests/test_platform_tools.py tests/test_runtime_tools.py \
  tests/test_adb_resolver.py tests/test_build_app.py tests/test_ci_contracts.py tests/test_source_text.py \
  tests/test_remote_services.py::test_scrcpy_service_resolves_bundled_windows_executable \
  tests/test_remote_services.py::test_scrcpy_service_resolves_path_scrcpy_on_non_windows \
  tests/test_scrcpy_backend.py::test_fast_plan_binds_only_scrcpy_child_environment \
  tests/test_scrcpy_backend.py::test_unsupported_launch_selects_native_before_any_process \
  tests/test_adb_client_refresh.py tests/test_qt_adb_runtime.py tests/test_i18n.py \
  tests/test_settings_expand_animation.py
.venv/bin/python scripts/build_app.py --name ADBLab-linux-x64 --onefile
```

构建与自检实际使用独立临时 XDG_CONFIG_HOME/XDG_CACHE_HOME，产物验证另设置 PATH=/nonexistent；
未读取真实用户设置或发起设备操作。
