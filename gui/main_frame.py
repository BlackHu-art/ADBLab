from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGroupBox,
    QComboBox, QPushButton, QListWidget, QLineEdit, QLabel,
    QMessageBox
)
from PySide6.QtGui import QAction, QCursor
from PySide6.QtCore import Qt, QPoint
from .log_panel import LogPanel
from .styles import Styles, get_default_font
from controllers.adb_controller import ADBController
from controllers.email_controller import EmailController
from controllers.log_controller import LogController
from gui.custom_menu_bar import CustomMenuBar


class MainFrame(QMainWindow):
    DEFAULT_WIDTH = 1100  # 默认窗口宽度
    DEFAULT_HEIGHT = 800  # 默认窗口高度
    MARGIN = 5  # 窗口边缘检测范围

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADB Manager GUI")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self._drag_pos = None
        self._resizing = False
        self._resize_direction = None

        # 初始化控制器
        self.adb_controller = ADBController(self)
        self.email_controller = EmailController(self)
        self.log_controller = LogController(self)

        self._setup_ui()
        self._create_menu()

    def _create_menu(self):
        """ 创建自定义菜单栏 """
        menu_bar = CustomMenuBar(self)
        self.setMenuBar(menu_bar)

        # File 菜单
        file_menu = menu_bar.addMenu("File")
        restore_action = QAction("Restore Default Size", self)
        restore_action.triggered.connect(self.restore_default_size)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(restore_action)
        file_menu.addAction(exit_action)

        # Help 菜单
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def show_about_dialog(self):
        QMessageBox.about(self, "About", "ADB Manager GUI\nVersion 1.0\nPySide6 Example")

    def restore_default_size(self):
        """ 一键恢复初始窗口大小 """
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def _setup_ui(self):
        """ 设置 UI 布局 """
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # ---------------- Left Panel ----------------
        left_panel = QWidget()
        left_panel.setFixedWidth(500)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(1)
        left_layout.setContentsMargins(1, 1, 1, 1)

        # Device Management
        device_group = QGroupBox("Device Management")
        device_group.setFont(get_default_font())
        device_layout = QVBoxLayout()
        # IP Address Entry and Connect Button
        ip_layout = QHBoxLayout()
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(get_default_font())
        ip_layout.addWidget(self.ip_entry)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFont(get_default_font())
        self.btn_connect.clicked.connect(self.adb_controller.on_connect_device)
        ip_layout.addWidget(self.btn_connect)
        device_layout.addLayout(ip_layout)
        # Device List
        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(get_default_font())
        device_layout.addWidget(self.listbox_devices)
        device_group.setLayout(device_layout)
        left_layout.addWidget(device_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setFont(get_default_font())
        actions_layout = QVBoxLayout()

        # Row 1: Refresh Devices, Get Info, Get Activity
        row1 = QHBoxLayout()
        self.btn_refresh_devices = QPushButton("Refresh")
        self.btn_refresh_devices.setFont(get_default_font())
        self.btn_refresh_devices.clicked.connect(self.adb_controller.on_refresh_devices)
        row1.addWidget(self.btn_refresh_devices)
        self.btn_get_device_info = QPushButton("Device Info")
        self.btn_get_device_info.setFont(get_default_font())
        self.btn_get_device_info.clicked.connect(self.adb_controller.on_get_device_info)
        row1.addWidget(self.btn_get_device_info)
        self.btn_current_activity = QPushButton("Current Activity")
        self.btn_current_activity.setFont(get_default_font())
        self.btn_current_activity.clicked.connect(self.adb_controller.on_current_activity)
        row1.addWidget(self.btn_current_activity)
        actions_layout.addLayout(row1)

        # Row 2: Select APK
        row2 = QHBoxLayout()
        self.btn_select_apk = QPushButton("Select APK")
        self.btn_select_apk.setFont(get_default_font())
        self.btn_select_apk.clicked.connect(self.adb_controller.on_select_apk)
        row2.addWidget(self.btn_select_apk)
        actions_layout.addLayout(row2)

        # Row 3: ANR Files, Kill Apps, Package List
        row3 = QHBoxLayout()
        self.btn_get_anr_files = QPushButton("Get ANR Files")
        self.btn_get_anr_files.setFont(get_default_font())
        self.btn_get_anr_files.clicked.connect(self.adb_controller.on_get_anr_files)
        row3.addWidget(self.btn_get_anr_files)
        self.btn_kill_all_apps = QPushButton("Kill All Apps")
        self.btn_kill_all_apps.setFont(get_default_font())
        self.btn_kill_all_apps.clicked.connect(self.adb_controller.on_kill_all_apps)
        row3.addWidget(self.btn_kill_all_apps)
        self.btn_get_packages = QPushButton("Installed Apps")
        self.btn_get_packages.setFont(get_default_font())
        self.btn_get_packages.clicked.connect(self.adb_controller.on_get_installed_packages)
        row3.addWidget(self.btn_get_packages)
        actions_layout.addLayout(row3)
        actions_group.setLayout(actions_layout)
        left_layout.addWidget(actions_group)

        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # ---------------- Right Log Panel ----------------
        self.log_panel = LogPanel()
        main_layout.addWidget(self.log_panel)

    def log_message(self, level, message):
        self.log_panel.log_message(level, message)

    def clear_log(self):
        self.log_panel.clear()

    # ---------------- Window Drag & Resize ----------------

    def mousePressEvent(self, event):
        """ Handle window drag and resize """
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._resizing = self._get_resize_direction(event.pos()) is not None
            event.accept()

    def mouseMoveEvent(self, event):
        """ Handle mouse movement: update cursor or resize window """
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            if self._resizing:
                self._resize_window(event.globalPosition().toPoint())
            else:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            self._update_cursor(event.pos())

    def mouseReleaseEvent(self, event):
        """ Clear drag & resize state """
        self._drag_pos = None
        self._resizing = False

    def _update_cursor(self, pos):
        """ Update cursor shape for resizing """
        resize_direction = self._get_resize_direction(pos)
        self.setCursor(QCursor(resize_direction) if resize_direction else QCursor(Qt.ArrowCursor))

    def _get_resize_direction(self, pos):
        """ Determine if mouse is near window edge for resizing """
        rect = self.rect()
        if pos.x() < self.MARGIN or pos.x() > rect.width() - self.MARGIN:
            return Qt.SizeHorCursor
        elif pos.y() < self.MARGIN or pos.y() > rect.height() - self.MARGIN:
            return Qt.SizeVerCursor
        return None

    def _resize_window(self, global_pos):
        """ Resize window based on cursor movement """
        delta = global_pos - self.pos()
        self.resize(delta.x(), delta.y())
