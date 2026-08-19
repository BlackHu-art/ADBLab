"""提供 Remote 控制和 scrcpy 进程服务的无界面实现。"""

from .control_service import RemoteControlService
from .input_engine import RemoteInputEngine
from .scrcpy_args import build_scrcpy_args
from .scrcpy_service import ScrcpyService
from .types import PreflightResult, ScrcpyConfig, ScrcpyLaunchPlan
from .window_manager import RemoteWindowManager

__all__ = [
    "PreflightResult",
    "RemoteInputEngine",
    "RemoteControlService",
    "ScrcpyConfig",
    "ScrcpyLaunchPlan",
    "ScrcpyService",
    "RemoteWindowManager",
    "build_scrcpy_args",
]
