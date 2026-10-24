"""保留旧模型模块路径，与 Qt worker 实现共享身份和替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.workers import file_explorer as _implementation

if TYPE_CHECKING:
    from gui.workers.file_explorer import ADBWorker as ADBWorker
    from gui.workers.file_explorer import CommandRunner as CommandRunner
    from gui.workers.file_explorer import DirectoryListWorker as DirectoryListWorker
    from gui.workers.file_explorer import LocalTextSaveWorker as LocalTextSaveWorker
    from gui.workers.file_explorer import LogService as LogService
    from gui.workers.file_explorer import ProcessRunner as ProcessRunner
    from gui.workers.file_explorer import QThread as QThread
    from gui.workers.file_explorer import SafeFileDownload as SafeFileDownload
    from gui.workers.file_explorer import Signal as Signal
    from gui.workers.file_explorer import TextReadWorker as TextReadWorker
    from gui.workers.file_explorer import TextSaveWorker as TextSaveWorker
    from gui.workers.file_explorer import TransferWorker as TransferWorker
    from gui.workers.file_explorer import explorer_service as explorer_service
    from gui.workers.file_explorer import file_operations as file_operations
    from gui.workers.file_explorer import os as os
    from gui.workers.file_explorer import subprocess as subprocess
    from gui.workers.file_explorer import threading as threading
    from gui.workers.file_explorer import time as time
    from gui.workers.file_explorer import uuid as uuid

sys.modules[__name__] = _implementation
