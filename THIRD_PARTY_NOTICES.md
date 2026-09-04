# 第三方代码与许可说明

本文件记录 ADBLab 仓库内直接依赖或随源码移植的主要第三方组件。具体分发义务以组件随附的
许可文本为准；构建产物应同时携带本文件和相应许可文件。

## PySide6-Fluent-Widgets

ADBLab 运行时依赖 `PySide6-Fluent-Widgets`。早期页面组织曾参考上游仓库默认 PyQt5 分支
提交 `356665d9db87090db43305b98ac6cde2071d8f4d` 中的 Gallery 示例；该来源只用于保留
历史改写归属，不能作为当前 API 依据。当前行为应依次以本项目代码和测试、活动解释器安装的
包、上游官方 [PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)
中的单个相关文件为准，仓库不保存 `reference/` 副本。

上游项目采用 GNU General Public License v3.0，并提供商业许可选项。许可文本见
[上游 LICENSE](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/356665d9db87090db43305b98ac6cde2071d8f4d/LICENSE)。
分发应用或构建产物前，必须选择并遵守适用的 GPL-3.0 或商业许可条款。

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

`resources/icons/` 包含 Phosphor Icons Regular SVG 图标集，并由 ADBLab 的主题图标加载器进行
颜色替换。Phosphor Icons 采用 MIT License；来源和许可文本见
[`resources/icons/LICENSE.txt`](resources/icons/LICENSE.txt)。仓库历史没有记录导入时的精确
上游发布版本，因此不得在长期文档中推断具体版本号。

## scrcpy 与 Android 平台工具

`scrcpy-win64/` 包含 Genymobile [scrcpy](https://github.com/Genymobile/scrcpy) 的 Windows
运行文件以及随包提供的 ADB 组件。scrcpy 的 Apache License 2.0 文本随附在
[`scrcpy-win64/LICENSE.txt`](scrcpy-win64/LICENSE.txt)。正式分发前仍需按实际制品清单核对
其中 Android 平台二进制及动态库的各自许可和 notice 文件。

## ChkBugReport

`resources/chkbugreport-0.5-215.jar` 的 manifest 入口为
`com.sonyericsson.chkbugreport.Main`，对应 Sony Mobile 已归档的
[ChkBugReport](https://github.com/sonyxperiadev/ChkBugReport) 项目。当前仓库尚未保存能与该
预编译 JAR 精确对应的官方许可文本和源码版本，因此不能把它标记为已完成分发合规；该缺口记录在
[`RISKS_AND_DEBT.md`](docs/project-knowledge/RISKS_AND_DEBT.md)，发布前必须闭环。
