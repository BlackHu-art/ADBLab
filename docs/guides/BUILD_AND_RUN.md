# 构建与运行

本页只记录当前可执行的安装、运行、检查和构建方式。所有命令默认在项目根目录执行。

## 环境要求

| 项目 | 要求/状态 | 依据 |
| --- | --- | --- |
| Python | 3.11 为 README 与 CI 标准版本 | `README.md`、`Build-exe.yaml` |
| 语法兼容目标 | 静态检查与格式配置目标为 Python 3.10 | `ruff.toml`、`pyproject.toml` |
| 主平台 | Windows；精确版本兼容矩阵待确认 | README；Windows 内置 adb/scrcpy；CI 未覆盖 OS 版本矩阵 |
| GUI | PySide6；精确版本见依赖清单 | `requirements.txt` |
| ADB/scrcpy | Windows/Linux x86_64 提供内置工具；其他平台使用环境工具；macOS 补充默认 SDK 与 Homebrew 路径发现，具体顺序见下文配置 | `utils/adb_resolver.py`、`services/remote/scrcpy_service.py` |
| 可选工具 | aapt 用于 APK 解析；Java 用于 chkbugreport JAR | `models/adb_app.py`、`models/adb_testing.py` |

## 安装

仓库内开发环境统一命名为 `.venv`。在 Windows PowerShell 中创建环境并安装完整开发工具链：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

依赖按用途逐层包含：

- `requirements.txt`：PySide6、PyYAML、psutil 等应用运行依赖。
- `requirements-build.txt`：包含运行依赖，并增加 PyInstaller。
- `requirements-dev.txt`：包含构建依赖，并增加 pytest、Ruff、coverage、pytest-cov、
  pytest-xdist、pre-commit 和 pyright。
- `constraints.txt`：由 `requirements.txt` 引入，固定 Python 3.11 / Windows 已验证环境的活动
  依赖闭包，包括构建 hooks 和开发工具的传递依赖；它只约束版本，不改变三个安装入口的范围。
  更新依赖时同步更新约束并验证对应安装入口、`pip check` 与受影响测试。该快照不包含制品哈希，
  也未锁定 macOS 独有依赖，不将它称为所有平台的完整锁文件。

Fluent Widgets 使用同版本的 `[full]` 依赖，提供覆盖导航菜单的 Acrylic 模糊能力；NumPy、
SciPy、Pillow 与 ColorThief 的版本由 `constraints.txt` 固定。安装基础包时上游仍可导入，
但覆盖菜单会退回实色。补齐依赖后须重新启动应用，模块导入时缓存的能力状态才会更新。

只运行源码时可以改装 `requirements.txt`；执行本地打包时安装 `requirements-build.txt`。开发、
测试和提交前检查统一安装 `requirements-dev.txt`。项目没有根级 `setup.py`/`setup.cfg`、
Poetry、PDM 或 npm 构建入口。

虚拟环境提示：若 venv 由 `uv venv`（未加 `--seed`）等工具创建，环境内可能没有 pip 模块，
PyCharm 等 IDE 执行 `pip install -r requirements.txt` 时会报 `No module named pip`。此时运行
`.venv\Scripts\python.exe -m ensurepip --upgrade` 补种 pip 即可。

## 配置

- 不需要在仓库内创建普通运行配置。首次读取后，AppSettings 会把旧 `resources/app_settings.json` 迁移到用户配置目录。
- Windows 用户数据根默认是 `%LOCALAPPDATA%\ADBLab`；具体由 `utils/user_data.py` 决定。
- 默认保存目录由 `AppSettings.save_directory` 返回；未配置或目录不存在时使用用户主目录下 `ADBLab`。
- ADB 解析器按平台和架构门控：Windows x64 使用 `runtime-tools/windows-x86_64/adb.exe`，Linux x86_64 使用
  `runtime-tools/linux-x86_64/adb`；依次尝试当前平台内置工具、`ADB_PATH`
  环境变量、Android SDK platform-tools（`ANDROID_HOME`/`ANDROID_SDK_ROOT`/`%LOCALAPPDATA%\Android\Sdk`）、
  再尝试 PATH；macOS 额外尝试 `~/Library/Android/sdk/platform-tools/adb`，随后检查
  `/opt/homebrew/bin/adb` 和 `/usr/local/bin/adb`，当前架构的标准 Homebrew 前缀优先。
  macOS 和未提供内置包的架构使用环境工具，不执行其他平台二进制。
