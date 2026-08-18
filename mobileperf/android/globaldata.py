"""保存 MobilePerf 采集会话在线程之间共享的运行时状态。"""

import threading


class RuntimeData:
    """集中保存当前采集会话的共享状态。

    调用方负责在新会话启动前设置包名、输出目录和退出事件，避免复用上次会话的残留值。
    """

    # 保存进程切换前的 PID，供监控器识别采集目标变化。
    old_pid = None
    packages = None
    package_save_path = None
    start_time = None
    exit_event = threading.Event()
    top_dir = None
    config_dic = {}
