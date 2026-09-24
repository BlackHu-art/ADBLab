"""应用管理表格材质跟随实际宿主，像素验证不依赖桌面壁纸或真实设备。"""

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QFrame, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import TableWidget, TreeView, TreeWidget, setCustomStyleSheet
from shiboken6 import isValid

from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.app_manager_material import AppManagerMaterial
from gui.dialogs.file_explorer_list import FileExplorerItemDelegate
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class MaterialHost(QWidget):
    """用已知色块代替系统 backdrop，只提供生产窗口已有的状态读取边界。"""

    def __init__(self, mica):
        super().__init__()
        self.mica = mica
        self.backdrop = QColor("#6388ad")

    def isMicaEffectEnabled(self):
        return self.mica

    def setMicaEffectEnabled(self, enabled):
        self.mica = enabled
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.backdrop)


@pytest.fixture
def material_view(qt_application):
    hosts = []

    def build(theme, mica, view_type=TreeView):
        BaseStyles.switch_theme(theme)
        host = MaterialHost(mica)
        hosts.append(host)
        owner = QWidget(host)
        outer = QVBoxLayout(host)
        outer.addWidget(owner)
        layout = QVBoxLayout(owner)
        view = view_type(owner)
        view.setObjectName("materialTestView")
        view.setRootIsDecorated(False)
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if isinstance(view, TreeWidget):
            from PySide6.QtWidgets import QTreeWidgetItem

            view.setHeaderLabels(["Name", "Package"])
            for row in range(3):
                view.addTopLevelItem(QTreeWidgetItem([f"App {row}", f"example.app{row}"]))
        else:
            model = QStandardItemModel(view)
            model.setHorizontalHeaderLabels(["Name", "Package"])
            for row in range(3):
                model.appendRow([QStandardItem(f"App {row}"), QStandardItem(f"example.app{row}")])
            view.setModel(model)
        view.header().setStretchLastSection(True)
        view.setColumnWidth(0, 180)
        styles = []
        for name in ("Light", "Dark"):
            styles.append(
                f"QTreeView {{ background-color: {BaseStyles.color_for(name, 'INPUT_BG')}; "
                f"alternate-background-color: {BaseStyles.color_for(name, 'INPUT_BG_HOVER')}; }}"
            )
        setCustomStyleSheet(view, *styles)
        layout.addWidget(view)
        material = AppManagerMaterial(owner, (view,))
        host.resize(660, 340)
        host.show()
        qt_application.processEvents()
        return host, owner, view, material

    yield build
    for host in hosts:
        host.close()
        host.deleteLater()


def pixel(host, widget, point):
    image = host.grab().toImage()
    position = widget.mapTo(host, point)
    scale = image.devicePixelRatio()
    return image.pixelColor(round(position.x() * scale), round(position.y() * scale))


def row_pixel(host, view, row):
    rect = view.visualRect(view.model().index(row, 1))
    return pixel(host, view.viewport(), QPoint(rect.right() - 30, rect.center().y()))


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
@pytest.mark.parametrize("view_type", [TreeView, TreeWidget])
def test_app_views_match_file_table_rows_header_and_blank(
    material_view, qt_application, theme, mica, view_type,
):
    host, owner, view, _material = material_view(theme, mica, view_type)
    reference = TableWidget(owner)
    reference.setItemDelegate(FileExplorerItemDelegate(reference))
    reference.setFrameShape(QFrame.Shape.NoFrame)
    reference.setColumnCount(2)
    reference.setHorizontalHeaderLabels(["Name", "Package"])
    reference.verticalHeader().hide()
    reference.setRowCount(3)
    for row in range(3):
        reference.setItem(row, 0, QTableWidgetItem(f"App {row}"))
        reference.setItem(row, 1, QTableWidgetItem(f"example.app{row}"))
    reference.horizontalHeader().setStretchLastSection(True)
    owner.layout().addWidget(reference)
    host.resize(660, 720)
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    host.setFocus()
    QTest.mouseMove(host, QPoint(0, 0))
    qt_application.processEvents()
    blank = pixel(host, view.viewport(), QPoint(300, view.viewport().height() - 20))
    header = pixel(host, view.header().viewport(), QPoint(view.header().width() - 35, 15))
    ordinary = row_pixel(host, view, 0)
    alternate = row_pixel(host, view, 1)

    reference_blank = pixel(
        host, reference.viewport(), QPoint(300, reference.viewport().height() - 20),
    )
    assert blank == reference_blank == host.backdrop
    assert header == pixel(
        host, reference.horizontalHeader().viewport(),
        QPoint(reference.horizontalHeader().width() - 35, 15),
    ) == host.backdrop
    # Fluent 表格从首行绘制条纹，Qt 树视图从第二行开始；比较相同行状态。
    assert ordinary == row_pixel(host, reference, 1) == host.backdrop
    assert alternate == row_pixel(host, reference, 0)
    assert 0 < abs(alternate.lightness() - ordinary.lightness()) <= 6


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("view_type", [TreeView, TreeWidget])
def test_mica_toggle_refreshes_visible_and_hidden_views(
    material_view, qt_application, theme, view_type,
):
    host, owner, view, _material = material_view(theme, False, view_type)
    assert row_pixel(host, view, 0) == host.backdrop
    host.setMicaEffectEnabled(True)
    wait_until(qt_application, lambda: row_pixel(host, view, 0) == host.backdrop)

    owner.hide()
    host.setMicaEffectEnabled(False)
    host.backdrop = QColor("#906f45")
    qt_application.processEvents()
    owner.show()
    wait_until(qt_application, lambda: row_pixel(host, view, 0) == host.backdrop)


