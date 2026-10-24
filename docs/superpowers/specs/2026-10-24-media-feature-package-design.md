# Screenshot 功能包目录设计

状态：已完成实施、独立任务审阅与最终综合审阅。延续已授权的目录调整、自主连续实施与并行工作，
不重新等待批准，不暂存或提交。本阶段只搬归属，不改变截图行为。实施见
[计划](../plans/2026-10-24-media-feature-package.md)。

## 目标、约束与方案

把 ScreenshotPage 与五个协作者归入 `gui/features/media/`，让图片会话的视图、操作、缓存和线程归属
在同一目录可见。Python 3.11 + PySide6，使用仓库 `.venv`，不增加依赖，不改 CI、发布、版本或用户数据。
保留公开入口、对象/Signal 身份、旧 patch 接缝、现有 UI、资源路径和平台行为。

已核对根 AGENTS、docs README、测试指南、架构/模块/业务流程、前批功能包和剩余 GUI 审计。
目标目录没有更近规则，六份迁移源当前没有未提交差异；其他在途成果均保留。

考虑的方案：

1. **采用：页面实际定义放在包 `__init__.py`，五个协作者作为 siblings，旧 dialogs 使用同模块 alias。**
   页面原本 eager 导入，模块名 `gui.features.media` 不变，方法的真实 globals 仍属于公开入口。
   这是本阶段负责人依据授权及现有替换语义作出的选择。
2. 页面搬到 `page.py` 后只重导出：旧入口里的 worker/关闭任务绑定不再控制页面的方法 globals，拒绝。
3. `page.py` 加动态模块代理：可补转发，但增加 setattr/解析机制，收益不足；禁止为目录形式引入代理。

前批功能包的延迟 `__getattr__` 不是本包要求。导入任一 media 子模块会先执行包入口并定义页面，
这是本阶段接受的 eager 行为，不要求“只导入 tasks 时不加载页面”。不新增功能、优化解码或重写状态机。

## 源与目标、精确导出

| 源路径 | 唯一实现目标 | 原定义，全部保留 |
| --- | --- | --- |
| `gui/features/media.py` | `gui/features/media/__init__.py` | `ScreenshotPage` 及所有原 globals；`__all__ = ["ScreenshotPage"]` |
| `gui/dialogs/screenshot_viewer_actions.py` | `gui/features/media/actions.py` | `ScreenshotViewerActions` |
| `gui/dialogs/screenshot_viewer_nav.py` | `gui/features/media/nav.py` | `ScreenshotViewerNav`、`MIN_ZOOM = 0.05`、`MAX_ZOOM = 5.0`、`ZOOM_STEP = 0.10` |
| `gui/dialogs/screenshot_viewer_tasks.py` | `gui/features/media/tasks.py` | `ImageKey = tuple[str, int, int]`、`ScreenshotIOShutdownTask`、`ScreenshotImageCache`、`ScreenshotReadWorker`、`ScreenshotDeleteWorker`、`ScreenshotValidateWorker` |
| `gui/dialogs/screenshot_viewer_ui.py` | `gui/features/media/ui.py` | `ScreenshotViewerUI` |
| `gui/dialogs/screenshot_viewer_widgets.py` | `gui/features/media/widgets.py` | `ScreenshotImageDelegate`、`ScreenshotFlipView`、`ScreenshotPipsPager`、`ScreenshotDetailsBar`、`_navigation_target` |

`media.py` 的内容迁至 `__init__.py`，不同时留下同名文件与包；五个旧 dialogs 文件保留为 shim。
不改变类构造参数、方法签名或信号。页面仍有 `dispose_ready = Signal(object)`、`back_requested = Signal()`、
`image_count_changed = Signal(int)`，`ScreenshotPage.__module__` 仍为 `gui.features.media`。
协作者类的 `__module__` 自然指向新模块，不通过伪造元数据保留旧值；旧路径可解析同一对象。

每个 shim 使用与前批相同的静态模式：

```python
import sys
from typing import TYPE_CHECKING

from gui.features.media import actions as _implementation

if TYPE_CHECKING:
    from gui.features.media.actions import ScreenshotViewerActions as ScreenshotViewerActions

sys.modules[__name__] = _implementation
```

示例省略的静态导出需按下表补齐。采用逐名 `X as X`，无星号导入；运行时 alias 保留完整属性面，
不得只复制类名。每对新旧模块及两侧父包属性必须为同一对象，任意导入顺序均成立。

| shim | `TYPE_CHECKING` 必须显式导出的名字 |
| --- | --- |
| actions | `ScreenshotViewerActions`、`ScreenshotDeleteWorker`、`ScreenshotValidateWorker`、`ProcessRunner`、`QImageReader`、`QFileDialog`、`QApplication`、`show_toast`、`os`、`sys` |
| nav | `ScreenshotViewerNav`、`MIN_ZOOM`、`MAX_ZOOM`、`ZOOM_STEP`、`ImageKey`、`ScreenshotImageCache`、`ScreenshotReadWorker`、`QImageReader`、`os` |
| tasks | `ImageKey`、全部五个类（shutdown/cache/read/delete/validate）、`QThread`、`QImage`、`raster_image_reader`、`os` |
| ui | `ScreenshotViewerUI` |
| widgets | 四个控件类及 `_navigation_target` |

实施者在修改前再用 AST 和消费者检索复核表；发现真实消费者需要其他静态名字时补充明确导出，不扩大公共 `__all__`。

## 内部依赖与真实 patch 接缝

