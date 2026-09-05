"""隔离子进程中的 Qt 缩放探针契约。"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


def run_probe(scale: str) -> dict[str, float]:
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QT_SCALE_FACTOR"] = scale
    if scale in {"1.25", "1.5"}:
        environment["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    result = subprocess.run(
        [sys.executable, "-m", "tests.ui_dpi_probe"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "QThread: Destroyed" not in result.stderr
    assert "deleted QObject" not in result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("scale", ["1", "1.25", "1.5", "2"])
def test_dpi_probe_reports_consistent_logical_and_physical_size(scale):
    result = run_probe(scale)
    assert result["dpr"] == pytest.approx(float(scale), abs=0.01)
    assert result["pixmap_width"] == pytest.approx(
        round(result["logical_width"] * result["dpr"]), abs=1
    )


@pytest.mark.parametrize("app_scale,external_scale,expected", [
    ("Auto", None, 1), ("Auto", "1.25", 1.25),
    (1, None, 1), (1.25, None, 1.25), (1.5, "2", 1.5),
    (1.75, None, 1.75), (2, None, 2), ("invalid", None, 1),
])
def test_saved_gui_scale_sets_real_qt_dpr_without_changing_window_aspect_ratio(
    tmp_path, app_scale, external_scale, expected,
):
    environment = dict(os.environ, LOCALAPPDATA=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path))
    for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_SCALE_FACTOR_ROUNDING_POLICY"):
        environment.pop(key, None)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    if external_scale is not None:
        environment["QT_SCALE_FACTOR"] = external_scale
    result = subprocess.run(
        [sys.executable, "-m", "tests.ui_dpi_probe", "--app-scale", json.dumps(app_scale)],
        env=environment, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    snapshot = json.loads(result.stdout)
    assert snapshot["dpr"] == pytest.approx(expected, abs=0.01)
    assert (snapshot["logical_width"], snapshot["logical_height"]) == (200, 120)
    assert snapshot["pixmap_width"] == round(200 * expected)
    assert snapshot["pixmap_height"] == round(120 * expected)