@pytest.mark.parametrize("mica", [False, True])
@pytest.mark.parametrize("view_type", [TreeView, TreeWidget])
def test_material_theme_round_trip_keeps_selection_and_item_identity(
    material_view, qt_application, mica, view_type,
):
    host, _owner, view, _material = material_view("Light", mica, view_type)
    index = view.model().index(1, 0)
    view.setCurrentIndex(index)
    for theme in ("Dark", "Light"):
        BaseStyles.switch_theme(theme)
        qt_application.processEvents()
        expected = host.backdrop
        assert row_pixel(host, view, 0) == expected
        assert view.currentIndex() == index
        selected = row_pixel(host, view, 1)
        view.selectionModel().clearSelection()
        assert selected != row_pixel(host, view, 1)
        view.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        header = pixel(host, view.header().viewport(), QPoint(view.header().width() - 35, 15))
        assert header == expected


def test_reparenting_rebinds_material_to_actual_window(material_view, qt_application):
    source, owner, view, _material = material_view("Light", False)
    target = MaterialHost(True)
    target.backdrop = QColor("#906f45")
    target.resize(660, 340)
    layout = QVBoxLayout(target)
    layout.addWidget(owner)
    target.show()
    try:
        wait_until(qt_application, lambda: row_pixel(target, view, 0) == target.backdrop)
        source.setMicaEffectEnabled(True)
        target.setMicaEffectEnabled(False)
        expected = target.backdrop
        wait_until(qt_application, lambda: row_pixel(target, view, 0) == expected)
    finally:
        target.close()
        target.deleteLater()


def test_destroying_page_disconnects_theme_and_host_callbacks(material_view, qt_application):
    host, owner, view, material = material_view("Light", True)
    owner.deleteLater()
    qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(owner)
    assert not isValid(view)
    assert not isValid(material)

    BaseStyles.switch_theme("Dark")
    host.setMicaEffectEnabled(False)
    qt_application.processEvents()


def test_stopped_material_ignores_late_refreshes(material_view, qt_application, monkeypatch):
    host, _owner, _view, material = material_view("Light", False)
    updates = []
    monkeypatch.setattr(material, "_apply_view", lambda *args: updates.append(args))
    material.stop()
    material.stop()

    host.setMicaEffectEnabled(True)
    BaseStyles.switch_theme("Dark")
    material.refresh(force=True)
    qt_application.processEvents()
    assert updates == []


@pytest.fixture
def app_material_view(qt_application, monkeypatch):
    def reject_worker(*_args, **_kwargs):
        pytest.fail("材质测试不得启动设备 worker")

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", reject_worker)
    hosts = []

    def build(theme, view_name):
        BaseStyles.switch_theme(theme)
        host = MaterialHost(False)
        hosts.append(host)
        page = AppManagerPage(host)
        QVBoxLayout(host).addWidget(page)
        page._populate([
            (f"示例 {row}", f"com.example.app{row}", "Enabled", "User")
            for row in range(3)
        ])
        host.resize(1040, 800)
        host.show()
        if view_name == "tree":
            QTest.mouseClick(page.view_toggle, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        view = getattr(page, view_name)
        assert view.isVisible()
        return host, page, view

    yield build
    for host in hosts:
        for page in host.findChildren(AppManagerPage):
            page.request_dispose("test")
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("view_name", ["tree", "icon_list"])
def test_integrated_app_views_reveal_material_and_preserve_selection(
    app_material_view, qt_application, theme, view_name,
):
    host, page, view = app_material_view(theme, view_name)
    assert row_pixel(host, view, 0) == host.backdrop
    host.setMicaEffectEnabled(True)
    wait_until(qt_application, lambda: row_pixel(host, view, 0) == host.backdrop)

    header = pixel(host, view.header().viewport(), QPoint(view.header().width() - 35, 15))
    blank = pixel(host, view.viewport(), QPoint(300, view.viewport().height() - 20))
    alternate = row_pixel(host, view, 1)
    assert header == host.backdrop
    assert blank == host.backdrop
    assert 0 < abs(alternate.lightness() - host.backdrop.lightness()) <= 6

    index = view.model().index(1, 0)
    view.setCurrentIndex(index)
    assert row_pixel(host, view, 1) != alternate
    selected_packages = set(page.selected_packages)
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    qt_application.processEvents()
    assert row_pixel(host, view, 0) == host.backdrop
    assert page.selected_packages == selected_packages
    assert view.currentIndex() == index

    host.setMicaEffectEnabled(False)
    expected = host.backdrop
    wait_until(qt_application, lambda: row_pixel(host, view, 0) == expected)


def test_request_dispose_stops_material_before_page_destruction(
    app_material_view, qt_application, monkeypatch,
):
    host, page, _view = app_material_view("Light", "tree")
    updates = []
    material = page._form_controller._material
    monkeypatch.setattr(material, "_apply_view", lambda *args: updates.append(args))
    assert page.request_dispose("test")
    assert isValid(page)

    host.setMicaEffectEnabled(True)
    BaseStyles.switch_theme("Dark")
    qt_application.processEvents()
    assert updates == []
