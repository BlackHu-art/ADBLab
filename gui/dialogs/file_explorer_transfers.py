"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import transfers as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.transfers import ADBWorker as ADBWorker
    from gui.features.file_explorer.transfers import Callable as Callable
    from gui.features.file_explorer.transfers import FileExplorerPage as FileExplorerPage
    from gui.features.file_explorer.transfers import (
        FileTransferCoordinator as FileTransferCoordinator,
    )
    from gui.features.file_explorer.transfers import LogService as LogService
    from gui.features.file_explorer.transfers import Protocol as Protocol
    from gui.features.file_explorer.transfers import QObject as QObject
    from gui.features.file_explorer.transfers import Qt as Qt
    from gui.features.file_explorer.transfers import QThread as QThread
    from gui.features.file_explorer.transfers import (
        QThreadGroupShutdownTask as QThreadGroupShutdownTask,
    )
    from gui.features.file_explorer.transfers import QTimer as QTimer
    from gui.features.file_explorer.transfers import QtTaskSupervisor as QtTaskSupervisor
    from gui.features.file_explorer.transfers import Signal as Signal
    from gui.features.file_explorer.transfers import TransferWorker as TransferWorker
    from gui.features.file_explorer.transfers import _QueuedTransfer as _QueuedTransfer
    from gui.features.file_explorer.transfers import _TransferThread as _TransferThread
    from gui.features.file_explorer.transfers import dataclass as dataclass
    from gui.features.file_explorer.transfers import threading as threading
    from gui.features.file_explorer.transfers import time as time
    from gui.features.file_explorer.transfers import tr as tr

sys.modules[__name__] = _implementation
