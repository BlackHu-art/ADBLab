"""组装并导出完整的 ADBController。

控制器由多个职责明确的 mixin 组合而成，可按以下方式直接导入：

    from controllers import ADBController
"""

from adblab.application.apk_selection import ApkFilePicker
from adblab.application.device_connection_lifecycle import DeviceConnectionLifecycle
from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from controllers._file import ADBFileMixin
from controllers._input import ADBInputMixin
from controllers._media import ADBMediaMixin
from controllers._system import ADBSystemControllerMixin
from controllers.model_dependencies import ControllerModelFactory, create_controller_models
from core.log_service import LogService


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

    组合根在 GUI 线程创建本对象，并拥有全部 model、信号与 OperationManager；异步结果经
    command_finished 回到该线程。shutdown 是终态的阻塞操作，只允许关闭阶段的后台任务调用。

    实例化方式：

        controller = ADBController(log_service)
    """

    def __init__(
        self, log_service: LogService, *, load_device_history: bool = True,
        apk_picker: ApkFilePicker | None = None,
        device_lifecycle: DeviceConnectionLifecycle | None = None,
        model_factory: ControllerModelFactory | None = None,
    ) -> None:
        """注入适配器与模型工厂；缺省适配器惰性读取后绑定的窗口。

        工厂在 GUI 线程加载设置后同步调用一次，异常原样传播；返回的未启动模型归本实例所有。
        """
        if apk_picker is None:
            from adblab.presentation.qt_apk_file_picker import QtApkFilePicker

            # 父窗口可在构造后设置，必须到选择时才读取。
            apk_picker = QtApkFilePicker(lambda: self.window_owner)
        if device_lifecycle is None:
            from adblab.presentation.qt_device_connection_lifecycle import (
                QtDeviceConnectionLifecycle,
            )

            device_lifecycle = QtDeviceConnectionLifecycle(lambda: self.window_owner)
        if model_factory is None:
            model_factory = create_controller_models
        super().__init__(
            log_service, load_device_history=load_device_history, apk_picker=apk_picker,
            device_lifecycle=device_lifecycle, model_factory=model_factory,
        )


__all__ = ["ADBController"]
