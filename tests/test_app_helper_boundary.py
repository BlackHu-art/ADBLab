"""应用 helper 的公开兼容入口、独立导入与业务替换点契约。"""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("first", ["services.app_icons", "services.apps.helper"])
def test_old_and_new_helper_entries_share_objects_in_both_import_orders(first):
    script = f"""
import importlib
importlib.import_module({first!r})
from services import app_icons
from services.apps import helper
assert app_icons.HelperResult is helper.HelperResult
assert app_icons.run_app_helper is helper.run_app_helper
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("entry,forbidden", [
    ("services.app_metadata", ["services.app_icons"]),
    ("services.apps.helper", ["services.app_icons", "services.app_metadata"]),
])
def test_protocol_services_import_without_unrelated_business_modules(entry, forbidden):
    script = f"""
import importlib
import sys
importlib.import_module({entry!r})
assert all(name not in sys.modules for name in {forbidden!r}), sorted(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_icon_business_helper_replacement_still_controls_result(monkeypatch):
    from services import app_icons
    from services.apps.helper import HelperResult

    monkeypatch.setattr(app_icons, "run_app_helper", lambda *args, **kwargs: HelperResult(
        error="MISSING",
    ))
    events = []
    app_icons.load_app_icons(
        "synthetic-device", ["com.example.app"], lambda: False,
        lambda *event: events.append(event),
    )
    assert events == [("com.example.app", b"", "应用图标组件缺失")]


def test_metadata_business_helper_replacement_still_controls_fallback(monkeypatch):
    from services import app_metadata
    from services.apps.helper import HelperResult

    monkeypatch.setattr(app_metadata, "run_app_helper", lambda *args, **kwargs: HelperResult(
        error="MISSING",
    ))
    result = app_metadata.load_app_metadata(
        "synthetic-device", ["com.example.app"], lambda: False,
    )
    assert result.unsupported and result.records == {}
