"""仅缩短运行详情以隔离长文本换行，保留真实状态和时间值。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import gui.widgets.performance_progress as progress

original_tr = progress.tr
progress.tr = lambda text: (
    "{elapsed} / {duration}"
    if text == "预计进度 {percent}% · 已用 {elapsed} / 计划 {duration}"
    else original_tr(text)
)
raise SystemExit(pytest.main([
    "-q", "tests/test_performance_responsive.py",
    "-k", "cards_reflow_without or large_font_running_summary",
]))
