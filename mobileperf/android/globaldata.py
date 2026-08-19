"""保存 MobilePerf 采集会话在线程之间共享的运行时状态。

每运行一份：``RuntimeData.begin_run()`` 在 ``StartUp.__init__`` 创建运行级实例，
``RuntimeData.end_run()`` 在 ``stop()`` 收尾后清空，避免跨会话残留（ADR-0004）。
类属性读写经元类代理转发到当前运行实例，因此现有 ``RuntimeData.xxx`` 调用点
无需改动；无活动运行（例如单测直接设置字段）时回退到类属性。
"""

import threading

_RUNTIME_FIELDS = frozenset(
    {
        "old_pid",
        "packages",
        "package_save_path",
        "start_time",
        "exit_event",
        "top_dir",
        "config_dic",
    }
)


class _RuntimeDataMeta(type):
    """把运行时字段的读写代理到当前运行实例，保持既有调用点兼容。"""

    def __getattribute__(cls, name):
        if name in _RUNTIME_FIELDS:
            instance = type.__getattribute__(cls, "_instance")
            if instance is not None:
                return getattr(instance, name)
        return super().__getattribute__(name)

    def __setattr__(cls, name, value):
        if name in _RUNTIME_FIELDS:
            instance = type.__getattribute__(cls, "_instance")
            if instance is not None:
                setattr(instance, name, value)
                return
        super().__setattr__(name, value)


class RuntimeData(metaclass=_RuntimeDataMeta):
    """集中保存当前采集会话的共享状态（每运行一个实例）。"""

    _instance = None
    _instance_lock = threading.Lock()

    # 无活动运行时的类级回退值。
    old_pid = None
    packages = None
    package_save_path = None
    start_time = None
    exit_event = threading.Event()
    top_dir = None
    config_dic = {}

    def __init__(self):
        self.old_pid = None
        self.packages = None
        self.package_save_path = None
        self.start_time = None
        self.exit_event = threading.Event()
        self.top_dir = None
        self.config_dic = {}

    @classmethod
    def begin_run(cls):
        """开始一次采集运行：创建全新的运行级实例并切换代理目标。"""
        with cls._instance_lock:
            cls._instance = cls()

    @classmethod
    def end_run(cls):
        """结束采集运行并丢弃运行级状态，防止跨会话残留。"""
        with cls._instance_lock:
            cls._instance = None
