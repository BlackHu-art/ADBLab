"""统一主窗构建的阶段位置与诊断名称；百分比表示阶段完成，不估算剩余时间。"""

from enum import IntEnum


class WindowStartupStage(IntEnum):
    """整数值兼容分步构建接口；100% 仅由协调器在主窗首帧后交付。"""

    WINDOW_BASE = 40
    APPS_OVERVIEW = 45
    SYSTEM_OVERVIEW = 50
    REMOTE_OVERVIEW = 55
    DEVICES_HOST = 60
    APPS_HOST = 65
    WORKSPACE = 70
    TASK_CENTER = 75
    TASKS_PAGE = 78
    SETTINGS_PAGE = 82
    HOME_PAGE = 85
    NAVIGATION = 95

    @property
    def diagnostic_name(self) -> str:
        """阶段命名直接来自枚举，入口无需另维护百分比到名称的映射。"""
        return self.name.lower().replace("_", "-")
