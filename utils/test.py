import sys
from PySide6.QtWidgets import (QApplication, QWidget, QGridLayout, QLabel, 
                              QScrollArea, QStyle, QVBoxLayout, QComboBox, QHBoxLayout, QPushButton)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFontDatabase, QFont, QPainter
import qtawesome as qta

class IconBrowser(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multi-Icon Library Browser")
        self.setGeometry(300, 300, 1024, 768)
        
        # 初始化图标库选项
        self.icon_libraries = {
            "Qt Standard": self.load_qt_icons,
            "QtAwesome (FontAwesome)": self.load_qtawesome_icons,
            "Material Design": self.load_material_icons
        }
        
        self._init_ui()
        self.load_icons("Qt Standard")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # 下拉选择框样式优化
        self.combo = QComboBox()
        self.combo.setFixedWidth(200)
        self.combo.addItems(self.icon_libraries.keys())
        self.combo.setStyleSheet("""
            QComboBox {
                font: 14px;
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
        """)
        self.combo.currentTextChanged.connect(self.load_icons)
        main_layout.addWidget(self.combo, alignment=Qt.AlignCenter)

        # 滚动区域优化
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setSpacing(20)  # 增加网格间距
        self.grid.setContentsMargins(20, 20, 20, 20)
        scroll.setWidget(self.content)
        main_layout.addWidget(scroll)

    def load_icons(self, library_name):
        # 清空布局前先删除所有子控件
        for i in reversed(range(self.grid.count())): 
            self.grid.itemAt(i).widget().deleteLater()
        
        # 重置布局参数
        self.grid.setRowStretch(self.grid.rowCount(), 0)
        self.grid.setColumnStretch(self.grid.columnCount(), 0)
        
        # 加载新图标
        self.icon_libraries[library_name]()

    def load_qt_icons(self):
        """加载Qt标准图标"""
        row = col = 0
        for name, value in QStyle.StandardPixmap.__members__.items():
            if name.startswith('SP_'):
                icon = self.style().standardIcon(value)
                if not icon.isNull():
                    self._add_item(
                        icon=icon,
                        title=name.replace("SP_", ""),
                        tooltip=f"Qt Standard: {name}",
                        row=row,
                        col=col
                    )
                    col = (col + 1) % 4
                    row += 1 if col == 0 else 0

    def load_qtawesome_icons(self):
        """动态加载QtAwesome全部图标"""
        try:
            # 使用官方API获取所有图标名称
            all_icons = qta.icons()
            
            # 分页加载配置
            self.current_page = 0
            self.page_size = 200  # 调整为每页200个图标
            self.all_icon_names = sorted(all_icons)
            
            self._load_qtawesome_page()
            self._add_pagination_controls()
            
        except Exception as e:
            print(f"加载QtAwesome图标失败: {str(e)}")

    def _load_qtawesome_page(self):
        """加载当前分页的图标（优化版）"""
        start = self.current_page * self.page_size
        end = start + self.page_size
        icons_to_show = self.all_icon_names[start:end]
        
        row = col = 0
        for icon_name in icons_to_show:
            try:
                # 创建基础图标
                base_icon = qta.icon(icon_name, color="#2196F3")
                if base_icon.isNull():
                    continue
                    
                self._add_item(
                    icon=base_icon,
                    title=icon_name,
                    tooltip=f"Icon: {icon_name}\n复制名称：{icon_name}",
                    row=row,
                    col=col
                )
                
                col = (col + 1) % 4
                row += 1 if col == 0 else 0
                
            except Exception as e:
                print(f"加载图标 {icon_name} 失败: {str(e)}")

    def _add_pagination_controls(self):
        """添加分页导航栏"""
        pagination = QWidget()
        layout = QHBoxLayout(pagination)
        
        btn_prev = QPushButton("上一页")
        btn_prev.clicked.connect(lambda: self._change_page(-1))
        btn_next = QPushButton("下一页")
        btn_next.clicked.connect(lambda: self._change_page(1))
        
        self.lbl_page = QLabel()
        self._update_page_label()
        
        layout.addWidget(btn_prev)
        layout.addWidget(self.lbl_page)
        layout.addWidget(btn_next)
        
        self.grid.addWidget(pagination, self.grid.rowCount()+1, 0, 1, 4)

    def _change_page(self, delta):
        """切换分页"""
        new_page = self.current_page + delta
        max_page = len(self.all_icon_names) // self.page_size
        
        if 0 <= new_page <= max_page:
            self.current_page = new_page
            self.load_icons("QtAwesome (FontAwesome)")  # 重新加载当前库
            self._update_page_label()

    def _update_page_label(self):
        """更新分页信息"""
        total = len(self.all_icon_names)
        current_start = self.current_page * self.page_size + 1
        current_end = min((self.current_page + 1) * self.page_size, total)
        self.lbl_page.setText(f"显示 {current_start}-{current_end} / 共 {total} 个图标")

    def load_material_icons(self):
        """加载Material Design图标"""
        font_id = QFontDatabase.addApplicationFont("materialdesignicons-webfont.ttf")
        if font_id == -1: return
        
        font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 24)
        icons = [
            ("\uF4A9", "账户", "#E91E63"),
            ("\uF156", "设置", "#3F51B5"),
            ("\uF2C7", "下载", "#009688"),
            ("\uF1C9", "上传", "#FF5722")
        ]
        
        row = col = 0
        for code, title, color in icons:
            label = QLabel(code)
            label.setFont(font)
            label.setStyleSheet(f"color: {color};")
            label.setAlignment(Qt.AlignCenter)
            
            self._add_custom_item(
                widget=label,
                title=title,
                tooltip=f"Material Design: {code}",
                row=row,
                col=col
            )
            col = (col + 1) % 4
            row += 1 if col == 0 else 0

    def _add_item(self, icon, title, tooltip, row, col):
        """通用图标项组件"""
        container = QWidget()
        container.setMinimumSize(180, 180)  # 固定最小尺寸防止重叠
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 图标显示
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)
        
        # 可复制文本标签
        text_label = QLabel(title)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("font: 14px; color: #666;")
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 允许复制
        text_label.setCursor(Qt.IBeamCursor)  # 显示文本光标
        layout.addWidget(text_label)
        
        container.setToolTip(tooltip)
        self.grid.addWidget(container, row, col)

    def _add_custom_item(self, widget, title, tooltip, row, col):
        """自定义组件项"""
        container = QWidget()
        container.setMinimumSize(180, 180)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 图标部件
        widget.setFixedSize(64, 64)
        layout.addWidget(widget, alignment=Qt.AlignCenter)
        
        # 可复制文本标签
        text_label = QLabel(title)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("font: 14px; color: #666;")
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_label.setCursor(Qt.IBeamCursor)
        layout.addWidget(text_label)
        
        container.setToolTip(tooltip)
        self.grid.addWidget(container, row, col)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IconBrowser()
    window.show()
    sys.exit(app.exec())