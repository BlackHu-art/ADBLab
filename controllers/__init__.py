"""组装并导出完整的 ADBController。

控制器由多个职责明确的 mixin 组合而成，可按以下方式直接导入：

    from controllers import ADBController
"""

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from controllers._file import ADBFileMixin
from controllers._input import ADBInputMixin
from controllers._media import ADBMediaMixin
from controllers._system import ADBSystemControllerMixin


class ADBController(
    ADBDeviceMixin,
    ADBInputMixin,
    ADBMediaMixin,
    ADBAppMixin,
    ADBFileMixin,
    ADBSystemControllerMixin,
    _ADBControllerBase,
):
    """通过 Qt 信号与界面通信的完整 ADB 控制器。

    实例化方式：

        controller = ADBController(log_service)
    """


__all__ = ["ADBController"]
