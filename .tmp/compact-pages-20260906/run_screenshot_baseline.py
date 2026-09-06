"""仅在当前进程加载截图修改前的源码，隔离比较 Qt 测试退出路径。"""

import importlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_SCALE_FACTOR", "1")

for module_name, snapshot in (
    ("gui.dialogs.screenshot_viewer_ui", "gui__dialogs__screenshot_viewer_ui.py"),
    ("gui.features.media", "gui__features__media.py"),
):
    module = importlib.import_module(module_name)
    exec(compile(Path(__file__).with_name(snapshot).read_bytes(), module.__file__, "exec"), module.__dict__)

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
