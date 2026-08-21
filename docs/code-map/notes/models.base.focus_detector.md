---
kind: file
---

# models.base.focus_detector

> 通过多种 Android 系统输出尽力识别设备当前前台应用

- 路径：models/base/focus_detector.py

## 函数

- [[models.base.focus_detector.detect_current_package]] — 依次执行兼容性探测命令，任一命令识别成功即返回前台包名
- [[models.base.focus_detector.extract_package_name]] — 从 activity/window 输出中提取首个可信的前台包名

