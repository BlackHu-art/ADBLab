# 云母柔化的模拟材质视觉证据

所有图片由离屏 Qt 渲染本进程窗口生成；标题标有“模拟材质（非原生 DWM）”。
两种根底色为冷色 `#DCE5EF` 和暖色 `#E8E2DC`，它们代替 Windows 合成材质，只用于比较应用表面的遮色程度。
不能由这些图推断用户当前窗口 DWM 是否启用、壁纸采样或系统材质的真实效果。

隔离方式：临时 LOCALAPPDATA 和测试库路径、完整 fake AppSettings、模拟 ADBController；
设备基本信息和详细信息替换为空，禁用 bootstrap，CommandRunner.run 一旦被调用便抛出异常。
未抓取桌面或其他应用，也没有创建可见的原生测试窗口。

## 旧实现基线

`before-*.png` 与 `before-samples.json` 已在主任务修改遮罩和日志 token 前完成，不能用当前实现覆盖。
两个底色下三页空白阅读区均分别采得 `#EDF2F7`、`#F3F0ED`。

旧版 `focus` 图的目标为：设置页的主题 ComboBox、任务页搜索框、性能页包名输入框。
这些图未记录 hasFocus，只作为布局及输入控件焦点外观基线，**不作为正文阅读框聚焦前后的验证证据**。

## 调整后截图

等待正文阅读样式完成后，执行：

```powershell
.\.venv\Scripts\python.exe .tmp/mica-softening-20260906/render_material.py after
```

调整后改为实际聚焦任务摘要和性能日志；设置页仍聚焦主题 ComboBox。
每帧先激活 Qt 窗口，分别验证目标撤焦/聚焦状态；JSON 记录控件类型、可访问名称、hasFocus 与 activeWindow。
因为正文目标与旧版输入目标不同，正文无新增亮化应通过调整后的 rest/focus 帧直接比较，
旧版正文对照由主任务独立控件回归覆盖，不回退共享工作树。

两次运行的临时输出目录和日志时间可能不同；材质定量比较使用预先登记的空白取样点，避开文本和边框。

## 已完成的对照结果

设置、任务结果和性能三页的结果一致：

| 模拟底色 | 旧共享阅读层 | 新共享阅读层 |
| --- | --- | --- |
| `#DCE5EF` | `#EDF2F7` | `#E0E8F0` |
| `#E8E2DC` | `#F3F0ED` | `#EAE6E1` |

使用 RGB 通道绝对差之和衡量两底色的色差，输入差为 34；旧输出差为 18（52.94%），
新输出差为 27（79.41%）。三页所有 rest/focus 帧的共享阅读点均保持一致。
这是模拟背景影响的保留率，不是系统云母的“透明度百分比”。

调整后 12 帧均记录窗口激活状态为 true，目标 hasFocus 与请求状态一致。
其中任务摘要与性能日志共 8 帧，正文空白像素始终为 `#F2F4F6`，撤焦、聚焦和两种底色均不改变它；
正文控件前景调色板同为 `#000000`，前景与背景的 sRGB 相对亮度对比值在各帧保持一致。
完整数值见 `comparison.json`，原始点位和焦点状态见 `after-samples.json`。

已实际查看设置 rest、任务摘要 focus 和性能日志 focus 图片；文字、边界与蓝色焦点框均清楚，
性能日志和任务摘要在聚焦时也未出现大面积纯白底。
直观前后对照可用 `before-dce5ef-settings-rest.png` 与 `after-dce5ef-settings-rest.png`；
任务页可用 `before-e8e2dc-tasks-rest.png` 与 `after-e8e2dc-tasks-rest.png`，无需拼接或图像后处理。
