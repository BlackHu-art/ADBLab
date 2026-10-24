"""验证模型工厂注入、默认装配时序和构造失败边界。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal

import controllers
from controllers import ADBController, _base, model_dependencies
from controllers.model_dependencies import ControllerModels

pytestmark = pytest.mark.ui


class SignalModel(QObject):
    """仅提供装配需要的真实 Qt 信号，不持有设备或后台任务。"""

    command_finished = Signal(str, object)
    action_progress = Signal(object, str)


@pytest.fixture
def model_bundle():
    return ControllerModels(*(SignalModel() for _ in range(4)))


@pytest.fixture
def controller_factory(isolated_app_settings):
    instances = []

    def build(**kwargs):
        controller = ADBController(Mock(), **kwargs)
        instances.append(controller)
        return controller

    yield build
    for controller in instances:
        controller.action_results.close()
        controller.executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("falsey", [False, True], ids=["callable", "falsey-callable"])
def test_injected_factory_is_used_once_and_models_are_preserved(
    monkeypatch, controller_factory, model_bundle, falsey,
):
    class ModelFactory:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            return not falsey

        def __call__(self):
            self.calls += 1
            return model_bundle

    default_factory = Mock(side_effect=AssertionError("不能回退到默认模型"))
    monkeypatch.setattr(controllers, "create_controller_models", default_factory, raising=False)
    history_load = Mock(side_effect=AssertionError("显式跳过历史加载"))
    monkeypatch.setattr(_base.DeviceStore, "load", history_load)
    factory = ModelFactory()
    picker = Mock()
    lifecycle = Mock()
    controller = controller_factory(
        model_factory=factory, load_device_history=False,
        apk_picker=picker, device_lifecycle=lifecycle,
    )

    assert factory.calls == 1
    assert controller.device_model is model_bundle.device_model
    assert controller.app_model is model_bundle.app_model
    assert controller.testing_model is model_bundle.testing_model
    assert controller.advanced_model is model_bundle.advanced_model
    assert controller.apk_picker is picker
    assert controller.device_lifecycle is lifecycle
    default_factory.assert_not_called()
    history_load.assert_not_called()


def test_factory_failure_propagates_without_fallback(monkeypatch, isolated_app_settings):
    error = RuntimeError("合成工厂失败")
    factory = Mock(side_effect=error)
    default_factory = Mock(side_effect=AssertionError("不能回退到默认模型"))
    executor = Mock(side_effect=AssertionError("工厂失败后不能创建 executor"))
    history_load = Mock(side_effect=AssertionError("工厂失败后不能加载历史"))
    services = Mock(side_effect=AssertionError("工厂失败后不能创建业务服务"))
    monkeypatch.setattr(controllers, "create_controller_models", default_factory, raising=False)
    monkeypatch.setattr(_base, "ThreadPoolExecutor", executor)
    monkeypatch.setattr(_base, "OperationManager", services)
    monkeypatch.setattr(_base.DeviceStore, "load", history_load)

    with pytest.raises(RuntimeError) as caught:
        ADBController(Mock(), model_factory=factory)

    assert caught.value is error
    factory.assert_called_once_with()
    default_factory.assert_not_called()
    services.assert_not_called()
    executor.assert_not_called()
    history_load.assert_not_called()


@pytest.mark.parametrize("explicit_none", [False, True], ids=["omitted", "explicit-none"])
@pytest.mark.parametrize("load_history", [False, True], ids=["preloaded", "default-history"])
def test_default_factory_runs_between_settings_and_controller_services(
    monkeypatch, controller_factory, isolated_app_settings, explicit_none, load_history,
):
    events = []

    def settings_instance():
        events.append("settings")
        return isolated_app_settings

    monkeypatch.setattr(_base.AppSettings, "instance", settings_instance)
    for name, event in (
        ("ADBDevice", "device"), ("ADBApp", "app"),
        ("ADBTesting", "testing"), ("ADBAdvanced", "advanced"),
    ):
        def construct_model(event=event):
            events.append(event)
            return SignalModel()

        monkeypatch.setattr(model_dependencies, name, construct_model)

    for name, event in (
        ("OperationManager", "operations"), ("InstallBatchUseCase", "install"),
        ("DeviceBatchUseCase", "device-batch"), ("ScreenRecordUseCase", "screen-record"),
        ("MonkeyBatchCoordinator", "monkey"), ("ThreadPoolExecutor", "executor"),
    ):
        original = getattr(_base, name)

        def construct_service(*args, original=original, event=event, **kwargs):
            events.append(event)
            return original(*args, **kwargs)

        monkeypatch.setattr(_base, name, construct_service)

    original_connect = _base._ADBControllerBase._connect_model_signals

    def connect_signals(controller):
        events.append("signals")
        original_connect(controller)

    monkeypatch.setattr(_base._ADBControllerBase, "_connect_model_signals", connect_signals)
    monkeypatch.setattr(_base.DeviceStore, "load", lambda: events.append("history"))
    kwargs = {}
    if explicit_none:
        kwargs["model_factory"] = None
    if not load_history:
        kwargs["load_device_history"] = False
    controller = controller_factory(**kwargs)

    assert controller._settings is isolated_app_settings
    assert events == [
        "settings", "device", "app", "testing", "advanced", "operations", "install",
        "device-batch", "screen-record", "signals", "monkey", "executor",
        *(["history"] if load_history else []),
    ]
