"""
采集 Android 目标进程的线程数量。
"""

import csv
import os
import re
import threading
import time
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class ThreadNumPackageCollector:
    """按固定间隔采集目标进程的 Threads 指标。"""

    def __init__(self, device, pacakgename, interval=1.0, timeout=24 * 60 * 60, thread_queue=None):
        self.device = device
        self.packagename = pacakgename
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.thread_queue = thread_queue

    def start(self, start_time):
        logger.debug("INFO: ThreadNum PackageCollector start... ")
        self.collect_thread_num_thread = threading.Thread(
            target=self._collect_thread_num_thread, args=(start_time,), daemon=True
        )
        self.collect_thread_num_thread.start()

    def stop(self):
        logger.debug("INFO: ThreadNumPackageCollector stop... ")
        if self.collect_thread_num_thread.is_alive():
            self._stop_event.set()
            self.collect_thread_num_thread.join(timeout=1)
            self.collect_thread_num_thread = None
            # 采集线程结束后通知上报队列当前任务已经完成。
            if self.thread_queue:
                self.thread_queue.task_done()

    def get_process_thread_num(self, process):
        pid = self.device.adb.get_pid_from_pck(self.packagename)
        out = self.device.adb.run_shell_cmd(f"cat /proc/{pid}/status")
        collection_time = time.time()
        logger.debug("collection time in thread_num info is : " + str(collection_time))
        if out:
            threads_match = re.search(r"Threads:\s+(\d+)", out)
            if threads_match:
                thread_num = int(threads_match.group(1))
                return [collection_time, self.packagename, pid, thread_num]
        else:
            return []

    def _collect_thread_num_thread(self, start_time):
        end_time = time.time() + self._timeout
        thread_list_titile = ("datatime", "packagename", "pid", "thread_num")
        thread_num_file = os.path.join(RuntimeData.package_save_path, "thread_num.csv")
        try:
            with open(thread_num_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(thread_list_titile)
                if self.thread_queue:
                    thread_file_dic = {"thread_file": thread_num_file}
                    self.thread_queue.put(thread_file_dic)
        except RuntimeError as e:
            logger.error(e)

        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "-----------into _collect_thread_num_thread loop, thread is : "
                    + str(threading.current_thread().name)
                )

                # 从目标进程状态中获取线程数量。
                thread_pck_info = self.get_process_thread_num(self.packagename)
                logger.debug(thread_pck_info)
                current_time = TimeUtils.getCurrentTime()
                if not thread_pck_info:
                    continue
                else:
                    logger.debug(
                        "current time: "
                        + current_time
                        + ", processname: "
                        + thread_pck_info[1]
                        + ", pid: "
                        + str(thread_pck_info[2])
                        + " thread num: "
                        + str(thread_pck_info[3])
                    )
                if self.thread_queue:
                    self.thread_queue.put(thread_pck_info)
                if not self.thread_queue:  # 未提供上报队列时直接保存本地结果。
                    try:
                        with open(thread_num_file, "a+", encoding="utf-8") as thread_writer:
                            writer_p = csv.writer(thread_writer, lineterminator="\n")
                            thread_pck_info[0] = current_time
                            writer_p.writerow(thread_pck_info)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                delta_inter = self._interval - time_consume
                logger.debug("time_consume  for thread num infos: " + str(time_consume))
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception:
                logger.error("an exception hanpend in thread num thread, reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.thread_queue:
                    self.thread_queue.task_done()


class ThreadNumMonitor:
    """管理目标进程线程数量采集器。"""

    def __init__(
        self, device_id, packagename, interval=1.0, timeout=24 * 60 * 60, thread_queue=None
    ):
        self.device = AndroidDevice(device_id)
        if not packagename:
            packagename = self.device.adb.get_foreground_process()
        self.thread_package_collector = ThreadNumPackageCollector(
            self.device, packagename, interval, timeout, thread_queue
        )

    def start(self, start_time):
        self.start_time = start_time
        self.thread_package_collector.start(start_time)

    def stop(self):
        self.thread_package_collector.stop()

    def save(self):
        pass
