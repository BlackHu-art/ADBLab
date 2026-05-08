"""ADB Controller package.

The fully-composed ADBController class is assembled here from mixins.
Import it directly::

    from controllers import ADBController
"""

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from controllers._file import ADBFileMixin
from controllers._input import ADBInputMixin
from controllers._media import ADBMediaMixin


class ADBController(
    ADBDeviceMixin,
    ADBInputMixin,
    ADBMediaMixin,
    ADBAppMixin,
    ADBFileMixin,
    _ADBControllerBase,
):
    """Fully decoupled ADB controller communicating via signals.

    Instantiation::

        controller = ADBController(log_service)
    """


__all__ = ["ADBController"]
