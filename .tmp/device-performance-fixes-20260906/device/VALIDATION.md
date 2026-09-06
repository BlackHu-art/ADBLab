# 设备概览紧凑键值布局验证

本轮范围仅 `gui/pages/device_hub.py` 与 `tests/test_device_hub_page.py`。两文件修改前无既有差异；原文件备份在当前目录，未修改其他页面、共享样式或翻译。

所有摘要和详情字段改为单行“图标 / 标签 + 数值”，同组标签和数值起点对齐。数值只在实际可见宽度不足时省略显示，tooltip、accessibleDescription 与复制详情保留完整当前快照；缺失字段仍隐藏。详情展开状态、设备选择和操作按钮沿用原行为。

## 自动验证

- 基线：`.venv/Scripts/python.exe -m pytest -q tests/test_device_hub_page.py`：66 passed，退出 0。
- 新增单行密度四种宽度 / 字体组合及长值完整获取回归，修前 5 failed，见 `before-new-tests.txt`。
- 最终同命令：72 passed，退出 0，见 `final-tests.txt`。包含长英文标签在 380 / 860 宽度下的回归。
- `.venv/Scripts/python.exe -m ruff check gui/pages/device_hub.py tests/test_device_hub_page.py`：通过。
- `.venv/Scripts/python.exe -m pyright gui/pages/device_hub.py`：0 errors。
- `.venv/Scripts/python.exe scripts/check_comment_language.py gui/pages/device_hub.py` 与范围内 `git diff --check`：通过。

## 实际渲染

`render_device.py` 使用内存合成快照、真实系统中文字体及项目翻译，未执行 ADB 或读取用户设置。宽窄预览均验证无横向滚动，复制详情能滚动至完整可见。

| 条件 | 展开卡片高度 | 摘要高度 | 详情参数高度 |
| --- | ---: | ---: | ---: |
| 浅色 1000 宽 / 字号 12，修改前 | 361 | 41 | 139 |
| 浅色 1000 宽 / 字号 12，修改后 | 277 | 20 | 76 |
| 深色 380 宽 / 字号 22，修改前 | 1377 | 316 | 638 |
| 深色 380 宽 / 字号 22，修改后 | 934 | 168 | 343 |

另检查英文 860 宽 / 字号 22 / 125% DPI：无横向溢出，长标签保留完整，复制按钮可达。实际截图见 `device-after-*.png`；相同条件修改前截图为 `device-before-*.png`。

未执行全量测试、实机设备操作或构建；本次仅页面显示及其直接回归。无新增翻译词条。
