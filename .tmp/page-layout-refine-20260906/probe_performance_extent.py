"""只读记录性能页布局测高，使用既有合成会话渲染。"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gui.dialogs.performance_launcher import PerformancePage

original_grab = PerformancePage.grab


def probe(page, *args, **kwargs):
    for name, widget in (
        ("page", page),
        ("columns", page._config_group),
        ("result", page._results_group),
        ("result_view", page._results_group.view),
        ("stack", page._chart_stack),
        ("log", page.log_view),
    ):
        layout = widget.layout()
        print(name, {
            "geometry": widget.geometry().getRect(),
            "hint": widget.sizeHint().toTuple(),
            "minimum_hint": widget.minimumSizeHint().toTuple(),
            "minimum": widget.minimumSize().toTuple(),
            "has_hfw": widget.hasHeightForWidth(),
            "hfw": widget.heightForWidth(widget.width()),
            "layout_minimum": layout.minimumSize().toTuple() if layout else None,
            "layout_hfw": layout.heightForWidth(widget.width()) if layout else None,
        })
    return original_grab(page, *args, **kwargs)


PerformancePage.grab = probe
sys.argv = [str(Path(__file__).with_name("render_pages.py")), "--label", "height-probe",
            "--theme", "Dark", "--width", "860", "--font", "22", "--expanded"]
runpy.run_path(sys.argv[0], run_name="__main__")
