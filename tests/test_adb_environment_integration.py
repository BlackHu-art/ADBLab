"""应用组合根的客户端重检与会话归属接线回归。"""

from types import SimpleNamespace

from gui.main_frame import MainFrame


def test_recheck_retires_input_sessions_before_probing_new_client():
    calls = []
    frame = SimpleNamespace(
        _closing=False,
        _adb_environment=SimpleNamespace(recheck=lambda: calls.append("recheck")),
        left_panel=SimpleNamespace(_scrcpy_tab=SimpleNamespace(
            invalidate_adb_input_sessions=lambda: calls.append("retire"),
        )),
    )
    MainFrame.recheck_adb_environment(frame)
    assert calls == ["retire", "recheck"]
