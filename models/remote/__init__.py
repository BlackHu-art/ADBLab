"""Remote control and scrcpy service layer."""

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
