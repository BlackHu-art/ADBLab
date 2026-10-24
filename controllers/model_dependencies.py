"""提供 Controller 的模型集合与默认装配入口。"""

from collections.abc import Callable
from dataclasses import dataclass

from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_device import ADBDevice
from models.adb_testing import ADBTesting


@dataclass(frozen=True)
class ControllerModels:
    """保存一次装配的模型身份；生命周期仍由 Controller 的原模型属性管理。"""

    device_model: ADBDevice
    app_model: ADBApp
    testing_model: ADBTesting
    advanced_model: ADBAdvanced


ControllerModelFactory = Callable[[], ControllerModels]


def create_controller_models() -> ControllerModels:
    """由 GUI 线程按原顺序创建独占模型，失败原样传播且不启动任务或接线。"""
    return ControllerModels(
        device_model=ADBDevice(),
        app_model=ADBApp(),
        testing_model=ADBTesting(),
        advanced_model=ADBAdvanced(),
    )
