# 本轮紧凑页面调整验证

范围：实时 Logcat 顶部两行、截图查看器嵌入页头去重、设备概览摘要与详情复制。
所有界面截图和设备/日志数据均为合成示例，没有额外查询真实设备。

## 已通过

- Logcat：`pytest -q tests/test_live_logcat_visual.py tests/test_model_meta.py`，44 项。
- 设备概览：`pytest -q tests/test_device_hub_page.py`，66 项；150% 缩放直接关联 9 项。
- 截图：`pytest -q tests/test_screenshot_page.py`，7 项；媒体关联 7 项。
- 字体与工作区：`test_loaded_feature_pages_refresh_fonts_and_text_constraints` 与
  `test_all_embedded_feature_pages_remain_reachable_on_short_workspace` 组合，2 项。
- 翻译：`tests/test_i18n.py`，28 项；业务页英文与应用语言检查 3 项。
- Logcat 150% 缩放两行布局/大字体可达性 5 项。
- 修改文件 Ruff、Pyright、中文注释、文档链接、差异空白检查通过。

## 未计为通过的检查

- 截图页 150% 缩放新增测试在断言结束后进程退出异常；离屏和 Windows 平台均复现。
  常规比例截图测试与真实主窗口渲染正常退出。
- 混合多页面字体测试单独运行时，pytest 退出 GC 触发 `0xc0000374`。
  进程内加载本轮修改前的页面与翻译资源亦复现，见 `probe_feature_fonts.py --before-all`。
  与主窗口可达性测试组合执行正常通过。未删除测试、跳过检查或更改生产生命周期。

本轮没有构建 EXE，也没有进行真实 Android 设备采集验收。
