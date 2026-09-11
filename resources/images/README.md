# 首页横幅资源来源

`gallery_header.png` 原样复制自 PyQt-Fluent-Widgets 的 Gallery 示例，未裁剪、压缩、重绘或调色。

- 来源项目：zhiyiYo/PyQt-Fluent-Widgets，官方 PySide6 分支。
- 核实提交：`d6f5a01f7f3fe285c6900e476349467810267839`。
- 原始路径：`examples/gallery/app/resource/images/header1.png`。
- 原始文件：https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/d6f5a01f7f3fe285c6900e476349467810267839/examples/gallery/app/resource/images/header1.png
- 引用位置：同提交 `examples/gallery/app/view/home_interface.py` 的 `BannerWidget`，Qt 资源名为
  `:/gallery/images/header1.png`。
- 尺寸：1921 × 1203，PNG，含透明通道；文件大小 722579 字节。
- SHA-256：`f372b0da602d18b8d8ed3c1c824eafc5522d80504842c31523836cb67867d0b9`。
- 许可依据：来源仓库根目录的 GPL-3.0 `LICENSE`，原文保存在
  [LICENSE.gallery.txt](LICENSE.gallery.txt)。来源副本未提供该图片单独的许可或作者说明，
  此处不推断其他归属；项目级说明见 [第三方许可说明](../../THIRD_PARTY_NOTICES.md)。

原 Gallery 将完整图像缩放至横幅矩形。ADBLab 沿用完整源图到完整横幅的坐标映射，横幅高度仍随
快捷卡片换行；不按长宽比裁掉图案或另留空白。绘制直接使用原图，不创建逻辑分辨率中间图，
也不创建随窗口尺寸或 DPI 累积的缩略图缓存。
