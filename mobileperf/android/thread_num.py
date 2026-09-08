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
from mobileperf.android.process_status import ProcessStatusSampler
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class ThreadNumPackageCollector:
    """按固定间隔采集目标进程的 Threads 指标。"""

    def __init__(
        self, device, pacakgename, interval=1.0, timeout=24 * 60 * 60, thread_queue=None,
        *, process_samples=None,
    ):
        self.device = device
        self.packagename = pacakgename
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.thread_queue = thread_queue
        self._process_samples = process_samples or ProcessStatusSampler(
            device.adb, pacakgename, interval,
        )

    def start(self, start_time):
        logger.debug("INFO: ThreadNum PackageCollector start... ")
        self.collect_thread_num_thread = threading.Thread(
            target=self._collect_thread_num_thread, args=(start_time,), daemon=True
        )
        self.collect_thread_num_thread.start()

    def stop(self):
        """取消本采集器的查询与间隔等待，只在确认线程退出后释放其引用。"""
        logger.debug("INFO: ThreadNumPackageCollector stop... ")
        self._stop_event.set()
        worker = getattr(self, "collect_thread_num_thread", None)
        if worker is not None:
            worker.join(timeout=1)
            if not worker.is_alive():
                self.collect_thread_num_thread = None

    def get_process_thread_num(self, process, *, timeout: float = 10):
        sample = self._process_samples.read(timeout=timeout, cancelled=self._stop_event.is_set)
        if sample is None:
            return []
        pid = sample.pid
        out = sample.status
        collection_time = sample.collected_at
        logger.debug("collection time in thread_num info is : " + str(collection_time))
        if out:
            threads_match = re.search(r"Threads:\s+(\d+)", out)
            if threads_match:
                thread_num = int(threads_match.group(1))
                return [collection_time, self.packagename, pid, thread_num]
        else:
            return []

    def _wait_for_interval(self, seconds: float, end_time: float) -> None:
        """等待到采样时刻或总截止；提前唤醒只复查停止，不能提前重复发布同周期数据。"""
        deadline = min(end_time, time.monotonic() + max(0, seconds))
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._stop_event.wait(remaining)

    def _collect_thread_num_thread(self, start_time):
        end_time = time.monotonic() + self._timeout
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

        while not self._stop_event.is_set() and time.monotonic() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "-----------into _collect_thread_num_thread loop, thread is : "
                    + str(threading.current_thread().name)
                )

                # 从目标进程状态中获取线程数量。
                thread_pck_info = self.get_process_thread_num(
                    self.packagename, timeout=min(10, end_time - time.monotonic()),
                )
                if self._stop_event.is_set():
                    break
                logger.debug(thread_pck_info)
                current_time = TimeUtils.getCurrentTime()
                if not thread_pck_info:
                    self._wait_for_interval(self._interval, end_time)
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
                    self._wait_for_interval(delta_inter, end_time)
            except Exception:
                logger.error("an exception hanpend in thread num thread, reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)


class ThreadNumMonitor:
    """管理目标进程线程数量采集器。"""

    def __init__(
        self, device_id, packagename, interval=1.0, timeout=24 * 60 * 60, thread_queue=None,
        *, process_samples=None,
    ):
        self.device = AndroidDevice(device_id)
        if not packagename:
            packagename = self.device.adb.get_foreground_process()
        self.thread_package_collector = ThreadNumPackageCollector(
            self.device, packagename, interval, timeout, thread_queue,
            process_samples=process_samples,
        )

    def start(self, start_time):
        self.start_time = start_time
        self.thread_package_collector.start(start_time)

    def stop(self):
        self.thread_package_collector.stop()

    def save(self):
        pass
