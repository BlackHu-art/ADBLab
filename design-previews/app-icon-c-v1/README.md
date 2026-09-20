# ADBLab C 版应用图标

用户选定“测试实验室”方向后的独立精修稿，2026-09-20。保留蓝色实验瓶、青色液面和白色终端符号；移除样板编号、展示底板和小图。

## 文件

- `adblab-icon-c.png`：1254 × 1254，带透明通道的生成原图。
- `adblab-icon-c.ico`：16、20、24、32、40、48、64、128、256 px，共 9 帧。
- `size-preview.png`：浅色/深色背景及实际小尺寸对照，使用 ICO 中读回的图像。
- `applied-titlebar-preview.png`：此前显示图标的标题栏方案预览；用户随后选择将标题栏品牌区域留空。
- `validation.json`：尺寸、读取验证和文件 SHA-256。

生成采用内置 imagegen。ICO 使用项目已安装的 Qt 缩放和 PNG 编码，再用 Python 标准库封装；未安装或升级依赖。ICO 目录、偏移、各帧 PNG 内容已检查，Qt 逐帧解码和 Windows LoadImageW 对全部 9 个尺寸均成功。

用户确认替换后，已将本目录 ICO 和 PNG 分别同步到根目录 `icon.ico`、`resources/app-icon.png`。按用户最新选择，主标题栏品牌区域留空，不显示名称或图标；系统窗口名称仍为 ADBLab，并保留新图标供任务栏使用；未修改依赖清单。

小尺寸预览用于判断轮廓、终端符号和明暗背景对比；重新启动源码应用后使用新图标，已有 EXE 的内嵌图标需下次构建更新，未执行安装包图标缓存验收。

## 最终生成提示词

使用此前 C 方案样板图作为图像参考，完整提示词如下：

```text
Refine the selected ADBLab app icon from the provided reference into ONE final standalone production-ready icon. The reference is a concept sheet; use ONLY its large blue laboratory flask with white terminal >_ symbol as the design reference. Preserve its recognizable wide Erlenmeyer flask silhouette, cobalt blue body, cyan liquid at bottom, short neck, softly rounded geometry, and white >_ terminal symbol. Remove the letter C, ALL miniature icons at the bottom, ALL display tiles, platform, cast ground shadow and backdrop. Output ONLY ONE flask icon, centered on a genuinely transparent alpha background, square high-resolution PNG. No text, no letters, no other objects. Use a calm polished Fluent desktop app aesthetic with refined shallow depth; reduce glossy glare and dark outlines compared to the reference. The flask must be visually bold, wide and balanced, with substantial terminal strokes, strong contrast and generous uncluttered interior. White terminal chevron and underscore should sit as one balanced group above the liquid; cyan liquid uses one simple shallow wave, no bubbles, no ticks. Crisp fully opaque silhouette with clean antialiased edges, absolutely no color fringe, blue haze, outer glow, stray pixels or scattered transparent artifacts. Subtle internal lighting only, no external shadow. Icon fills about 84% of canvas height and 78% of canvas width with transparent safety padding on all sides. The interior is solid opaque blue, not transparent glass. Keep all lines and spaces bold enough for small Windows taskbar sizes. Preserve the chosen design, only improve polish and extract a clean final icon.
```
