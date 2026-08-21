---
kind: file
---

# utils.adb_values

> 集中校验会进入 ADB 参数列表的动态值

- 路径：utils/adb_values.py

## 函数

- [[utils.adb_values.normalize_android_package]] — 校验只读诊断使用的 Android 包名
- [[utils.adb_values.normalize_dumpsys_service]] — 把 dumpsys 服务限制在界面公开的只读白名单内
- [[utils.adb_values.normalize_geo_coordinate]] — 校验普通十进制坐标并去除无意义的尾零
- [[utils.adb_values.normalize_tcp_port]] — 返回规范化 TCP 端口；非法值抛出 ``ValueError``
- [[utils.adb_values.truncate_diagnostic_output]] — 限制诊断输出的行数和字符数，并返回是否发生裁剪

