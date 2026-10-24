"""设备状态不依赖控件、服务或持久化，操作准入与保留勾选分别投影。"""

import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from adblab.application.device_context import DeviceContext, DeviceContextSnapshot


def test_initial_and_new_devices_are_not_selected():
    context = DeviceContext()
    assert context.snapshot() == DeviceContextSnapshot((), (), "scanning")
    assert context.begin_refresh() is False
    assert context.restore_superseded_refresh() is False
    context.replace_connected_devices(["a", "a", "b"])
    assert context.snapshot() == DeviceContextSnapshot((), ("a", "b"), "scanning")
    assert context.checked_devices == ()
    assert context.display_devices == ("a", "b")


def test_reordering_and_reconnection_preserve_only_surviving_checks():
    context = DeviceContext()
    context.replace_connected_devices(["a", "b"])
    context.set_selected_devices(["b", "a", "b", "missing"])
    context.replace_connected_devices(["b", "a", "c"])
    assert context.snapshot().connected_devices == ("b", "a", "c")
    assert context.display_devices == ("a", "b", "c")
    assert context.checked_devices == ("a", "b")
    context.replace_connected_devices(["b", "c"])
    context.replace_connected_devices(["a", "b", "c"])
    assert context.display_devices == ("b", "c", "a")
    assert context.checked_devices == ("b",)


def test_selection_uses_membership_without_normalizing_identifiers():
    context = DeviceContext()
    context.replace_connected_devices(iter([" a ", "b"]))
    context.set_selected_devices(device for device in ["b", "missing", " a ", "b", "a"])
    assert context.checked_devices == (" a ", "b")
    assert context.snapshot().selected_devices == (" a ", "b")


def test_unavailable_retains_checks_but_masks_operation_targets():
    context = DeviceContext()
    context.replace_connected_devices(["a", "b"])
    context.set_selected_devices(["a"])
    for state in ("ready", "scanning"):
        context.set_discovery_state(state)
        assert context.snapshot().selected_devices == ("a",)
    context.set_discovery_state("unavailable")
    assert context.checked_devices == ("a",)
    assert context.snapshot() == DeviceContextSnapshot((), ("a", "b"), "unavailable")
    context.set_selected_devices(["b"])
    assert context.checked_devices == ("b",)
    assert context.snapshot().selected_devices == ()
    context.set_discovery_state("ready")
    assert context.snapshot().selected_devices == ("b",)


def test_state_normalization_does_not_replace_inventory():
    context = DeviceContext()
    context.replace_connected_devices(["a"])
    context.set_selected_devices(["a"])
    assert context.set_discovery_state("READY") is True
    assert context.set_discovery_state("ready") is False
    assert context.set_discovery_state("unknown") is True
    assert context.set_discovery_state("") is False
    assert context.snapshot() == DeviceContextSnapshot(("a",), ("a",), "empty")
    context.replace_connected_devices([])
    assert context.snapshot() == DeviceContextSnapshot((), (), "empty")
    assert context.display_devices == context.checked_devices == ()


@pytest.mark.parametrize("state", ["ready", "empty", "unavailable"])
def test_refresh_restores_once_and_rejects_duplicates(state):
    context = DeviceContext()
    context.set_discovery_state(state)
    assert context.begin_refresh() is True
    assert context.begin_refresh() is False
    assert context.set_discovery_state("scanning") is False
    assert context.snapshot().discovery_state == "scanning"
    assert context.restore_superseded_refresh() is True
    assert context.snapshot().discovery_state == state
    assert context.restore_superseded_refresh() is False


@pytest.mark.parametrize(
    ("state", "new_devices", "expected_devices"),
    [("ready", ["b"], ("b",)), ("empty", [], ()), ("unavailable", None, ("a",))],
)
def test_terminal_state_invalidates_refresh_restore(state, new_devices, expected_devices):
    context = DeviceContext()
    context.replace_connected_devices(["a"])
    context.set_discovery_state("ready")
    assert context.begin_refresh() is True
    if new_devices is not None:
        context.replace_connected_devices(new_devices)
    context.set_discovery_state(state)
    assert context.restore_superseded_refresh() is False
    assert context.snapshot().discovery_state == state
    assert context.snapshot().connected_devices == expected_devices


def test_inputs_snapshots_and_instances_are_isolated():
    context = DeviceContext()
    connected, selected = ["a"], ["a"]
    context.replace_connected_devices(connected)
    context.set_selected_devices(selected)
    context.set_discovery_state("ready")
    snapshot = context.snapshot()
    connected.clear()
    selected.clear()
    assert context.snapshot() == DeviceContextSnapshot(("a",), ("a",), "ready")
    context.replace_connected_devices(["b"])
    assert snapshot == DeviceContextSnapshot(("a",), ("a",), "ready")
    with pytest.raises(FrozenInstanceError):
        snapshot.discovery_state = "empty"
    assert DeviceContext().snapshot() == DeviceContextSnapshot((), (), "scanning")


def test_device_context_imports_without_gui_or_services():
    source = textwrap.dedent("""
        import importlib.abc
        import sys

        class RejectDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {
                    'PySide6', 'qfluentwidgets', 'gui', 'core', 'models', 'services',
                }:
                    raise AssertionError('Unexpected dependency: ' + fullname)

        sys.meta_path.insert(0, RejectDependencies())
        from adblab.application.device_context import DeviceContext
        context = DeviceContext()
        context.replace_connected_devices(['a'])
        context.set_selected_devices(['a'])
        assert context.snapshot().selected_devices == ('a',)
    """)
    result = subprocess.run(
        [sys.executable, "-B", "-c", source],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
