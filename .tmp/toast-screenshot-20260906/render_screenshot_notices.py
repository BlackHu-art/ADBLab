"""以合成截图和内存字体设置检查实际结果 Toast，不访问设备或用户配置。"""

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from gui.dialogs import screenshot_viewer_actions as actions
from gui.features.media import ScreenshotPage
from gui.i18n import install_translators
from gui.styles import BaseStyles, FontRole
from gui.styles.typography import typography_manager
from tests.ui_geometry_helpers import assert_contained, wait_for_stable_geometry

out = Path(__file__).parent
app = QApplication([])
translators = install_translators(app, "zh_CN")
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    if (fonts / name).exists():
        QFontDatabase.addApplicationFont(str(fonts / name))
config = replace(BaseStyles.current_font_config(), ui_size=22, ui_family="Microsoft YaHei UI")
BaseStyles._sync_legacy_values(config)
typography_manager.apply(config)
app.setFont(BaseStyles.font_for_role(FontRole.UI))
BaseStyles.switch_theme("Dark")
shot = QPixmap(420, 660)
shot.fill(QColor("#1c3144"))
painter = QPainter(shot)
painter.setPen(QColor("#f0f5ff"))
painter.setFont(BaseStyles.font_for_role(FontRole.UI))
painter.drawText(shot.rect(), Qt.AlignmentFlag.AlignCenter, "Synthetic screenshot\nNo device access")
painter.end()
path = str(out / "synthetic-screenshot.png")
assert shot.save(path)
page = ScreenshotPage([path])
page.prepare_for_workspace()
page.resize(860, 700)
page.show()
report = []


def capture(name, expected):
    notice = page._adblab_toast_stack.notices[-1]
    notice._timer.stop()
    wait_for_stable_geometry(app, (page, notice, notice.content_edit))
    assert_contained(notice, page)
    assert_contained(notice.titleLabel, notice)
    assert_contained(notice.content_edit, notice)
    assert notice.content_edit.toPlainText() == expected
    assert notice.titleLabel.height() >= notice.titleLabel.heightForWidth(notice.titleLabel.width())
    page.grab().save(str(out / name))
    report.append({
        "image": name, "full_text_length": len(expected), "toast_rect": notice.geometry().getRect(),
        "scroll_maximum": notice.content_edit.verticalScrollBar().maximum(),
    })
    return notice


page.copy_to_clipboard()
copy = capture("screenshot-copy-dark-860-font22.png", actions.tr("Image copied"))
copy.close()
page._delete_file()
page._delete_confirm_timer.stop()
capture("screenshot-confirm-dark-860-font22.png", actions.tr("Click Delete again to confirm"))
error = "无法删除截图：文件正在被其他程序使用，请关闭占用程序后重试。\n" + (
    "D:/synthetic-output/" + "very-long-screenshot-name-" * 28 + "ending-marker.png"
)
with patch.object(actions.os, "remove", side_effect=PermissionError(error)):
    page._delete_file()
notice = capture("screenshot-error-dark-860-font22.png", error)
scroll = notice.content_edit.verticalScrollBar()
assert scroll.maximum() > 0
scroll.setValue(scroll.maximum())
app.processEvents()
page.grab().save(str(out / "screenshot-error-end-dark-860-font22.png"))
print(json.dumps(report, ensure_ascii=False))
page.close()
page.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
