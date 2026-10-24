"""验证离屏测试会话补齐系统字体，不依赖字体库恰好为空。"""

import pytest
from PySide6.QtGui import QFontDatabase

from tests import conftest


@pytest.mark.ui
@pytest.mark.parametrize(
    "platform_name,plugin,expected_count",
    [("win32", "offscreen", 4), ("win32", "windows", 0), ("linux", "offscreen", 0)],
)
def test_qt_fixture_loads_windows_offscreen_fonts_with_partial_inventory(
    qt_application, monkeypatch, tmp_path, platform_name, plugin, expected_count,
):
    font_directory = tmp_path / "Fonts"
    font_directory.mkdir()
    filenames = ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf")
    for filename in filenames:
        (font_directory / filename).touch()
    loaded_paths = []
    with monkeypatch.context() as local:
        local.setattr(conftest, "_APPLICATION_REFERENCES", [])
        local.setattr(conftest.sys, "platform", platform_name)
        local.setenv("QT_QPA_PLATFORM", plugin)
        local.setenv("WINDIR", str(tmp_path))
        local.setattr(QFontDatabase, "families", lambda: ["Segoe UI"])
        local.setattr(QFontDatabase, "addApplicationFont", loaded_paths.append)
        session_fixture = conftest.qt_application.__wrapped__()
        try:
            assert next(session_fixture) is qt_application
        finally:
            session_fixture.close()
    expected_paths = [str(font_directory / name) for name in filenames][:expected_count]
    assert loaded_paths == expected_paths
