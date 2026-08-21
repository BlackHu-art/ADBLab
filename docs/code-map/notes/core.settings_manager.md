---
kind: file
---

# core.settings_manager

> 通过 JSON 文件持久化应用设置

- 路径：core/settings_manager.py

## 类

- [[core.settings_manager.AppSettings]] — 线程安全的应用设置单例

## 函数

- [[core.settings_manager._legacy_panel_ratio]] — 把旧版左右像素宽度迁移为受限的左栏比例
- [[core.settings_manager._log_error]] — 向注入的错误日志接收器转发消息；无接收器或接收器异常时静默
- [[core.settings_manager._migrate_1_to_2]] — v1 → v2：折算面板比例并补齐缺失键，用户已设值一律不动（ADR-0006）
- [[core.settings_manager._migrate_2_to_3]] — v2 → v3：剔除未知键（含 monkey_params 内的死键）并记录警告（ADR-0006）
- [[core.settings_manager._normalise_setting]] — 校验需要稳定边界的设置，其他设置保持原有类型与行为
- [[core.settings_manager._prune_unknown_keys]] — 剔除未知顶层键与未知 monkey_params 键，每类一次性记录警告
- [[core.settings_manager._run_migrations]] — 按版本升序对存储字典做原地结构迁移
- [[core.settings_manager._stored_schema_version]] — 读取存储字典的 schema 版本；缺失或非正整数一律视为 v1（种子时代）
- [[core.settings_manager.set_error_sink]] — 注入 ``(level: str, message: str) -> None`` 形式的错误日志接收器

