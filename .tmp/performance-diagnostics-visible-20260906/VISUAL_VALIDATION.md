# 性能诊断常显：三场景视觉核对

日期：2026-09-06。独立视觉核对后由主任务修正换列条件，并重新渲染三个相同场景。

## 方法与范围

`render_diagnostics.py` 创建真实 MainFrame，使用完整 fake AppSettings、内存 RunLibrary、隔离用户目录和合成设备名；CommandRunner.run 被禁止调用。截图来自本窗口 `QWidget.grab()`，没有截图桌面或其他应用，没有执行 ADB / Monkey / 性能采集。

已加载项目中文或英文译文、Windows 本地字体。三个场景的当前脚本均正常退出（exit 0），实际 DPR 分别为 1 / 1 / 1.25。记录字段默认显隐、祖先包含、从滚动两端到达字段、标签换行高度、单位文字宽度、字段相交、横滚和滚动条净空；并逐张用 view_image 查看三个 `*-diagnostics.png`。

```powershell
.\.venv\Scripts\python.exe -u -X faulthandler .tmp/performance-diagnostics-visible-20260906/render_diagnostics.py light
.\.venv\Scripts\python.exe -u -X faulthandler .tmp/performance-diagnostics-visible-20260906/render_diagnostics.py dark-large
.\.venv\Scripts\python.exe -u -X faulthandler .tmp/performance-diagnostics-visible-20260906/render_diagnostics.py english-125
```

## 当前结果

| 场景 | 窗口逻辑尺寸 | UI 字号 / DPR | 诊断布局 | 横滚 | 滚动条净空 |
| --- | --- | --- | --- | --- | --- |
| 浅色中文 | 1100×1000 | 12pt / 1 | 三列同排，区块 956×86 | 0 | 19px |
| 深色中文窄窗 | 860×1000 | 22pt / 1 | 两列，区块 716×233；全部标签单行，同排输入对齐 | 0 | 19px |
| 浅色英文 | 1100×1000 | 12pt / 1.25 | 三列同排，区块 956×86 | 0 | 19px |

共同通过：三个诊断字段默认可见；所有标签高度满足实际换行要求；`min` 单位完整；字段不相交；可滚动到全部字段；结构区保持透明且输入框自有底色保留；没有横滚或控件压住右侧滚动条。原始测量分别在 `light.json`、`dark-large.json`、`english-125.json`。

## 视觉复核后修正

首版深色窄窗 22pt 在可用宽度 716px 时仍保留三列，每列仅 230–231px，第三个输入框因标签换行比其他字段低 36px。原始图与数据保存在 `dark-large-before-reflow.png` 和 `dark-large-before-reflow.json`。

最终诊断网格按“结束后拉取的设备日志”的当前译文和字体测量最小列宽；默认网格行为保持。深色大字号改为两列，每列 352px，第一行两个输入均在 y=88，第二行设备日志位于 y=187，所有标签均单行。长关键字仍可通过输入框自身水平阅读。常规浅色与英文 125% DPI 重新渲染后维持原三列布局。

## 产物

- `light-top.png` / `light-diagnostics.png`
- `dark-large-top.png` / `dark-large-diagnostics.png`
- `english-125-top.png` / `english-125-diagnostics.png`
- 三份对应 JSON 与本目录复验脚本。

技术备注：初版临时脚本曾把兄弟 QWidget 传给 `mapTo()` 测滚动条距离，引发脚本测量时的 native 访问异常；已改为映射到双方共同祖先 QScrollArea，再完成上述三场景。此异常来自临时探针，不作为生产缺陷或成功验证记录。没有运行 pytest，主任务负责其直接/关联测试汇总。