内部导入精确调整：入口原五个 `gui.dialogs.screenshot_viewer_*` 改为 `.actions/.nav/.tasks/.ui/.widgets`；
actions/nav → `.tasks`；ui → `.widgets`；widgets 的 `TYPE_CHECKING` 页面引用改为 `from . import ScreenshotPage`。
没有函数内旧截图路径导入需要保留。`gui.dialogs.lifecycle.QThreadGroupShutdownTask` 是共享工具，留原位；
`gui.i18n`、通知、样式、widgets、`core.exec`、`utils.raster_image` 继续原绝对路径，不反向导入自身旧 shim。

已确认消费者：MainFrame 的 `_init_panels_steps()` 经 `gui.features.media` 导入页面并组装功能工厂；
`tests/screenshot_helpers.py`、截图、语言、排版、可访问性及工作区测试使用相同公开入口。
没有理由改这些调用者，更不能批量把旧测试入口改成新路径绕过兼容。

| 替换点与实际调用 | 已有消费者/回归证据 | 必须保持 |
| --- | --- | --- |
| 旧 nav 的 `QImageReader`、`ScreenshotReadWorker` → `_start_read()` | `test_screenshot_io.py`、`test_model_media_adb.py::test_screenshot_main_image_reuses_page_decode_cache` | 旧绑定在调用时传给实际 worker；当前图先读，邻图随后预读 |
| 旧 actions 的 `QImageReader`、`ScreenshotValidateWorker`、`QFileDialog` → `_add_images()` | `test_screenshot_io.py` 的添加成功/失败/取消；`test_screenshot_page.py` 的重入与弹窗关闭 | reader factory 作为参数传递，不移动为 tasks 的固定 reader |
| 旧 actions 的 `ScreenshotDeleteWorker` → `_start_delete()` | 删除快照、重复点击及同路径替换已有行为测试 | snapshot、versions 与页面 parent 原样传入 |
| 旧 actions 的 `ProcessRunner/os.name/sys.platform` → `_open_file_location()` | `test_model_media_adb.py::test_screenshot_page_opens_folder_via_process_runner` | 使用原平台命令及同一个受替换的 runner |
| 旧 tasks 的 `ScreenshotReadWorker.wait` | `test_screenshot_io.py::test_screenshot_supervisor_and_dispose_wait_for_native_join` | 页面与监督者读取同一真实类型，不提前确认完成 |
| 页面 globals 的 worker 类型、`ScreenshotIOShutdownTask` | `_start_io_worker()`、`_reap_io_workers()`、`register_shutdown_tasks()` | 保留页面真实 globals；类型分派和关闭构造均继续读取 `gui.features.media` |

`actions.os.remove` 的旧测试替换之所以生效，是标准库 os 对象共享；实际删除仍发生于 tasks。
不能把这当作 actions 直接删除的证据。新兼容测试需要验证旧 worker factory 真正被动作使用，
仅断言 `old_module is new_module` 或只检查 replacement 属性不够。

## 行为、生命周期与安全不变量

- 页面独占 `_workers`、`_add_worker`、`_delete_worker` 和像素缓存；缓存预算仍是 64 MiB，不引入全局缓存。
- queued 信号交付、`isFinished()`、`wait(0)`、结果消费、`deleteLater()` 顺序不变；shutdown 同样等待原生 join。
- 成功、失败、取消、重复启动、start 抛错、关闭与晚到结果路径原样保留；不阻塞 GUI，不变更 QObject parent。
- 删除只针对启动快照；新增图片、同路径 supersede/version、部分权限失败、取消剩余项和计数发布保持。
  仅临时测试文件可被测试删除，不接触真实图片。清除结果仍只释放会话，不删除磁盘图片。
- 隐藏页暂停解码、代次拒收、先发布当前图、旋转不改原图、完整像素复制、缩略图/分页/焦点/快捷键/溢出菜单保持。
- `raster_image_reader` 的栅格签名边界及受限格式保持，不能因移文件绕开 SVG 等不受信输入防线。
- `set_device_tools()`/`_release_device_tools()` 仍借用及归还原控件；截图页不拥有设备操作、录屏或控制器生命周期。
- MainFrame、controllers、models、共享生命周期、测试夹具、配置 schema、路径 provider 和资源不改。

六份源未使用 `__file__`/目录层级推断资源。移成包后的 `__file__` 会改变，但不新增路径计算。
入口及 shim 全为静态 import，PyInstaller 可分析；不改 spec 或 `scripts/packaging_manifest.py` 的收集规则。
源码 import probe 和 packaging self-check 不是冻结产物验证。

## 验收与并行交接

最小直接基线为 `test_screenshot_page.py` 与 `test_screenshot_io.py`，实现后加兼容测试及定向关联节点，
精确命令见计划。先确认红测试因新包缺失而失败，再迁移，不给既有行为添加人为失败条件。
新 GUI 用例显式 `@pytest.mark.ui` 并使用 `qt_application`；子进程导入顺序测试不创建 QWidget。
不得修改 `tests/conftest.py` 来登记本阶段文件。

Media owner 独占新包、旧六源的迁移和新 `tests/test_media_module_compatibility.py`；
Settings owner 可并行实施但不共同改这些文件。MainFrame、conftest、共享 docs/路线图由主任务持有；
实施者只提交交接证据，主任务串行同步当前架构与模块地图中旧 media 文件路径。
本轮仅交付三份设计文件，独立 builder check 由主任务安排，然后才启动实现。
不默认全量 pytest、PyInstaller 构建、真实 GUI/高 DPI/剪贴板平台及设备验收；没有新视觉行为不构成这些验证已通过。
