"""设备连接适配边界只读既有生命周期，不新增 Qt 或后台资源。"""

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.adb_pairing import PairingOutcome


@pytest.fixture
def lifecycle_case():
    from adblab.presentation.qt_device_connection_lifecycle import QtDeviceConnectionLifecycle

    outcome = PairingOutcome(
        request_id=4, context_revision=7, paired=True, connected=True,
        reason="connected", state="Connected", device_id="synthetic-transport",
        connection_endpoint="192.0.2.10:41000",
    )
    pairing = SimpleNamespace(context_revision=7)
    pairing.accepts_outcome = Mock(side_effect=lambda value: value is outcome)
    owner = SimpleNamespace(_closing=False, _adb_pairing=pairing)
    current = {"owner": owner}
    adapter = QtDeviceConnectionLifecycle(lambda: current["owner"])
    return adapter, current, owner, pairing, outcome


def test_lifecycle_protocol_import_is_isolated():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; "
         "import adblab.application.device_connection_lifecycle; "
         "assert not any(n == 'controllers' or n == 'services.adb_pairing' "
         "or n.startswith('PySide6') for n in sys.modules)"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_adapter_is_lazy_and_tracks_late_owner(lifecycle_case):
    from adblab.presentation.qt_device_connection_lifecycle import QtDeviceConnectionLifecycle

    _adapter, _current, owner, _pairing, outcome = lifecycle_case
    provider = Mock(return_value=None)
    adapter = QtDeviceConnectionLifecycle(provider)
    provider.assert_not_called()
    assert adapter.capture_wireless_history(outcome) is None
    adapter.invalidate_wireless_pairing("server_restart")
    adapter.note_adb_server_restarted()
    for candidate in (owner, SimpleNamespace(_closing=True)):
        candidate.invalidate_wireless_pairing = Mock()
        candidate.note_adb_server_restarted = Mock()
        provider.return_value = candidate
        adapter.invalidate_wireless_pairing("server_restart")
        adapter.note_adb_server_restarted()
        candidate.invalidate_wireless_pairing.assert_called_once_with("server_restart")
        candidate.note_adb_server_restarted.assert_called_once_with()


@pytest.mark.parametrize("rejection", [
    "none", "closing", "no_pairing", "missing_accepts", "noncallable", "rejected", "copy",
])
def test_capture_delegates_original_outcome_and_preserves_rejection(lifecycle_case, rejection):
    adapter, current, owner, pairing, outcome = lifecycle_case
    if rejection == "none":
        current["owner"] = None
    elif rejection == "closing":
        owner._closing = True
    elif rejection == "no_pairing":
        owner._adb_pairing = None
    elif rejection == "missing_accepts":
        del pairing.accepts_outcome
    elif rejection == "noncallable":
        pairing.accepts_outcome = 1
    elif rejection == "rejected":
        pairing.accepts_outcome = Mock(return_value=False)
    else:
        outcome = replace(outcome)
    assert adapter.capture_wireless_history(outcome) is None


@pytest.mark.parametrize("change", ["owner", "pairing", "revision", "closing"])
def test_guard_rejects_owner_pairing_revision_and_closing_changes(lifecycle_case, change):
    adapter, current, owner, pairing, outcome = lifecycle_case
    guard = adapter.capture_wireless_history(outcome)
    assert guard is not None and guard.is_current()
    assert pairing.accepts_outcome.call_args.args[0] is outcome
    if change == "owner":
        current["owner"] = SimpleNamespace(**vars(owner))
    elif change == "pairing":
        owner._adb_pairing = SimpleNamespace(**vars(pairing))
    elif change == "revision":
        pairing.context_revision += 1
    else:
        owner._closing = True
    assert not guard.is_current()


def test_guard_does_not_repeat_gui_admission(lifecycle_case):
    adapter, _current, _owner, pairing, outcome = lifecycle_case
    admission_threads = []

    def accepts(value):
        admission_threads.append(threading.get_ident())
        return value is outcome

    pairing.accepts_outcome = accepts
    guard = adapter.capture_wireless_history(outcome)
    assert guard is not None
    pairing.accepts_outcome = Mock(side_effect=AssertionError("后台不能重新调用准入"))
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(guard.is_current).result(timeout=2)
        assert executor.submit(guard.is_current).result(timeout=2)
    assert admission_threads == [threading.get_ident()]
    pairing.accepts_outcome.assert_not_called()


@pytest.mark.parametrize("change", ["verified", "request", "pairing_closing"])
def test_guard_preserves_admitted_request_semantics(lifecycle_case, change):
    adapter, _current, _owner, pairing, outcome = lifecycle_case
    pairing._verified_outcome = outcome
    pairing._request_id = outcome.request_id
    pairing._closing = False
    guard = adapter.capture_wireless_history(outcome)
    assert guard is not None
    if change == "verified":
        pairing._verified_outcome = None
    elif change == "request":
        pairing._request_id += 1
    else:
        pairing._closing = True
    pairing.accepts_outcome = Mock(return_value=False)
    assert guard.is_current()
    assert adapter.capture_wireless_history(outcome) is None


@pytest.mark.parametrize("value", [None, 1])
def test_callbacks_keep_optional_behavior(lifecycle_case, value):
    adapter, _current, owner, _pairing, _outcome = lifecycle_case
    adapter.invalidate_wireless_pairing("server_restart")
    adapter.note_adb_server_restarted()
    owner.invalidate_wireless_pairing = value
    owner.note_adb_server_restarted = value
    adapter.invalidate_wireless_pairing("server_restart")
    adapter.note_adb_server_restarted()


@pytest.mark.parametrize("failure", ["provider", "accepts", "invalidate", "notify"])
def test_callbacks_preserve_exception_behavior(lifecycle_case, failure):
    from adblab.presentation.qt_device_connection_lifecycle import QtDeviceConnectionLifecycle

    adapter, _current, owner, pairing, outcome = lifecycle_case
    error = RuntimeError("synthetic failure")
    fail = Mock(side_effect=error)
    if failure == "provider":
        adapter = QtDeviceConnectionLifecycle(fail)
        operation = partial(adapter.capture_wireless_history, outcome)
    elif failure == "accepts":
        pairing.accepts_outcome = fail
        operation = partial(adapter.capture_wireless_history, outcome)
    elif failure == "invalidate":
        owner.invalidate_wireless_pairing = fail
        operation = partial(adapter.invalidate_wireless_pairing, "server_restart")
    else:
        owner.note_adb_server_restarted = fail
        operation = adapter.note_adb_server_restarted
    with pytest.raises(RuntimeError) as caught:
        operation()
    assert caught.value is error
