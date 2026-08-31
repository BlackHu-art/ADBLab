"""GUI 页面集合（P1 信息架构）：设备 / 任务中心 / 日志。

本包导出页面宿主类与一个按页面键构造宿主的工厂 ``create_page``；页面键与
``NavBar`` 的业务键一致（``devices`` / ``tasks`` / ``logs``，``settings``
走导航回调打开既有设置对话框，不在此处建页）。
"""

from __future__ import annotations

from .devices_page import DevicesPage
from .log_page import LogPage
from .tasks_page import TaskCenterPage

# 本包实际持有页面宿主的业务键集合（settings 由导航回调承接）。
PAGE_KEYS: tuple[str, ...] = ("devices", "tasks", "logs")


def create_page(key: str, *, panel=None, log_panel=None, parent=None):
    """按页面键创建对应页面宿主；未知键抛 ``KeyError``。

    参数按页面类型按需使用：``devices`` 需要 ``panel``，``logs`` 可传入已有
    ``log_panel``（缺省时新建），``tasks`` 当前为占位页。
    """

    if key == "devices":
        return DevicesPage(panel, parent=parent)
    if key == "tasks":
        return TaskCenterPage(panel=panel, parent=parent)
    if key == "logs":
        return LogPage(log_panel, parent=parent)
    raise KeyError(f"未知页面键：{key}")


__all__ = [
    "DevicesPage",
    "LogPage",
    "PAGE_KEYS",
    "TaskCenterPage",
    "create_page",
]
