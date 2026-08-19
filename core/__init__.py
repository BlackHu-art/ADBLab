"""ADBLab 核心基础设施包。

本包保持轻量入口：不在 __init__ 中主动导入依赖 Qt 的模块，避免 ``import core.xxx``
把 PySide6 拉进不需要 Qt 的执行边界（如 MobilePerf 内核）。各模块按需显式导入，
例如 ``from core.log_service import LogService``。
"""
