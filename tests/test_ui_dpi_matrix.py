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
