"""使用内存设备快照渲染设备概览的前后布局，不执行 ADB 或读取用户设置。"""

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QScrollArea

from gui.i18n import install_translators
from gui.styles import BaseStyles, FontRole
from gui.styles.typography import typography_manager
from tests.test_device_hub_page import _rich_metadata
from tests.ui_geometry_helpers import wait_for_stable_geometry

parser = argparse.ArgumentParser()
parser.add_argument("--before", action="store_true")
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--font", type=int, default=12)
parser.add_argument("--theme", default="Light")
parser.add_argument("--language", default="zh_CN")
args = parser.parse_args()
out = Path(__file__).parent
app = QApplication([])
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    if (fonts / name).exists():
        QFontDatabase.addApplicationFont(str(fonts / name))
translators = install_translators(app, args.language)
config = replace(BaseStyles.current_font_config(), ui_size=args.font, ui_family="Microsoft YaHei UI")
BaseStyles._sync_legacy_values(config)
typography_manager.apply(config)
app.setFont(BaseStyles.font_for_role(FontRole.UI))
BaseStyles.switch_theme(args.theme)
if args.before:
    spec = importlib.util.spec_from_file_location("device_hub_baseline", out / "gui__pages__device_hub.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    DeviceHubPage = module.DeviceHubPage
else:
    from gui.pages.device_hub import DeviceHubPage
page = DeviceHubPage()
records = _rich_metadata()
page.set_device_metadata(records)
page.set_device_context([records[0]["ip"]], [record["ip"] for record in records], "ready")
window = QScrollArea()
window.setWidgetResizable(True)
window.setWidget(page)
window.resize(args.width, 900 if args.width >= 800 else 700)
window.show()
page.device_cards[0].details_button.click()
wait_for_stable_geometry(app, (window, page, *page.device_cards))
tag = f"{'before' if args.before else 'after'}-{args.theme.lower()}-{args.width}-font{args.font}-{args.language}"
window.grab().save(str(out / f"device-{tag}.png"))
card = page.device_cards[0]
for field in (*card.summary_fields.values(), *card.detail_fields.values(), card.identifier_field):
    assert card.rect().contains(QRect(field.mapTo(card, QPoint()), field.size()))
assert window.horizontalScrollBar().maximum() == 0
window.ensureWidgetVisible(card.copy_details_button)
app.processEvents()
assert window.viewport().rect().contains(
    QRect(card.copy_details_button.mapTo(window.viewport(), QPoint()), card.copy_details_button.size())
)
window.grab().save(str(out / f"device-{tag}-details.png"))
print(json.dumps({
    "tag": tag, "window_width": window.width(), "card_height": card.height(),
    "summary_height": card.summary_container.height(),
    "details_height": card.detail_parameters.height(),
    "horizontal_scroll_max": window.horizontalScrollBar().maximum(),
    "copy_details_reachable": True,
}, ensure_ascii=False))
window.close()
window.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
