"""保留窗口事件订阅及失败清理引用集合的既有导入入口。"""

from services.remote.windowing.events import (
    _RETAINED_SUBSCRIPTIONS as _RETAINED_SUBSCRIPTIONS,
)
from services.remote.windowing.events import (
    WinEventSubscription as WinEventSubscription,
)
