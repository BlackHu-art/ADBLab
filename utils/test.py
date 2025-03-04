import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QTextEdit, QToolBar, QLineEdit, QPushButton, QMenu, QStyle, QHBoxLayout
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QSize

class TermiusClone(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        # 允许窗口背景透明（可选）
        # self.setAttribute(Qt.WA_TranslucentBackground)
        # self.setWindowTitle("Termius Clone")
        self.setGeometry(100, 100, 1200, 800)
        self.setup_ui()
        self.load_sample_data()
        self.setup_styles()
        self.menuBar().setVisible(False)

    def setup_ui(self):
        main_splitter = QSplitter()
        
        # 左侧边栏
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setIndentation(15)
        self.sidebar.itemDoubleClicked.connect(self.connect_to_server)
        
        # 右侧主区域
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        
        main_splitter.addWidget(self.sidebar)
        main_splitter.addWidget(self.tab_widget)
        main_splitter.setSizes([200, 1000])
        
        # 主工具栏
        main_toolbar = QToolBar("Main Toolbar")
        main_toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(main_toolbar)
        
        # 左侧工具按钮
        self.new_action = QAction(QIcon.fromTheme("list-add"), "New", self)
        self.new_action.triggered.connect(self.new_connection)
        main_toolbar.addAction(self.new_action)
        
        self.edit_action = QAction(QIcon.fromTheme("edit"), "Edit", self)
        self.edit_action.triggered.connect(self.edit_item)
        main_toolbar.addAction(self.edit_action)
        
        self.delete_action = QAction(QIcon.fromTheme("edit-delete"), "Delete", self)
        self.delete_action.triggered.connect(self.delete_item)
        main_toolbar.addAction(self.delete_action)
        
        main_toolbar.addSeparator()
        
        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setFixedWidth(200)
        main_toolbar.addWidget(self.search_box)
        
        # 右侧菜单按钮
        main_toolbar.addSeparator()
        self.setup_menu_buttons(main_toolbar)
        
        self.setCentralWidget(main_splitter)
        
        # 上下文菜单
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.show_context_menu)

    def setup_menu_buttons(self, toolbar):
        menu_widget = QWidget()
        menu_layout = QHBoxLayout()
        menu_layout.setContentsMargins(0, 0, 0, 0)
        menu_layout.setSpacing(5)
        
        # 文件菜单
        self.file_btn = QPushButton("File")
        file_menu = QMenu(self)
        file_menu.addAction("New Window").triggered.connect(self.new_window)
        file_menu.addSeparator()
        file_menu.addAction("Settings").triggered.connect(self.show_settings)
        file_menu.addSeparator()
        file_menu.addAction("Exit").triggered.connect(self.close)
        self.file_btn.setMenu(file_menu)
        menu_layout.addWidget(self.file_btn)
        
        # 编辑菜单
        self.edit_btn = QPushButton("Edit")
        edit_menu = QMenu(self)
        edit_menu.addAction("Copy").triggered.connect(self.copy_text)
        edit_menu.addAction("Paste").triggered.connect(self.paste_text)
        self.edit_btn.setMenu(edit_menu)
        menu_layout.addWidget(self.edit_btn)
        
        # 视图菜单
        self.view_btn = QPushButton("View")
        view_menu = QMenu(self)
        self.fullscreen_action = view_menu.addAction("Toggle Full Screen")
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addSeparator()
        view_menu.addAction("Zoom In").triggered.connect(self.zoom_in)
        view_menu.addAction("Zoom Out").triggered.connect(self.zoom_out)
        self.view_btn.setMenu(view_menu)
        menu_layout.addWidget(self.view_btn)
        
        # 帮助菜单
        self.help_btn = QPushButton("Help")
        help_menu = QMenu(self)
        help_menu.addAction("Documentation").triggered.connect(self.show_docs)
        help_menu.addSeparator()
        help_menu.addAction("About").triggered.connect(self.show_about)
        self.help_btn.setMenu(help_menu)
        menu_layout.addWidget(self.help_btn)
        
        menu_widget.setLayout(menu_layout)
        toolbar.addWidget(menu_widget)

    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2D2D2D; }
            QTreeWidget { 
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: none;
            }
            QTabWidget::pane { border: 0; background: #1E1E1E; }
            QTabBar::tab { 
                background: #333333;
                color: #FFFFFF;
                padding: 8px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background: #1E1E1E; }
            QTextEdit { 
                background-color: #1E1E1E;
                color: #FFFFFF;
                font-family: Consolas;
                font-size: 12pt;
                border: none;
            }
            QPushButton { 
                background: transparent; 
                color: white;
                padding: 5px;
                border: none;
            }
            QPushButton:hover { background: #404040; }
        """)

    def load_sample_data(self):
        data = {
            "Groups": [{
                "name": "Production",
                "hosts": [
                    {"name": "Web Server 1", "address": "192.168.1.100"},
                    {"name": "DB Server", "address": "192.168.1.101"}
                ]
            }]
        }
        for group in data["Groups"]:
            group_item = QTreeWidgetItem(self.sidebar)
            group_item.setText(0, group["name"])
            group_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
            for host in group["hosts"]:
                host_item = QTreeWidgetItem(group_item)
                host_item.setText(0, host["name"])
                host_item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
                host_item.setData(0, Qt.UserRole, host["address"])
        self.sidebar.expandAll()

    # 以下是所有必需的最小化方法实现
    def show_context_menu(self, position):
        item = self.sidebar.currentItem()
        if not item: return
        menu = QMenu()
        connect_action = menu.addAction("Connect")
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Delete")
        action = menu.exec_(self.sidebar.mapToGlobal(position))
        if action == connect_action: self.connect_to_server(item)
        elif action == edit_action: self.edit_item()
        elif action == delete_action: self.delete_item()

    def connect_to_server(self, item):
        if item.childCount() == 0:
            address = item.data(0, Qt.UserRole)
            self.create_new_tab(f"SSH: {address}", f"Connecting to {address}...\n")

    def create_new_tab(self, title, content):
        terminal = QTextEdit()
        terminal.setPlainText(content)
        self.tab_widget.addTab(terminal, title)

    def close_tab(self, index):
        self.tab_widget.removeTab(index)

    def new_connection(self): pass
    def edit_item(self): pass
    def delete_item(self): pass
    def new_window(self): TermiusClone().show()
    def show_settings(self): pass
    def copy_text(self): pass
    def paste_text(self): pass
    def toggle_fullscreen(self): self.showFullScreen() if not self.isFullScreen() else self.showNormal()
    def zoom_in(self): pass
    def zoom_out(self): pass
    def show_docs(self): pass
    def show_about(self): pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TermiusClone()
    window.show()
    sys.exit(app.exec())