"""字典迁移原地转换并通过显式 reporter 提交有序诊断。"""

from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.mark.parametrize(("stored", "expected"), [
    ({}, 1), ({"schema_version": True}, 1), ({"schema_version": False}, 1),
    ({"schema_version": None}, 1), ({"schema_version": "3"}, 1),
    ({"schema_version": 0}, 1), ({"schema_version": -1}, 1),
    ({"schema_version": 1}, 1), ({"schema_version": 2}, 2),
    ({"schema_version": 3}, 3), ({"schema_version": 99}, 99),
])
def test_stored_version_contract(stored, expected):
    from core.settings.migrations import stored_schema_version

    assert stored_schema_version(stored) == expected


@pytest.mark.parametrize(("left", "right", "expected"), [
    (300, 900, 0.25), (-1, 900, 0.2), (900, 0, 0.7),
    (0, 0, 0.5), (None, 400, 0.5), ("invalid", 400, 0.5),
])
def test_legacy_ratio_keeps_clamp_and_fallback(left, right, expected):
    from core.settings.migrations import legacy_panel_ratio

    assert legacy_panel_ratio(left, right) == expected


def test_v1_migration_mutates_in_place_without_stamping_version():
    from core.settings.migrations import migrate_1_to_2, run_migrations
    from core.settings.schema import DEFAULTS

    stored = {"left_panel_width": 300, "right_panel_width": 900,
              "monkey_params": {"events": 5000}, "future": "old"}
    identity = id(stored)
    defaults = deepcopy(DEFAULTS)
    reports = []
    migrate_1_to_2(stored, lambda *message: reports.append(message))
    assert id(stored) == identity
    assert stored["panel_split_ratio"] == 0.25
    assert stored["monkey_params"]["events"] == 5000
    assert stored["monkey_params"]["throttle"] == 300
    assert stored["monkey_params"] is not DEFAULTS["monkey_params"]
    assert stored["future"] == "old"
    assert "schema_version" not in stored
    assert not reports
    stored["monkey_params"]["events"] = 6000
    assert DEFAULTS == defaults
    run_migrations(stored, 1, lambda *message: reports.append(message))
    assert "future" not in stored
    assert "schema_version" not in stored
    assert stored["monkey_params"]["events"] == 6000
    assert reports == [("WARNING", "Ignored 1 unknown settings key(s): future")]


@pytest.mark.parametrize("run_chain", [False, True])
def test_pruning_reports_sorted_top_level_then_monkey_once(run_chain):
    from core.settings.migrations import prune_unknown_keys, run_migrations

    stored = {"zeta": 1, "alpha": 2, "monkey_params": {"zeta": 3, "alpha": 4}}
    reports = []

    def report(*message):
        reports.append(message)

    if run_chain:
        run_migrations(stored, 1, report)
    else:
        prune_unknown_keys(stored, report)
    prune_unknown_keys(stored, report)
    assert reports == [
        ("WARNING", "Ignored 2 unknown settings key(s): alpha, zeta"),
        ("WARNING", "Ignored 2 unknown monkey_params key(s): alpha, zeta"),
    ]
    assert "zeta" not in stored and "alpha" not in stored
    assert "zeta" not in stored["monkey_params"]
    assert "alpha" not in stored["monkey_params"]


def test_migration_reporters_are_not_shared():
    from core.settings.migrations import run_migrations

    first, second = [], []
    run_migrations({"alpha": 1}, 2, lambda *message: first.append(message))
    run_migrations({"zeta": 1}, 2, lambda *message: second.append(message))
    assert first == [("WARNING", "Ignored 1 unknown settings key(s): alpha")]
    assert second == [("WARNING", "Ignored 1 unknown settings key(s): zeta")]


def test_migration_does_not_swallow_reporter_failure():
    from core.settings.migrations import prune_unknown_keys

    def report(level, message):
        raise RuntimeError("report failure")

    with pytest.raises(RuntimeError, match="report failure"):
        prune_unknown_keys({"future": True}, report)


def test_pure_migrations_import_has_no_settings_or_qt_side_effects(tmp_path):
    script = r'''
import importlib.abc
import os
import sys
from pathlib import Path
import utils.user_data as user_data
import utils.resource_path as resource

root = Path(os.environ["XDG_CONFIG_HOME"])
sentinel = root / "sentinel"
sentinel.write_text("unchanged", encoding="utf-8")
def forbidden_path(*args, **kwargs):
    raise AssertionError("path resolver called")
user_data.user_config_path = forbidden_path
resource.resource_path = forbidden_path
blocked = ("core.settings_manager", "core.log_service", "PySide6", "qfluentwidgets")
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
from core.settings.migrations import run_migrations, prune_unknown_keys
stored = {"left_panel_width": 300, "right_panel_width": 900, "future": 1}
reports = []
run_migrations(stored, 1, lambda *message: reports.append(message))
prune_unknown_keys(stored, lambda *message: reports.append(message))
assert stored["panel_split_ratio"] == 0.25
assert reports == [("WARNING", "Ignored 1 unknown settings key(s): future")]
assert not any(
    name == item or name.startswith(item + ".")
    for name in sys.modules for item in blocked
)
assert sentinel.read_text(encoding="utf-8") == "unchanged"
assert not list(root.rglob("app_settings.json"))
'''
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                 "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR", "TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
