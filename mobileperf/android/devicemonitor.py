"""监控目标应用的前台 Activity 和安装状态。"""

import csv
import os
import random
import threading
import time
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class DeviceMonitor:
    """轮询目标应用的前台 Activity，并提供卸载状态检查能力。"""

    def __init__(
        self,
        device_id,
        packagename,
        interval=1.0,
        main_activity=[],
        activity_list=[],
        event=None,
        activity_queue=None,
    ):
        """初始化监控目标、轮询间隔、允许的 Activity 列表和结果队列。"""
        self.uninstall_flag = event
        self.device = AndroidDevice(device_id)
        self.packagename = packagename
        self.interval = interval
        self.main_activity = main_activity
        self.activity_list = activity_list
        self.stop_event = threading.Event()
        self.activity_queue = activity_queue
        self.current_activity = None

    def start(self, starttime):
        self.activity_monitor_thread = threading.Thread(
            target=self._activity_monitor_thread, daemon=True
        )
        self.activity_monitor_thread.start()
        logger.debug("DeviceMonitor activitymonitor has started...")

    def stop(self):
        if self.activity_monitor_thread.is_alive():
            self.stop_event.set()
            self.activity_monitor_thread.join(timeout=1)
            self.activity_monitor_thread = None
        logger.debug("DeviceMonitor stopped!")

    def _activity_monitor_thread(self):
        activity_title = ("datetime", "current_activity")
        self.activity_file = os.path.join(RuntimeData.package_save_path, "current_activity.csv")
        try:
            with open(self.activity_file, "a+") as af:
                csv.writer(af, lineterminator="\n").writerow(activity_title)
        except Exception:
            logger.error("file not found: " + str(self.activity_file))

        while not self.stop_event.is_set():
            try:
                before = time.time()
                self.current_activity = self.device.adb.get_current_activity()
                collection_time = time.time()
                activity_list = [collection_time, self.current_activity]
                if self.activity_queue:
                    logger.debug("activity monitor thread activity_list: " + str(activity_list))
                    self.activity_queue.put(activity_list)
                if self.current_activity:
                    logger.debug("current activity: " + self.current_activity)
                    if self.main_activity and self.activity_list:
                        if self.current_activity not in self.activity_list:
                            start_activity = (
                                self.packagename
                                + "/"
                                + self.main_activity[random.randint(0, len(self.main_activity) - 1)]
                            )
                            logger.debug("start_activity:" + start_activity)
                            self.device.adb.start_activity(start_activity)
                    activity_tuple = (TimeUtils.getCurrentTime(), self.current_activity)
                    # 前台 Activity 同时写入 CSV，便于与其他性能指标按时间对齐。
                    try:
                        with open(self.activity_file, "a+", encoding="utf-8") as writer:
                            writer_p = csv.writer(writer, lineterminator="\n")
                            writer_p.writerow(activity_tuple)
                    except RuntimeError as e:
                        logger.error(e)
                time_consume = time.time() - before
                delta_inter = self.interval - time_consume
                logger.debug("get app activity time consumed: " + str(time_consume))
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception:
                s = traceback.format_exc()
                logger.debug(s)  # 堆栈仅进入开发诊断通道。

if __name__ == "__main__":
    monitor = DeviceMonitor("NVGILZSO99999999", "com.taobao.taobao", 2)
    monitor.start(time.time())
    time.sleep(60)
    monitor.stop()