- 解析结果在进程内缓存，包含明确缺失结果；应用执行要求可用绝对路径，缺失时直接失败，
  不交给裸命令名重新搜索 PATH。设置页「重新检测」清空解析与执行两层缓存，并作废客户端
  探测缓存；安装或移除 platform-tools 后无需重启应用。重检合并、持久输入退休和子进程
  路径冻结契约见 [ADB_FAST](ADB_FAST.md#应用内自动选择)。
- 普通启动会后台检测默认本机 ADB 服务，为受支持短命令选择执行方式；设置页的执行模式只在
  当前运行生效。支持范围、恢复和自定义服务环境的处理见 [ADB_FAST](ADB_FAST.md#应用内自动选择)。
- 设置页「ADB 维护 → 客户端」可固定使用的 ADB 客户端，配置键 `adb_client` 默认 `auto`
  （按上述解析顺序）；取值也支持命名来源
  （`bundled`/`runtime_cache`/`env`/`PATH`/`homebrew_arm64`/`homebrew_x64`，
  SDK 来源 `sdk_home`/`sdk_root`/`sdk_local`/`sdk_macos` 仍被接受）或绝对路径；
  `bundled` 与 `runtime_cache` 兼容源码和 onefile 间的内置选择，不迁移用户设置。
  界面只列出内置与环境来源，Android SDK 位置仍在自动链里兜底。切换时清空解析与短命令两层
  缓存并重新检测；所选客户端缺失时按选择如实失败，不会静默改用其它 adb。
  自动选项及折叠摘要显示宿主系统，如「Windows 下自动选择」「Ubuntu 下自动选择」
  「macOS 下自动选择」；其他 Linux 发行版或发行版信息不可读时显示 Linux。自动模式的摘要按命令执行边界
  已选定的绝对路径显示来源与已有版本；SDK 等未列出的候选仅显示缩略路径，悬停可查看完整路径；未找到可执行
  文件时提示检查安装环境。切换客户端后后台刷新摘要，不改变原有选择优先级。该名称只说明当前桌面环境，
  不改变下方执行环境的能力检测、测速及后端选择。
- Remote 非空 `SCRCPY_PATH` 显式覆盖 scrcpy 路径，支持 `~` 和相对文件路径；该值是单个文件路径，
  不能附加启动参数。无效覆盖会报错，不会静默回退。未配置时优先使用当前平台内置 scrcpy；
  Linux 内置包未准备时及未提供内置包的平台使用 PATH；macOS 最后检查两个 Homebrew 标准前缀。
  主应用启动 MobilePerf 和 scrcpy 时分别冻结
  `ADB_PATH` / `ADB` 子进程环境；所选 ADB 缺失会在启动前失败，详情见
  [Remote 投屏与输入](ADB_FAST.md#remote-投屏与输入) 与 [MobilePerf 采集进程](ADB_FAST.md#mobileperf-采集进程)。
- 开发控制台的输出级别由 `console_log_level` 控制（默认 `DEBUG` 保留现状，可选
  `INFO`/`WARNING`/`ERROR`/`OFF`）；环境变量 `ADBLAB_CONSOLE_LOG_LEVEL` 优先于配置，
  启动时读取、只影响源码运行的控制台，界面与诊断落盘不受影响。
- Remote 的 `scrcpy_*` 表单键通过 `core/settings_manager.py::SCRCPY_SETTING_DEFAULTS` 白名单
  纳入 `DEFAULTS`，可跨会话保存与恢复；主应用不再读取任何外部服务配置。

## 启动

### Windows 本地开发

使用项目 Python 3.11 虚拟环境安装依赖后，首次运行先准备当前平台工具。准备脚本下载
官方 `scrcpy-win64-v4.1.zip`，校验固定 SHA256 后安全解压到
`runtime-tools/windows-x86_64/`；该生成目录不进入 Git：

```powershell
./.venv/Scripts/python.exe scripts/prepare_runtime_tools.py
./.venv/Scripts/python.exe main.py
```

离线准备及只读校验：

```powershell
./.venv/Scripts/python.exe scripts/prepare_runtime_tools.py --archive C:/downloads/scrcpy-win64-v4.1.zip
./.venv/Scripts/python.exe scripts/prepare_runtime_tools.py --check
```

Windows 包完整保留 ADB、scrcpy/server、DLL、图标、启动辅助文件与许可证。准备脚本先复用
通过校验的现有目录；此时不读取 `--archive`。复制失败会停止构建，且可能留下部分修复的文件，
不保证整包回滚；工具被占用时关闭相关程序后重试。应用运行时不下载，发行包继续内置完整工具。
如果自定义 ADB 路径仍指向旧的 `scrcpy-win64/`，需在客户端设置中重新选择；命名的「应用自带」
选择会自动使用新目录。独立 helper 的构建与 native 回退见下文 [scrcpy 专用 ADB 入口](#scrcpy-专用-adb-入口)。

### Linux 本地开发

使用 Python 3.11 的项目虚拟环境安装 `requirements.txt`（开发测试使用 `requirements-dev.txt`），
随后准备工具并启动。PyCharm 等 IDE 使用同一 `.venv/bin/python`，不需要修改系统 PATH：

```bash
.venv/bin/python scripts/prepare_runtime_tools.py
.venv/bin/python main.py
```

准备脚本按共享清单下载官方 `scrcpy-linux-x86_64-v4.1.tar.gz`，校验 SHA256 后安全解压。
包内为 scrcpy/server 4.1 和 ADB 37.0.0；文件及准备清单位于 Git 忽略的 `runtime-tools/`，
再次准备会校验已存在文件并复用。可以离线准备或只读校验：

```bash
.venv/bin/python scripts/prepare_runtime_tools.py --archive /path/to/scrcpy-linux-x86_64-v4.1.tar.gz
.venv/bin/python scripts/prepare_runtime_tools.py --check
```

应用启动时不联网下载工具。当前二进制已在 Ubuntu 24.04 x86_64 验证版本命令，要求 glibc 2.35
及 libudev 等系统库；实际桌面显示、USB 权限与设备授权仍需按部署环境验证。Linux ARM/macOS
未交付内置包，需要兼容的系统 ADB/scrcpy。Windows 开发环境按上一节准备工具。
完整产物打包与自检可使用：

```bash
.venv/bin/python scripts/build_app.py --name ADBLab-linux-x64 --onefile
.venv/bin/python scripts/check_build_artifacts.py frozen --executable dist/ADBLab-linux-x64 --timeout 60
```

Ubuntu 的 Qt X11 启动需要系统动态库，CI 使用的完整安装清单见 [Build 工作流](#build-工作流)。
其中 Xvfb/xauth 用于没有桌面的验收环境。可分别验证源码与产物，显示依赖缺失会返回失败：

```bash
QT_QPA_PLATFORM=xcb timeout 15s xvfb-run -a .venv/bin/python main.py --self-check gui
QT_QPA_PLATFORM=xcb timeout 15s xvfb-run -a ./dist/ADBLab-linux-x64 --self-check gui
```

`--self-check gui` 创建最小窗口并运行一次事件循环，不加载主窗口、用户设置或设备业务；
不强制离屏模式。它验证 QPA 插件启动，不能代替实际桌面、Wayland、高 DPI 和设备功能验收。

### macOS 工具发现

macOS 发行包不内置 ADB/scrcpy。终端 PATH 已配置的工具继续优先；从 Finder 启动时，
程序也能发现上述默认 SDK 和 Homebrew 路径。安装或移除 ADB 后在设置页重新检测；
特殊位置的 scrcpy 可在启动环境中指定 `SCRCPY_PATH`。双架构安装时分别显示 Homebrew 来源，
不能用来源标签代替真实可执行性和版本检查。

GUI 启动命令来自 README，并由 `main.py` 入口确认：

```powershell
.\.venv\Scripts\python.exe main.py
```

内部/诊断子模式：

```powershell
.\.venv\Scripts\python.exe main.py --self-check packaging
.\.venv\Scripts\python.exe main.py --mobileperf-worker --config <由 MobilePerfRunner 生成的配置路径>
```

第二条是内部 worker 入口，正常用户应通过左侧“性能采集”页启动，不应手写含真实设备/包信息的配置并提交到仓库。
另有 `core/native_process.py` 调用的内部 `--adblab-native-launch` 模式，用于隔离原生工具启动环境，
不作为日常运行命令。

设置页手动更新检查的状态和重试规则见
[应用更新检查](../project-knowledge/BUSINESS_FLOW.md#11-应用更新检查)。源码和产物的
`--self-check packaging` 同时检查 QtNetwork 可导入及 TLS 后端可用，保持离线执行；它不能
证明实际 HTTPS 握手、代理或目标网络可达。验收产物时还需从设置页显式检查，并验证检查中关闭。

同一自检的 `ui:acrylic` 项检查覆盖磨砂的图像依赖是否可用，缺失时返回失败；自检不截取屏幕。
图像模糊及导航绘制由相关 Qt 回归测试验证，实际桌面效果仍需人工检查。
Windows spec 保留 `unittest` 和 `pydoc` 标准库，当前 NumPy/SciPy 图像处理链在运行时会导入
它们；排除会让覆盖磨砂退回实色并导致 `ui:acrylic` 自检失败。
无线配对增加 Segno 运行依赖；同一自检验证导入、内存 PNG 生成及 Qt 解码，并检查随包的
BSD-3-Clause 许可文本。该自检不访问设备；真正的扫码发现、手机授权和无线连接需使用
Android 11+ 手机按[连接流程](../project-knowledge/BUSINESS_FLOW.md#2-连接设备与读取信息)验收。

设置页的“显示缩放”支持跟随系统、100%、125%、150%、175%、200%，写入正式键 `ui_scale`，
重启应用后生效。GUI 入口在创建 QApplication 前应用手动比例；跟随系统保留系统 DPI 和外部启动环境。
自检和 MobilePerf worker 不应用 GUI 比例。窗口内容仍按实际可用宽高重排，缩放不改变屏幕分辨率。
字体沿用已保存的族和字号（pt），默认 12 pt；可选 11 pt 获得更紧凑的界面，输出文本字号单独配置。

设置页的“语言”支持跟随系统、简体中文、繁體中文和 English，保存后重启生效。云母效果在
Windows 11 上即时切换；不支持的系统禁用该开关并使用主题实色。离屏 Qt 测试验证透明层合成与
主题切换，桌面最终材质仍需在 Windows 11 实机观察。

应用翻译源文件在 `resources/i18n/`；历史页面混用中文和英文源文案，简中、繁中、英文均安装
应用词库。修改 `.ts` 后，用项目环境提供的 Qt 工具更新 `.qm` 和静态导入的
`gui/generated/translations_rc.py`：

```powershell
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.zh_CN.ts -qm resources/i18n/adblab.zh_CN.qm
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.en_US.ts -qm resources/i18n/adblab.en_US.qm
.\.venv\Scripts\pyside6-lrelease.exe resources/i18n/adblab.zh_HK.ts -qm resources/i18n/adblab.zh_HK.qm
.\.venv\Scripts\pyside6-rcc.exe --compress-algo zlib --compress 9 --threshold 0 resources/i18n/translations.qrc -o gui/generated/translations_rc.py
```

资源压缩显式固定为 zlib，避免生成器默认使用 Zstd 后，缺少 Zstd 支持的 Windows Qt 无法解压词库。
资源随 Python 模块进入现有 PyInstaller 构建，无需安装目录可写，也不依赖运行时读取参考项目。
源码与产物的 `--self-check packaging` 同时实际加载三种语言的内嵌词库；词库回归测试核对 `.ts`、编译资源
和格式占位符一致性。语言设置及显示值与业务值的边界见 [DATA_FLOW](../project-knowledge/DATA_FLOW.md#设置字段)。

遇到 `source code string cannot contain null bytes` 或 UTF-8 解码失败时，先运行
`.\.venv\Scripts\python.exe scripts/check_source_text.py` 确认受影响范围。该检查只报告路径和
错误类别，不尝试猜测编码或覆盖文件。翻译生成模块可由有效词库重新生成；其他源码应从确认可读的
版本或备份恢复，并保留原内容用于追溯。

## 测试与检查

日常修复按 [TESTING_GUIDE 的增量验证策略](TESTING_GUIDE.md#增量验证策略) 选择直接和受影响模块
测试；只有测试指南列出的全量触发条件成立时，使用
[完整门禁命令](TESTING_GUIDE.md#完整门禁命令)。dev 推送 main 本身不触发本地全量测试，
`pytest --collect-only` 只用于发现和选择测试。

`compileall` 与 Ruff、测试导入和 Pyright 的职责重复，还会生成 `__pycache__`，不属于默认门禁；
只有排查明确的解释器编译问题时才对具体目标临时运行。`git diff --check` 应在本次修改全部完成后执行。

Ruff 的规则、排除项和逐文件例外只以 `ruff.toml` 为准。

## 本地 PyInstaller 构建

### scrcpy 专用 ADB 入口

源码运行前可用现有构建依赖生成轻量 CLI：

```powershell
.\.venv\Scripts\python.exe scripts/build_scrcpy_adb_bridge.py
& .\build\runtime-helpers\adblab-adb-bridge\adblab-adb-bridge.exe --self-check
```

构建只写项目 `build/`，使用 console onedir 保留标准流并避免逐命令解压；不安装系统工具。
入口源码摘要不匹配或缺少构建时，源码 Remote 选择原生兼容模式。`ADBLab.spec` 自动先构建该入口，
CI 同样先构建再收集整个 `runtime-helpers` 目录。`--self-check packaging` 要求入口存在，
并离线调用其自检确认标准输出与退出码；因此源码执行打包自检前也需先完成此构建。
支持范围与会话清理见 [ADB_FAST](ADB_FAST.md#remote-投屏与输入)。

### 应用图标读取工具

`resources/app-icon-helper.jar` 是随应用携带的应用元数据与图标 DEX 工具，源码位于
`tools/app_icons/Main.java`。设备端通过 `app_process` 临时执行，读取当前 Android 用户下的
应用图标，或通过 `--metadata` 模式批量读取应用名称、版本和缓存身份；不安装 APK，
不要求 root，主机运行应用时也不需要 Java 或 Android SDK。
设备不支持相关框架接口时，图标保留占位；元数据仅在明确不支持时使用有界兼容查询。
两种模式共用临时部署和清理边界，协议、取消与缓存行为见
[应用管理流程](../project-knowledge/BUSINESS_FLOW.md#3-应用管理与安装批次)。

只有修改 Java 源码时才需要重新生成此资源，需要完整 JDK（脚本只校验 `javac`/`java` 是否存在，
不校验 JDK 版本）、Android SDK platform 33 和 build-tools 33.0.2；工具不会自动下载这些开发组件：

```powershell
.\.venv\Scripts\python.exe scripts/build_app_icon_helper.py --sdk <Android-SDK目录> --java-home <JDK目录>
.\.venv\Scripts\python.exe scripts/build_app_icon_helper.py --check
```

`--check` 不需要 JDK/SDK，检查 DEX 和内嵌源码摘要；摘要规范化换行以兼容 Windows 检出。
编译目标为 Android API 23，使用新旧框架共有的用户上下文入口；实际设备覆盖范围以验证记录
为准，不将编译目标视为完整 Android 版本兼容性认证。修改资源收集时更新公共打包清单
`scripts/packaging_manifest.py`，并核对 `main.py --self-check packaging` 的资源验收项。

### 主应用构建

本页提供的 Windows spec 构建命令（`README.md` 只给出启动方式并指向本页）：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller ADBLab.spec --noconfirm --clean
.\.venv\Scripts\python.exe scripts/check_build_artifacts.py frozen --executable dist/ADBLab/ADBLab.exe --timeout 60
```

`ADBLab.spec`：

- 入口为 `main.py`。
- 通过白名单收集图标、`resources/images/gallery_header.png`、图库许可、迁移种子、Bugreport JAR、
  应用图标 DEX 工具、二维码、第三方许可、`icon.ico` 和当前平台工具目录，不把旧演示图或无关
  文档带入产物。
- 通过 hidden imports 收集全部 `mobileperf` 与 `qfluentwidgets` 子模块，不再把 `mobileperf/`
  源码目录作为 data 重复打包；运行配置由 `MobilePerfRunner` 临时生成。
- 生成 windowed、onedir 的 `ADBLab`。

完整 PyInstaller 构建会创建 `build/` 和 `dist/`。纯文档或不涉及打包边界的内部修改无需构建或
packaging self-check；触及启动入口、依赖、资源或运行时路径时执行源码自检。修改 spec、资源
收集或产物入口时，在已有打包授权范围内额外构建并验证实际产物。测试全量通过本身不触发构建。

## CI/CD

### Build 工作流

`.github/workflows/Build-exe.yaml` 在 `main` push 或手动触发时：

1. 从 `utils.app_metadata.APP_RELEASE_TAG` 读取版本，并确定是否发布：`main` push 自动发布；手动
   `workflow_dispatch` 默认 `publish=false`，只构建和上传 Actions artifacts。手动设为 `publish=true`
   时仅允许 `main`，其他分支明确失败。仅构建允许重复已有版本；发布模式提前拒绝已有远端 tag，
   并校验 `.github/release-notes/<tag>.md`：UTF-8 正文非空，首行为 `# ADBLab <tag>`，
   标题后必须有正文。缺失、空白或版本不符均在构建前失败；仅构建模式不要求发布说明。
2. 使用 Python 3.11 安装 `requirements-build.txt`（包含运行依赖和 PyInstaller）。Linux 在源码自检前
   通过 apt 安装 EGL、udev、X11/xcb 与 Xvfb/xauth 运行库，提供 Qt、设备访问与无桌面 GUI 探针所需环境；
   具体包清单以 [Build-exe.yaml](../../.github/workflows/Build-exe.yaml) 的 Linux 安装步骤为准。
   xcb 除光标库外还依赖 shape、randr、xfixes、ICCCM 和 X11 键盘等库，
   依据见 [Qt 6.8 X11 要求](https://doc.qt.io/qt-6.8/linux-requirements.html)。安装后对当前 Python 的
   `libqxcb.so` 执行 `ldd`，列出依赖并在出现 `not found` 时立即失败；仅安装 Python wheel 无法补齐系统库。
3. 准备当前平台工具。Windows 额外安装 `requirements-dev.txt`，运行 `python -m ruff check .` 和
   `python -m pyright`；编译发布工作流不执行 pytest。macOS/Linux 运行 source packaging self-check。
4. PyInstaller 构建 Windows onedir、macOS/Linux onefile。macOS 使用 `macos-15-intel` 构建 x64、
   `macos-15` 构建 arm64；Python 显式选择架构并核对 machine，helper 与主程序用 file/lipo 核对架构。
5. 三平台通过 `scripts/check_build_artifacts.py frozen` 显式等待产物退出并校验退出码，避免 Windows
   windowed EXE 被 shell 启动后直接放行。探针依次检查 packaging 自检、worker `--help` 的 `--config`
   输出，以及未知中文参数的 UTF-8 错误输出和退出码 2；每项运行超时为 60 秒，另给清理最多 2 秒，超时会尝试清理进程树，
   清理未确认也判失败。随包工具检查文件、可执行权限及版本命令，系统工具不参与兜底。
   Linux 额外对源码和产物运行有超时保护的 Xvfb/xcb GUI 探针，启用 `QT_DEBUG_PLUGINS` 记录插件加载失败原因；
   macOS 架构检查继续保留。
6. 压缩后只上传各任务的精确归档路径，包括 Windows x64、Linux x64、macOS x64 与 arm64。
7. 仅发布模式进入 Release job，单独使用 `contents: write`。下载失败即停止；
   `scripts/check_build_artifacts.py release` 要求恰好四个预期版本、路径的非空归档，并检查归档
   可读且含主程序；缺包、多包、错误版本或损坏均阻止发布。现存同版本 Release 或远端 tag
   仍会使发布失败，防止直接覆盖。Release 正文由 `gh release create --notes-file` 读取同版本说明，
   不再使用固定占位文案。发布完成后执行 "Retain latest 5 version tags"，删除超出最新 5 个的旧版本 tag 及其
   Release；被保留策略删除的历史版本不再受“存在性检查”保护，但仓库版本规则仍禁止复用版本号。

工作流默认权限为 `contents: read`，使用的第三方 Actions 固定到已核验的 40 字符 commit SHA。
全部任务设置 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`，避免 Windows runner 的默认代码页使中文日志输出失败。
CI 通过 `scripts/build_app.py` 生成 PyInstaller CLI 参数，和本地 `ADBLab.spec` 共用
`scripts/packaging_manifest.py` 的资源及子模块白名单。平台产物名、onefile/onedir、windowed
与图标选择仍由 workflow matrix 决定；`--dry-run` 只显示命令，不构建或写入产物。
CLI 生成的 spec 位于 `build/app-spec`，资源、入口及图标路径按仓库根解析，避免默认名称
`ADBLab` 覆盖受控的根目录 spec；生成文件不进入版本控制。
CLI 与本地 spec 在构建前运行工具准备脚本，任一准备步骤失败即停止构建。onefile 继续把工具复制到
稳定的用户缓存运行；缓存缺失时补齐文件，丢失可执行权限时修复权限，保留仍在运行的有效工具文件。

`runtime-tools/` 不从 Git checkout 获取，也不要求手工上传；每个构建任务运行
`scripts/prepare_runtime_tools.py`，按 `utils/tool_manifest.py` 的固定下载地址与 SHA256 准备：

| 构建平台 | 工具来源 | 生成目录 |
| --- | --- | --- |
| Windows x64 | Genymobile/scrcpy 的 v4.1 Release：`scrcpy-win64-v4.1.zip`，包含 ADB、scrcpy/server、DLL 与许可 | `runtime-tools/windows-x86_64/` |
| Linux x64 | 同一 Release：`scrcpy-linux-x86_64-v4.1.tar.gz`，包含 ADB、scrcpy/server 与许可 | `runtime-tools/linux-x86_64/` |
| macOS x64 / arm64 | 不生成内置工具包；运行时发现用户安装的兼容工具 | 无 |

只有校验通过的已有工具目录可复用；网络、摘要或准备过程失败会停止构建。生成目录不进入 Git，
资源收集只带入当前平台工具。应用运行时不联网下载；macOS 安装与发现方式见
[macOS 工具发现](#macos-工具发现)。

发布集合的目录结构由四个 Actions artifact 名称决定。下载后可在项目根目录离线核验：

```bash
python3 scripts/check_build_artifacts.py release --directory release_artifacts --version vX.Y.Z
```

将 `vX.Y.Z` 替换为实际版本。该命令只用 Python 标准库，不需要安装应用依赖。`frozen` 检查使用
项目构建环境，并需要其中的 psutil 来清理子进程；它验证启动、打包与标准流，不连接真实设备，
不能代替 Windows/macOS 原生运行、桌面交互及投屏实机验收。

CI 侧只保留 Build（编译发布）与 Retention Audit（手动只读审计）两个工作流；Build 在推送 main
或手动触发时执行文本完整性、Windows 静态检查、三平台构建与产物自检，并在依赖安装及源码导入前
检查文本完整性。CI 不运行 pytest，测试由开发者按 [测试指南](TESTING_GUIDE.md) 在本地选择执行；
pip 缓存按系统与架构隔离，同时考虑 requirements 和 constraints 的变化。

### 提交版本规则

- `utils/app_metadata.py` 是版本号唯一事实来源。
- `APP_VERSION` 仅在准备将 dev 代码推送到 main 分支时递增一次（默认补丁 +1），普通本地与 dev
  提交不主动递增版本号。
- 每次发布随版本提交 `.github/release-notes/<tag>.md`，其中 `<tag>` 为 `APP_RELEASE_TAG`。
  首行写 `# ADBLab <tag>`，后续正文记录实际改动、下载选择及必要的使用限制；使用 UTF-8，
  不把未执行的实机或平台验收写成已通过。说明文件供该版本 Release 使用，后续版本新增对应文件。
- 推送 main 成功后，应将已发布的 main 同步回日常本地开发分支，优先采用快进同步；同步前检查
  工作区，保留已有未提交修改，不得覆盖。本地同步沿用已发布版本，不再次递增版本号。
- 主版本和次版本只按明确的发布计划调整；当前值直接读取 `utils/app_metadata.py`。
- 不允许把多次推送共用一个版本，也不允许只修改 README、工作流或发布标签中的派生版本。
- 推送前应先比较上次推送时的版本，确认本次版本已递增；本地验证继续按增量策略选择，推送 main
  本身不触发本地全量测试。发布验收按完整门禁执行；CI Build 只执行静态检查、打包和产物自检。

### Auto-Clean 工作流

`.github/workflows/Auto-Clean.yaml` 已改为手动只读的 **Retention Audit**：只列出 workflow runs
和 releases，不带 schedule、不删除 run/release/tag，权限为 `actions: read` 和 `contents: read`。
真正的保留期删除若未来需要，必须另行设计审批和保护环境。

## 调试方法

- 普通 ADB 失败：packaging self-check 可确认依赖与打包资源存在，Windows/Linux 还执行内置工具
  版本命令；它不验证设备连接。继续查看任务中心“本次操作”的错误详情及设置页 ADB 维护状态；
  实时采集内容保留在对应功能页，归属见 [OPERATION_RESULTS](OPERATION_RESULTS.md)。应用自身异常在设置页导出诊断。
- 设备扫描：检查 `continuous_device_scan` 和 `device_scan_interval_ms`；原生扫描在有活跃
  CommandRunner 命令时跳过本轮，快速扫描不受该忙碌判断阻塞。能力恢复检查在忙碌判断前提交，
  细节见 [ADB_FAST](ADB_FAST.md#应用内自动选择)。
- Remote：观察预检 warning、scrcpy stderr/FPS 状态；先检查显式 `SCRCPY_PATH`，
  再按平台检查内置包、PATH 或 macOS Homebrew；确认工具匹配宿主架构且有执行权限。
- MobilePerf：使用左侧“性能采集”页的日志与结果目录；停止先写 `mobileperf.stop`，默认最多等待
  90 秒供报告收尾，再尝试终止进程；未确认退出时保留运行状态，不能将停止请求视为退出成功。
- 高并发/关闭问题：重点检查功能页 `request_dispose()`、Workspace 会话 registry、TaskSupervisor、
  `ProcessRunner` 全局进程表和 QThread 是否仍运行；瞬态表单再单独检查 `closeEvent`。

## 常见问题

| 问题 | 已确认原因/处理 |
| --- | --- |
| 找不到设备 | ADB 不可用、设备未授权/offline、网络 target 不完整；连接目标必须含 port |
| APK 信息解析失败 | `aapt` 不在 PATH 或 APK 不存在 |
| bugreport 转换失败 | Java 或 JAR 不可用；保留原始输出再排查 |
| Remote 提示 scrcpy 不可用 | 检查 SCRCPY_PATH；Windows/Linux x86_64 检查准备后的工具包，macOS/其他架构需兼容的系统工具 |
| Linux 提示无法加载 xcb 插件 | 检查实际缺失的系统库；缺少 libxcb-cursor.so.0 时安装 libxcb-cursor0，再运行 GUI 自检 |
