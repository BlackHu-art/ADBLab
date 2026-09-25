"""提供由启动协调器持有的单次后台准备任务。"""

from __future__ import annotations

from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QThread


class StartupTask(QThread):
    """仅运行非 UI 工作；取消协作生效，finished 之后才允许继续构建或退出。

    协调器在开始前接管 Qt 所有权并持有到退出；任务自身不查询控件、不创建日志服务。
    错误交给阶段生成器决定降级或失败；系统 I/O 未返回时不能伪报取消完成。
    """

    def __init__(self, name: str, work: Callable[[Event], None]) -> None:
        super().__init__()
        self.name = name
        self.error: BaseException | None = None
        self._work = work
        self._cancel = Event()
        self._started = False

    def start_work(self) -> None:
        """任务只允许提交一次，避免重复初始化共享快照。"""
        if self._started:
            raise RuntimeError("startup task already started")
        self._started = True
        self.start()

    def cancel(self) -> None:
        """请求协作停止；由调用方等待 finished，禁止强制终止 Python 执行。"""
        self._cancel.set()

    def run(self) -> None:
        try:
            if not self._cancel.is_set():
                self._work(self._cancel)
        except BaseException as error:
            self.error = error
