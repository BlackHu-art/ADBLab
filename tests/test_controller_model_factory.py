"""模型工厂保持构造顺序、实例身份与失败传播契约。"""

import threading
from dataclasses import FrozenInstanceError

import pytest

from controllers import model_dependencies


def test_default_factory_creates_fresh_models_per_call(monkeypatch):
    calls = []
    instances = {name: [] for name in ("device", "app", "testing", "advanced")}

    def constructor(name):
        def create():
            calls.append(name)
            instance = object()
            instances[name].append(instance)
            return instance

        return create

    monkeypatch.setattr(model_dependencies, "ADBDevice", constructor("device"))
    monkeypatch.setattr(model_dependencies, "ADBApp", constructor("app"))
    monkeypatch.setattr(model_dependencies, "ADBTesting", constructor("testing"))
    monkeypatch.setattr(model_dependencies, "ADBAdvanced", constructor("advanced"))

    first = model_dependencies.create_controller_models()
    second = model_dependencies.create_controller_models()

    assert calls == ["device", "app", "testing", "advanced"] * 2
    assert isinstance(first, model_dependencies.ControllerModels)
    assert isinstance(second, model_dependencies.ControllerModels)
    assert first is not second
    for name, created in instances.items():
        assert getattr(first, f"{name}_model") is created[0]
        assert getattr(second, f"{name}_model") is created[1]
        assert created[0] is not created[1]
    with pytest.raises(FrozenInstanceError):
        first.device_model = object()


@pytest.mark.parametrize(
    ("failing_model", "expected_calls"),
    [
        ("device", ["device"]),
        ("app", ["device", "app"]),
        ("testing", ["device", "app", "testing"]),
        ("advanced", ["device", "app", "testing", "advanced"]),
    ],
)
def test_default_factory_propagates_model_creation_failure(
    monkeypatch, failing_model, expected_calls,
):
    calls = []
    failure = RuntimeError("合成模型构造失败")

    def constructor(name):
        def create():
            calls.append(name)
            if name == failing_model:
                raise failure
            return object()

        return create

    monkeypatch.setattr(model_dependencies, "ADBDevice", constructor("device"))
    monkeypatch.setattr(model_dependencies, "ADBApp", constructor("app"))
    monkeypatch.setattr(model_dependencies, "ADBTesting", constructor("testing"))
    monkeypatch.setattr(model_dependencies, "ADBAdvanced", constructor("advanced"))

    with pytest.raises(RuntimeError) as raised:
        model_dependencies.create_controller_models()

    assert raised.value is failure
    assert calls == expected_calls


@pytest.mark.ui
def test_real_factory_preserves_model_types_and_pool_ownership(qt_application, monkeypatch):
    from PySide6.QtCore import QThread, QThreadPool

    from core.exec import CommandRunner, ProcessRunner
    from models.adb_advanced import ADBAdvanced
    from models.adb_app import ADBApp
    from models.adb_device import ADBDevice
    from models.adb_testing import ADBTesting

    def reject_command(*args, **kwargs):
        pytest.fail("模型装配不得执行真实命令或启动进程")

    monkeypatch.setattr(CommandRunner, "run", reject_command)
    monkeypatch.setattr(ProcessRunner, "start", reject_command)
    monkeypatch.setattr("subprocess.Popen", reject_command)
    assert QThread.currentThread() is qt_application.thread()
    created = []
    try:
        created.append(model_dependencies.create_controller_models())
        created.append(model_dependencies.create_controller_models())
        all_models = [
            model
            for models in created
            for model in (
                models.device_model, models.app_model,
                models.testing_model, models.advanced_model,
            )
        ]
        assert len({id(model) for model in all_models}) == 8
        assert len({id(model.long_pool) for model in all_models}) == 8
        global_pool = QThreadPool.globalInstance()
        for models in created:
            assert type(models.device_model) is ADBDevice
            assert type(models.app_model) is ADBApp
            assert type(models.testing_model) is ADBTesting
            assert type(models.advanced_model) is ADBAdvanced
            record_pool = models.advanced_model._record_pool
            assert record_pool.parent() is models.advanced_model
            assert record_pool.maxThreadCount() == 2
            assert record_pool.thread() is qt_application.thread()
            assert record_pool.activeThreadCount() == 0
        assert created[0].advanced_model._record_pool is not created[1].advanced_model._record_pool
        for model in all_models:
            assert model.parent() is None
            assert model.thread() is qt_application.thread()
            assert model.thread_pool is global_pool
            assert model.long_pool is not global_pool
            assert model.long_pool.parent() is None
            assert model.long_pool.thread() is qt_application.thread()
            assert model.long_pool.activeThreadCount() == 0
            assert not model.is_shutting_down()
        assert global_pool.activeThreadCount() == 0
    finally:
        cleanup_errors = []

        def cleanup():
            for models in created:
                owned = (
                    models.device_model, models.app_model,
                    models.testing_model, models.advanced_model,
                )
                callbacks = [model.begin_shutdown for model in owned]
                callbacks.extend((models.testing_model.shutdown, models.advanced_model.shutdown))
                callbacks.extend(model.wait_for_commands for model in owned)
                for callback in callbacks:
                    try:
                        callback()
                    except Exception as exc:
                        cleanup_errors.append(exc)

        worker = threading.Thread(target=cleanup, daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "模型清理线程未在预算内退出"
        assert not cleanup_errors, cleanup_errors
