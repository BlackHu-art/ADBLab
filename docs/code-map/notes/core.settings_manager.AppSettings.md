---
kind: class
---

# AppSettings

- 模块：[[core.settings_manager]]
- 全名：core.settings_manager.AppSettings

> 线程安全的应用设置单例

## 方法

- [[core.settings_manager.AppSettings.__new__]] — （无 docstring）
- [[core.settings_manager.AppSettings.instance]] — 返回应用设置单例
- [[core.settings_manager.AppSettings._load]] — 加载用户设置；不存在时尝试迁移旧安装目录中的设置
- [[core.settings_manager.AppSettings._save_atomic]] — 先写临时文件再原子替换，避免中途退出导致配置文件损坏
- [[core.settings_manager.AppSettings._schedule_save]] — 重新启动单个防抖计时器
- [[core.settings_manager.AppSettings.get]] — 读取设置，不存在时按默认设置和调用方默认值依次回退
- [[core.settings_manager.AppSettings.set]] — 更新单项设置，并在 500 毫秒防抖后持久化
- [[core.settings_manager.AppSettings.update]] — 批量更新多项设置，并仅安排一次防抖持久化
- [[core.settings_manager.AppSettings.set_many]] — 兼容性批量设置别名
- [[core.settings_manager.AppSettings.reset]] — 将指定设置或全部设置恢复为默认值，并立即持久化
- [[core.settings_manager.AppSettings.save_directory]] — 返回已配置且有效的保存目录，否则使用用户主目录下的 ADBLab
- [[core.settings_manager.AppSettings.ui_font_size]] — 返回已校验的界面字号
- [[core.settings_manager.AppSettings.log_font_size]] — 返回已校验的日志字号

