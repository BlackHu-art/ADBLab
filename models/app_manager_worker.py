"""保留旧模型模块路径，与 Qt worker 实现共享身份和替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.workers import app_manager as _implementation

if TYPE_CHECKING:
    from gui.workers.app_manager import (
        CLEAR_DATA_PERMISSION_MESSAGE as CLEAR_DATA_PERMISSION_MESSAGE,
    )
    from gui.workers.app_manager import AppManagerWorker as AppManagerWorker
    from gui.workers.app_manager import AppMetadata as AppMetadata
    from gui.workers.app_manager import CommandRunner as CommandRunner
    from gui.workers.app_manager import Literal as Literal
    from gui.workers.app_manager import PackageDetail as PackageDetail
    from gui.workers.app_manager import QCoreApplication as QCoreApplication
    from gui.workers.app_manager import QThread as QThread
    from gui.workers.app_manager import Signal as Signal
    from gui.workers.app_manager import actions as actions
    from gui.workers.app_manager import archives as archives
    from gui.workers.app_manager import cast as cast
    from gui.workers.app_manager import load_app_icons as load_app_icons
    from gui.workers.app_manager import load_app_metadata as load_app_metadata
    from gui.workers.app_manager import monotonic as monotonic
    from gui.workers.app_manager import parse_app_details as parse_app_details
    from gui.workers.app_manager import parse_batch_detail as parse_batch_detail
    from gui.workers.app_manager import (
        parse_package_permissions as parse_package_permissions,
    )
    from gui.workers.app_manager import queries as queries
    from gui.workers.app_manager import query_timeout as query_timeout
    from gui.workers.app_manager import threading as threading

sys.modules[__name__] = _implementation
