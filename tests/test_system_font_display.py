"""验证系统字号在受控平台样本及 Qt 显示缩放下保持 pt 语义。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_DISPLAY_PROBE = r"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

app = QApplication([])
if sys.platform == 'win32':
    font_directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf', 'consola.ttf'):
        font_path = font_directory / filename
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))

from gui.styles.typography import FontRole, TypographyManager

general_role = QFontDatabase.SystemFont.GeneralFont
fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
installed_families = QFontDatabase.families()
platform_samples = (
    ('.AppleSystemUIFont', ['.AppleSystemUIFont', 'PingFang SC'], 13.0),
    ('Segoe UI', ['Segoe UI', 'Microsoft YaHei UI'], 9.0),
    ('.AppleSystemUIFont', ['.AppleSystemUIFont', 'PingFang SC'], 12.5),
    ('Segoe UI', ['Segoe UI', 'Microsoft YaHei UI'], 12.5),
)
for family, families, point_size in platform_samples:
    system_font = QFont(family)
    system_font.setPointSizeF(point_size)
    with (
        patch.object(QFontDatabase, 'families', return_value=families),
        patch.object(
            QFontDatabase, 'systemFont',
            side_effect=lambda role: QFont(system_font if role == general_role else fixed_font),
        ),
    ):
        # 平台样本不绘制：另一平台的字体族在当前主机可能尚未安装。
        manager = TypographyManager()
        assert manager.config.ui_family == family, manager.config
        assert manager.config.ui_size == point_size, (family, point_size, manager.config)
        for role, expected in (
            (FontRole.UI, point_size),
            (FontRole.UI_SMALL, max(8, point_size - 1)),
            (FontRole.TITLE, point_size + 4),
        ):
            font = manager.font_for_role(role)
            assert font.pointSizeF() == expected, (family, role, font.pointSizeF())
            assert font.pixelSize() == -1
            assert font.families() == families

# offscreen 的通用别名可能不对应已安装字体，绘制只使用真实可用的主机字体。
family = next(
    (name for name in ('.AppleSystemUIFont', 'Segoe UI', 'Arial')
     if name in installed_families),
    installed_families[0],
)
records = []
for point_size in (9.0, 13.0, 12.5):
    system_font = QFont(family)
    system_font.setPointSizeF(point_size)
    with patch.object(
        QFontDatabase, 'systemFont',
        side_effect=lambda role: QFont(system_font if role == general_role else fixed_font),
    ):
        manager = TypographyManager()
    root = QWidget()
    root.setFont(manager.font_for_role(FontRole.UI))
    root.resize(420, 180)
    root_layout = QVBoxLayout(root)
    scroll = QScrollArea(root)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    root_layout.addWidget(scroll)
    content = QWidget()
    layout = QVBoxLayout(content)
    title = QLabel('ADBLab 字体 Font')
    title.setFont(manager.font_for_role(FontRole.TITLE))
    layout.addWidget(title)
    actions = []
    for index in range(8):
        button = QPushButton(f'执行操作 Run action {index + 1}')
        button.setMinimumHeight(manager.control_height(minimum=32, padding=12))
        layout.addWidget(button)
        actions.append(button)
    scroll.setWidget(content)
    root.show()
    app.processEvents()
    scroll.ensureWidgetVisible(actions[-1], 0, 0)
    app.processEvents()

    assert root.font().pointSizeF() == point_size
    assert actions[-1].font().pointSizeF() == point_size
    assert title.font().pointSizeF() == point_size + 4
    assert scroll.verticalScrollBar().maximum() > 0
    target = actions[-1]
    position = target.mapTo(scroll.viewport(), QPoint(0, 0))
    assert position.y() >= 0
    assert position.y() + target.height() <= scroll.viewport().height()
    assert target.fontMetrics().height() <= target.contentsRect().height()
    assert target.fontMetrics().horizontalAdvance(target.text()) < target.width()

    canvas = root.grab()
    dpr = root.devicePixelRatioF()
    assert canvas.devicePixelRatioF() == dpr
    assert canvas.width() == round(root.width() * dpr)
    assert canvas.height() == round(root.height() * dpr)
    records.append({'point_size': point_size, 'dpr': dpr})
    root.close()
    root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

print('DISPLAY_PROBE=' + json.dumps(records))
"""


@pytest.mark.ui
@pytest.mark.integration
@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 2])
def test_system_point_sizes_remain_stable_under_qt_display_scaling(scale, tmp_path):
    environment = dict(os.environ)
    environment.update(
        QT_QPA_PLATFORM="offscreen",
        QT_SCALE_FACTOR=str(scale),
        XDG_CONFIG_HOME=str(tmp_path),
        LOCALAPPDATA=str(tmp_path),
    )
    # 清除继承的屏幕覆盖，避免外部开发环境给本次显式比例再乘一次。
    for key in ("QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI", "QT_DEVICE_PIXEL_RATIO"):
        environment.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", _DISPLAY_PROBE],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for warning in ("missing font family", "missing glyph"):
        assert warning not in result.stderr.lower(), result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("DISPLAY_PROBE="))
    records = json.loads(line.removeprefix("DISPLAY_PROBE="))
    assert [record["point_size"] for record in records] == [9, 13, 12.5]
    assert [record["dpr"] for record in records] == pytest.approx([scale] * 3)
