"""职责归位保留真实定义、唯一类型身份及纯服务导入边界。"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = {
    "core.tasks.cancellation": ("CancellationError", "CancellationToken"),
    "core.tasks.supervision": (
        "StopDisposition", "TaskStopResult", "SupervisedTaskSnapshot", "_SupervisedTask",
        "ThreadedShutdownTask", "TaskSupervisor",
    ),
    "services.tasks.operations": (
        "OperationState", "OperationTransitionError", "IncompleteOperationError",
        "ConflictingOperationResultError", "OperationUnitResult", "OperationArtifact",
        "OperationSnapshot", "_OperationEntry", "OperationManager",
    ),
    "services.tasks.envelope": (
        "OperationMetadata", "OperationEnvelope", "attach_operation_metadata",
        "split_operation_metadata",
    ),
    "services.tasks.action_results": (
        "ActionSpec", "ActionItem", "ActionResult", "expired_action_results", "ActionJob",
        "ActionEnvelope", "_Request", "capture_action_job", "report_action_message",
        "ActionResults", "artifact_name",
    ),
    "services.devices.device_context": ("DeviceContextSnapshot", "DeviceContext"),
    "services.devices.device_batch": (
        "DeviceBatchUnit", "DeviceBatchStart", "DeviceBatchOutcome", "DeviceBatchUseCase",
    ),
    "services.devices.device_connection_lifecycle": (
        "WirelessHistoryGuard", "DeviceConnectionLifecycle",
    ),
    "services.apps.install_batch": (
        "InstallRequest", "InstallUnit", "InstallBatchOutcome", "InstallBatchStart",
        "InstallBatchUseCase",
    ),
    "services.apps.apk_selection": ("ApkFilePicker",),
    "services.screen_record": ("ScreenRecordUseCase",),
    "services.monkey_batch": (
        "MonkeyRunSnapshot", "MonkeyTargetCompletion", "_MonkeyTargetState",
        "MonkeyBatchCoordinator",
    ),
}


def _probe(source):
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(source)], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module_name", DEFINITIONS)
def test_full_definitions_live_in_responsible_module(module_name):
    path = ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    assert path.is_file(), f"Missing responsibility module: {module_name}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = tuple(
        node.name for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    assert definitions == DEFINITIONS[module_name]
    _probe(f"""
        import importlib
        import importlib.abc
        from pathlib import Path
        import sys

        class RejectDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                forbidden = {{
                    'PySide6', 'qfluentwidgets', 'gui', 'models', 'controllers', 'adblab',
                }}
                if {module_name!r}.startswith('core.'):
                    forbidden.add('services')
                if fullname.split('.')[0] in forbidden:
                    raise AssertionError('Unexpected dependency: ' + fullname)

        sys.meta_path.insert(0, RejectDependencies())
        module = importlib.import_module({module_name!r})
        assert Path(module.__file__).resolve() == Path({str(path)!r}).resolve()
        assert importlib.import_module({module_name!r}) is module
        for name in {DEFINITIONS[module_name]!r}:
            value = getattr(module, name)
            assert value.__module__ == {module_name!r}, name
            assert value is getattr(importlib.import_module({module_name!r}), name)
        assert not any(name.split('.')[0] in {{'adblab', 'PySide6', 'gui', 'models', 'controllers'}}
                       for name in sys.modules)
    """)


@pytest.mark.parametrize(
    "package", ["core.tasks", "services.tasks", "services.devices", "services.apps"],
)
def test_package_root_does_not_load_leaves_or_qt(package):
    _probe(f"""
        import importlib
        import importlib.abc
        import sys

        class RejectDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {{
                    'PySide6', 'qfluentwidgets', 'gui', 'models', 'controllers', 'adblab',
                }}:
                    raise AssertionError('Unexpected dependency: ' + fullname)

        sys.meta_path.insert(0, RejectDependencies())
        importlib.import_module({package!r})
        packages = {{'core.tasks', 'services.tasks', 'services.devices', 'services.apps'}}
        assert not any(name.startswith(package + '.')
                       for package in packages for name in sys.modules)
    """)


def test_cross_package_dependencies_share_operation_types_and_cancellation():
    _probe("""
        from core.tasks import cancellation
        from services.tasks import operations
        from services.devices import device_batch
        from services.apps import install_batch

        assert operations.CancellationToken is cancellation.CancellationToken
        for module in (device_batch, install_batch):
            for name in ('OperationManager', 'OperationState'):
                assert getattr(module, name) is getattr(operations, name)
        token = operations.CancellationToken()
        assert token.request() is True
        assert token.request() is False
        try:
            token.raise_if_cancelled()
        except cancellation.CancellationError:
            pass
        else:
            raise AssertionError('CancellationError identity was lost')
    """)


def test_action_scope_is_shared_and_restored_across_copied_contexts():
    _probe("""
        from contextvars import copy_context
        import importlib
        from services.tasks import action_results
        from services.tasks.action_results import capture_action_job, report_action_message

        assert importlib.import_module('services.tasks.action_results') is action_results
        updates = []
        store = action_results.ActionResults(updates.append)
        jobs = []
        clean_context = copy_context()

        def submit():
            assert clean_context.run(capture_action_job, 'probe', 'a') is None
            job = copy_context().run(capture_action_job, 'probe', 'a')
            assert isinstance(job, action_results.ActionJob)
            jobs.append(job)
            assert report_action_message(True, 'submitted') is True

        store.run(action_results.ActionSpec('probe', 'test', '测试'), ('a',), submit)
        assert capture_action_job('probe', 'a') is None
        assert report_action_message(True, 'outside') is False
        store.complete(jobs[0], {'success': True, 'output': 'done'})
        assert updates[-1].state == 'succeeded'
        assert updates[-1].items[0].detail == 'done'
        assert updates[-1].request_id == jobs[0].request_id
    """)
