# Monkey 内部容器背景：隔离视觉验证

日期：2026-09-06。范围仅为应用与诊断页 Monkey 的测试目标、运行参数两处结构容器。
本子任务没有修改生产文件或测试，没有执行 pytest。

## 已确认来源

- 修前 `gui/panels/app_panel.py` 第 222、269 行分别创建 `monkey_package_card` 与
  `monkey_parameters_card`，类型为 `SimpleCardWidget`。
- 活动 `.venv` 的 `qfluentwidgets/components/widgets/card_widget.py` 第 115—116 行，
  `SimpleCardWidget._normalBackgroundColor()` 返回白色，浅色 alpha=170，深色 alpha=13；
  第 124—135 行 `paintEvent()` 自行绘制该背景与边框。
- 外层 `BasePanel._card()` 已创建 `ContentSection`；`gui/widgets/content_section.py` 第 22—25 行
  已绕过结构卡片自绘。因此最小修复为两个内部容器改成普通 QWidget，不需要改共享内容分区或主题。
- 当前修后两处位于 `gui/panels/app_panel.py` 第 221、268 行，原控件与布局保留。

## 隔离与采样方法

`render_monkey_surface.py` 使用真实 MainFrame、完整内存 AppSettings、临时用户目录、内存运行库和
模拟 ADBController；设备信息为合成单设备，禁止 `CommandRunner.run`，关闭扫描和 ADB 启动入口。
没有读取用户配置、没有设备截图、没有桌面截图。图像来自当前隔离 QWidget 的 `grab()`。

两种主题均使用 1100×1100 窗口、12pt 中文、offscreen 平台、DPR=1，mica_enabled=False。
本记录验证 Qt 容器合成背景，不声称验证了 Windows 原生云母材质或设备 Monkey 执行。

before 在独立进程中按原模块名加载本轮前字节副本 `app_panel.before.py`，不替换工作树文件。
副本 SHA256：`C1A9CE3042BA1691E2FDC0BBF14C1F956067B725A106B848494D103CD87CB803`。
after 使用当前生产模块。容器和控件采样点均通过滚动置入祖先视口，并检查其可见位置；
页面对照取同一合成图中 Monkey 左侧空隙，不误取卡片内部或边框。

## 结果

| 主题 | 对象 | 修前采样 | 修后采样 | 同图页面空隙 |
| --- | --- | --- | --- | --- |
| 浅色 | 测试目标空白 | #fbfbfb | #f3f3f3 | #f3f3f3 |
| 浅色 | 运行参数空白 | #fbfbfb | #f3f3f3 | #f3f3f3 |
| 深色 | 测试目标空白 | #2b2b2b | #202020 | #202020 |
| 深色 | 运行参数空白 | #2b2b2b | #202020 | #202020 |
| 浅色 | 事件数输入及获取按钮 | #fefefe | #fbfbfb | #f3f3f3 |
| 深色 | 事件数输入及获取按钮 | #373737 | #2d2d2d | #202020 |

输入和按钮自身背景仍与页面不同，交互边界保留。它们的最终合成像素随祖先白层移除而改变，
不应把“保留控件底色”误写为最终像素必须与修前完全相同。

两种主题修前、修后的测试目标尺寸均为 988×129，运行参数尺寸均为 988×546，事件数输入
466×30，获取按钮 130×33；四次正式渲染的横向滚动最大值均为 0。已通过 view_image 实际检查
四张 overview 对照图：两块外层底板与细边框消失，标签、方案栏、输入、按钮、异常复选框及
运行操作保留，未见本轮引入的裁切或横向溢出。

## 复验命令与产物

以下四个正式场景均 exit 0；before 曾因页面对照点位于卡片左边界而重采样，最终 JSON
已经修正为卡片外侧空隙，未更改生产实现。

```powershell
.\.venv\Scripts\python.exe -X faulthandler .tmp/monkey-surface-fix-20260906/render_monkey_surface.py before Light
.\.venv\Scripts\python.exe -X faulthandler .tmp/monkey-surface-fix-20260906/render_monkey_surface.py before Dark
.\.venv\Scripts\python.exe -X faulthandler .tmp/monkey-surface-fix-20260906/render_monkey_surface.py after Light
.\.venv\Scripts\python.exe -X faulthandler .tmp/monkey-surface-fix-20260906/render_monkey_surface.py after Dark
```

- 直观对照：`before-light-overview.png` / `after-light-overview.png`；
  `before-dark-overview.png` / `after-dark-overview.png`。
- 补充参数区域图：上述四个前缀的 `-parameters.png`。
- 几何与颜色数据：`before-light.json`、`before-dark.json`、`after-light.json`、`after-dark.json`。
- 脚本直接导入 GUI 测试构造器，因此终端可出现依赖原始 Tips 广告；它未走 main.py 启动 helper，
  此诊断脚本输出不代表正式启动广告修复回归。

本子任务未运行全量、真实设备操作、打包或原生云母测试；主任务负责新增像素回归和关联业务测试，
其结果另记 `VALIDATION.md`。
