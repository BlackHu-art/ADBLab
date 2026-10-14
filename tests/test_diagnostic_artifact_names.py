"""诊断产物短名称、设备归属及任务唯一性回归。"""

import base64
import re
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controllers import _app, _media


@pytest.mark.parametrize("kind", ["log", "logcat"])
@pytest.mark.parametrize("device", [
    "mock-usb-device",
    "192.0.2.15:5555",
    "adb-MOCKDEVICE123456-randomsuffix._adb-tls-connect._tcp",
    "测试设备-" + "x" * 300,
])
def test_log_export_names_are_bounded_and_hide_connection_identifiers(
    tmp_path, monkeypatch, kind, device,
):
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 14, 18, 27, 4)
    monkeypatch.setattr(_app, "datetime", clock)
    monkeypatch.setattr(_media, "datetime", clock)
    controller = SimpleNamespace(
        testing_model=Mock(),
        advanced_model=Mock(),
        _require_devices=lambda *args: True,
        _get_screenshot_dir=lambda: str(tmp_path),
    )

    if kind == "log":
        _app.ADBAppMixin._save_single_device_log(controller, device, str(tmp_path))
        capture = controller.testing_model.retrieve_device_logs_async
    else:
        _media.ADBMediaMixin.logcat_filtered(controller, [device])
        capture = controller.advanced_model.logcat_filtered_async

    target_device, path = capture.call_args.args[:2]
    name = Path(path).name
    assert target_device == device
    assert Path(path).parent == tmp_path
    assert len(name) <= 64
    assert re.fullmatch(rf"{kind}_20261014_182704_[0-9a-f]{{8}}_[a-z2-7]{{26}}\.txt", name)
    assert device not in name
    assert "MOCKDEVICE123456" not in name
    assert list(tmp_path.iterdir()) == []


def test_diagnostic_prefix_is_stable_per_device_and_shared_by_artifact_kinds():
    from utils.diagnostic_artifacts import diagnostic_prefix

    timestamp = "20261014_182704"
    prefixes = {
        kind: diagnostic_prefix(kind, "mock-device-a", timestamp)
        for kind in ("log", "logcat", "bugreport")
    }
    assert len({prefix.rsplit("_", 2)[-2] for prefix in prefixes.values()}) == 1
    for kind, prefix in prefixes.items():
        assert re.fullmatch(rf"{kind}_{timestamp}_[0-9a-f]{{8}}_", prefix)
        assert prefix == diagnostic_prefix(kind, "mock-device-a", timestamp)
        assert prefix != diagnostic_prefix(kind, "mock-device-b", timestamp)


def test_log_name_retains_all_uuid_bits_in_case_insensitive_safe_encoding(monkeypatch):
    from utils import diagnostic_artifacts

    identities = [
        uuid.UUID("d5363941-0c17-459b-a481-16482dfe4c70"),
        uuid.UUID("d5363941-0c17-459b-a481-16482dfe4c71"),
    ]
    monkeypatch.setattr(diagnostic_artifacts.uuid, "uuid4", Mock(side_effect=identities))
    names = [
        diagnostic_artifacts.diagnostic_log_filename("log", "mock-device", "20261014_182704")
        for _ in identities
    ]

    assert len(set(names)) == 2
    assert len({name.casefold() for name in names}) == 2
    for name, identity in zip(names, identities, strict=True):
        nonce = Path(name).stem.rsplit("_", 1)[-1]
        assert len(nonce) == 26 and nonce.islower()
        assert base64.b32decode(nonce.upper() + "======") == identity.bytes
