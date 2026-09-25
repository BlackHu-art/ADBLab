# 第三方代码与许可说明

本文件记录 ADBLab 仓库内直接依赖或随源码移植的主要第三方组件。具体分发义务以组件随附的
许可文本为准；构建产物应同时携带本文件和相应许可文件。

## PySide6-Fluent-Widgets

ADBLab 运行时依赖 `PySide6-Fluent-Widgets`。早期页面组织曾参考上游仓库默认 PyQt5 分支
提交 `356665d9db87090db43305b98ac6cde2071d8f4d` 中的 Gallery 示例；该来源只用于保留
历史改写归属，不能作为当前 API 依据。当前行为应依次以本项目代码和测试、活动解释器安装的
包、上游官方 [PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)
中的相关文件为准。经用户要求拉取的本地 `reference/` 副本受 Git 忽略，不作为运行或打包来源。

首页背景 [`resources/images/gallery_header.png`](resources/images/gallery_header.png) 原样复用
官方 PySide6 分支提交 `d6f5a01f7f3fe285c6900e476349467810267839` 的
[`examples/gallery/app/resource/images/header1.png`](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/d6f5a01f7f3fe285c6900e476349467810267839/examples/gallery/app/resource/images/header1.png)。
来源和文件摘要见 [`resources/images/README.md`](resources/images/README.md)；该上游副本附带
GPL-3.0 许可，未发现此图的独立许可声明。保留的完整文本见
[`resources/images/LICENSE.gallery.txt`](resources/images/LICENSE.gallery.txt)，该许可文本在构建时收集到
`licenses/gallery/`。运行与打包只读取仓库内的正式资源，不依赖 `reference/` 路径。

截图浏览参考官方 PySide6 分支提交 `d6f5a01f7f3fe285c6900e476349467810267839` 的
[`examples/view/flip_view/demo.py`](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/d6f5a01f7f3fe285c6900e476349467810267839/examples/view/flip_view/demo.py)
与 [`examples/menu/command_bar/demo.py`](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/d6f5a01f7f3fe285c6900e476349467810267839/examples/menu/command_bar/demo.py)。
ADBLab 直接引用已安装的 `HorizontalFlipView`、`HorizontalPipsPager`、`CommandBar` 和
`Action`，并沿用示例的 `FlipImageDelegate` 扩展方式适配整页原比例绘制、预览缩放和拖动。
适配层负责分页同步、尺寸变化与解码缓存释放；不复制示例图片或修改依赖包。
精确运行版本继续以 `requirements.txt` 为准。

上游项目采用 GNU General Public License v3.0，并提供商业许可选项。许可文本见
[上游 LICENSE](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/356665d9db87090db43305b98ac6cde2071d8f4d/LICENSE)。
分发应用或构建产物前，必须选择并遵守适用的 GPL-3.0 或商业许可条款。

## Segno 1.6.6

无线调试配对二维码使用 [Segno 1.6.6](https://pypi.org/project/segno/1.6.6/)，采用
BSD 3-Clause License。ADBLab 使用 `make_qr()` 生成标准 QR，并在内存输出 PNG；没有复制
上游实现代码，也没有为二维码新增图像运行依赖。

完整许可文本从该版本 wheel 的 `segno-1.6.6.dist-info/licenses/LICENSE` 原样保存至
[`resources/licenses/LICENSE.segno.txt`](resources/licenses/LICENSE.segno.txt)，打包收集到
`licenses/segno/`。固定版本上游文本见
[LICENSE](https://github.com/heuer/segno/blob/1.6.6/LICENSE)。

## MobilePerf

`mobileperf/` 是对 Alibaba
[mobileperf](https://github.com/alibaba/mobileperf) 的项目内移植版本。ADBLab 保留其采集与
报告内核，并调整了状态隔离、ADB 解析、子进程入口、线程收口和 Python 3.11 兼容性。当前只能
通过 ADBLab 的 `services/mobileperf_runner.py` 和 `main.py --mobileperf-worker --config`
边界运行，不能使用上游旧版 `run.bat`、`run.sh` 或安装脚本判断本项目行为。

MobilePerf 使用 MIT License；完整文本见 [`mobileperf/LICENSE`](mobileperf/LICENSE)。

## XlsxWriter 1.1.2

`mobileperf/extlib/xlsxwriter/` 是 MobilePerf 随附的 XlsxWriter 1.1.2 副本，用于生成 XLSX
报告。上游项目为 [XlsxWriter](https://github.com/jmcnamara/XlsxWriter)，采用 BSD 2-Clause
License；该版本许可文本见
[`mobileperf/extlib/xlsxwriter/LICENSE.txt`](mobileperf/extlib/xlsxwriter/LICENSE.txt)。

## Phosphor Icons

`resources/icons/` 包含 Phosphor Icons Regular SVG 图标集；当前设备轮廓复用其中的
`device-mobile.svg`，经 Fluent 扩展接口按主题着色。Phosphor Icons 采用 MIT License；来源和许可文本见
[`resources/icons/LICENSE.txt`](resources/icons/LICENSE.txt)。仓库历史没有记录导入时的精确
上游发布版本，因此不得在长期文档中推断具体版本号。

## scrcpy 与 Android 平台工具

Windows x64 与 Linux x86_64 的准备脚本使用 Genymobile 官方
[scrcpy 4.1 发行包](https://github.com/Genymobile/scrcpy/releases/tag/v4.1)，下载地址和 SHA256
固定于 `utils/tool_manifest.py`。生成目录分别为 `runtime-tools/windows-x86_64/` 与
`runtime-tools/linux-x86_64/`，均不纳入 Git；打包时收集当前平台的完整工具，包括 ADB、
配套 server 和上游许可文件。Linux 包内 ADB 为 37.0.0。

scrcpy 的 [Apache License 2.0 文本](https://github.com/Genymobile/scrcpy/blob/v4.1/LICENSE)
随 Windows 包保存在 `LICENSE.txt`，随 Linux 包保存在 `LICENSE`。正式分发前仍需按实际
制品清单核对其中 Android 平台二进制及动态库的各自许可和 notice 文件。

## ChkBugReport

`resources/chkbugreport-0.5-215.jar` 的 manifest 入口为
`com.sonyericsson.chkbugreport.Main`，对应 Sony Mobile 已归档的
[ChkBugReport](https://github.com/sonyxperiadev/ChkBugReport) 项目。当前仓库尚未保存能与该
预编译 JAR 精确对应的官方许可文本和源码版本，因此不能把它标记为已完成分发合规；该缺口记录在
[`RISKS_AND_DEBT.md`](docs/project-knowledge/RISKS_AND_DEBT.md)，发布前必须闭环。
