"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import list as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.list import ADBWorker as ADBWorker
    from gui.features.file_explorer.list import DirectoryListWorker as DirectoryListWorker
    from gui.features.file_explorer.list import FileExplorerItemDelegate as FileExplorerItemDelegate
    from gui.features.file_explorer.list import FileExplorerList as FileExplorerList
    from gui.features.file_explorer.list import FileModifiedItem as FileModifiedItem
    from gui.features.file_explorer.list import FileSizeItem as FileSizeItem
    from gui.features.file_explorer.list import FileTypeItem as FileTypeItem
    from gui.features.file_explorer.list import Generator as Generator
    from gui.features.file_explorer.list import QFontMetrics as QFontMetrics
    from gui.features.file_explorer.list import QIcon as QIcon
    from gui.features.file_explorer.list import QItemSelection as QItemSelection
    from gui.features.file_explorer.list import QItemSelectionModel as QItemSelectionModel
    from gui.features.file_explorer.list import QModelIndex as QModelIndex
    from gui.features.file_explorer.list import Qt as Qt
    from gui.features.file_explorer.list import QTableWidgetItem as QTableWidgetItem
    from gui.features.file_explorer.list import QThreadGroupShutdownTask as QThreadGroupShutdownTask
    from gui.features.file_explorer.list import QTimer as QTimer
    from gui.features.file_explorer.list import QWidget as QWidget
    from gui.features.file_explorer.list import TableItemDelegate as TableItemDelegate
    from gui.features.file_explorer.list import cast as cast
    from gui.features.file_explorer.list import explorer_service as explorer_service
    from gui.features.file_explorer.list import file_explorer_icon as file_explorer_icon
    from gui.features.file_explorer.list import get_fluent_icon as get_fluent_icon
    from gui.features.file_explorer.list import os as os
    from gui.features.file_explorer.list import perf_counter as perf_counter
    from gui.features.file_explorer.list import tr as tr

sys.modules[__name__] = _implementation
