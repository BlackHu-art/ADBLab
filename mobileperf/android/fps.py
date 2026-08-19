"""
采集 SurfaceFlinger 或 gfxinfo 帧时间并计算 FPS 与卡顿次数。
"""

import copy
import csv
import datetime
import os
import queue
import re
import threading
import time
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.basemonitor import Monitor
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class SurfaceStatsCollector:
    """从 SurfaceFlinger 输出中采集当前 Surface 的帧统计数据。"""

    def __init__(
        self, device, frequency, package_name, fps_queue, jank_threshold, use_legacy=False
    ):
        self.device = device
        self.frequency = frequency
        self.package_name = package_name
        self.jank_threshold = jank_threshold / 1000.0  # 内部时间戳以秒为单位。
        self.use_legacy_method = use_legacy
        self.surface_before = 0
        self.last_timestamp = 0
        self.data_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.focus_window = None
        # 该队列用于向上层采集线程报告结果。
        self.fps_queue = fps_queue

    def start(self, start_time):
        """启动 Surface 统计数据采集和计算线程。"""
        if not self.use_legacy_method and self._clear_surfaceflinger_latency_data():
            try:
                self.focus_window = self.get_focus_activity()
                # Shell 会解释窗口名中的美元符号，因此发送命令前需要转义。
                if self.focus_window.find("$") != -1:
                    self.focus_window = self.focus_window.replace("$", r"\$")
            except Exception:
                logger.warn("无法动态获取当前Activity名称，使用page_flip统计全屏帧率！")
                self.use_legacy_method = True
                self.surface_before = self._get_surface_stats_legacy()
        else:
            logger.debug("dumpsys SurfaceFlinger --latency-clear is none")
            self.use_legacy_method = True
            self.surface_before = self._get_surface_stats_legacy()
        self.collector_thread = threading.Thread(target=self._collector_thread, daemon=True)
        self.collector_thread.start()
        self.calculator_thread = threading.Thread(
            target=self._calculator_thread, args=(start_time,), daemon=True
        )
        self.calculator_thread.start()

    def stop(self):
        """停止 Surface 统计数据采集线程。"""
        if self.collector_thread:
            self.stop_event.set()
            self.collector_thread.join()
            self.collector_thread = None
            if self.fps_queue:
                self.fps_queue.task_done()

    def get_focus_activity(self):
        """通过 dumpsys window windows 获取当前焦点 Activity 的窗口名。"""
        return self.device.adb.get_focus_activity()

    def _calculate_results(self, refresh_period, timestamps):
        """根据帧时间戳计算 FPS 和卡顿次数。

        部分设备返回的第一列和第三列时间戳完全相同，因此使用第二列计算。
        """

        frame_count = len(timestamps)
        if frame_count == 0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        return fps, jank

    def _calculate_results_new(self, refresh_period, timestamps):
        """根据帧数量选择对应算法计算 FPS 和卡顿次数。"""

        frame_count = len(timestamps)
        if frame_count == 0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        elif frame_count == 2 or frame_count == 3 or frame_count == 4:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_jankey_new(timestamps)
            else:
                fps = 1
                jank = 0
        return fps, jank

    def _calculate_jankey_new(self, timestamps):
        """同时满足以下条件时计为一次卡顿。

        1. Display FrameTime 大于前三帧平均耗时的两倍。
        2. Display FrameTime 大于两帧电影帧耗时，约 83.33 毫秒。
        """

        twofilmstamp = 83.3 / 1000.0
        tempstamp = 0
        # 统计丢帧引起的卡顿。
        jank = 0
        for index, timestamp in enumerate(timestamps):
            # 前四帧缺少完整历史窗口，按固定阈值判断卡顿。
            if (index == 0) or (index == 1) or (index == 2) or (index == 3):
                if tempstamp == 0:
                    tempstamp = timestamp[1]
                    continue
                # 当前绘制帧耗时。
                costtime = timestamp[1] - tempstamp
                # 超过配置阈值时记为一次可感知卡顿。
                if costtime > self.jank_threshold:
                    jank = jank + 1
                tempstamp = timestamp[1]
            elif index > 3:
                currentstamp = timestamps[index][1]
                lastonestamp = timestamps[index - 1][1]
                lasttwostamp = timestamps[index - 2][1]
                lastthreestamp = timestamps[index - 3][1]
                lastfourstamp = timestamps[index - 4][1]
                tempframetime = (
                    (
                        (lastthreestamp - lastfourstamp)
                        + (lasttwostamp - lastthreestamp)
                        + (lastonestamp - lasttwostamp)
                    )
                    / 3
                    * 2
                )
                currentframetime = currentstamp - lastonestamp
                if (currentframetime > tempframetime) and (currentframetime > twofilmstamp):
                    jank = jank + 1
        return jank

    def _calculate_janky(self, timestamps):
        tempstamp = 0
        # 统计丢帧引起的卡顿。
        jank = 0
        for timestamp in timestamps:
            if tempstamp == 0:
                tempstamp = timestamp[1]
                continue
            # 当前绘制帧耗时。
            costtime = timestamp[1] - tempstamp
            # 超过配置阈值时记为一次可感知卡顿。
            if costtime > self.jank_threshold:
                jank = jank + 1
            tempstamp = timestamp[1]
        return jank

    def _calculator_thread(self, start_time):
        """消费 SurfaceFlinger 数据并将 FPS 结果写入文件或上报队列。"""
        fps_file = os.path.join(RuntimeData.package_save_path, "fps.csv")
        if self.use_legacy_method:
            fps_title = ["datetime", "fps"]
        else:
            fps_title = ["datetime", "activity window", "fps", "jank"]
        try:
            with open(fps_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(fps_title)
                if self.fps_queue:
                    fps_file_dic = {"fps_file": fps_file}
                    self.fps_queue.put(fps_file_dic)
        except RuntimeError as e:
            logger.exception(e)

        while True:
            try:
                data = self.data_queue.get()
                if isinstance(data, str) and data == "Stop":
                    break
                before = time.time()
                if self.use_legacy_method:
                    td = data["timestamp"] - self.surface_before["timestamp"]
                    seconds = td.seconds + td.microseconds / 1e6
                    frame_count = data["page_flip_count"] - self.surface_before["page_flip_count"]
                    fps = int(round(frame_count / seconds))
                    if fps > 60:
                        fps = 60
                    self.surface_before = data
                    logger.debug(f"FPS:{fps:2}")
                    tmp_list = [TimeUtils.getCurrentTimeUnderline(), fps]
                    try:
                        with open(fps_file, "a+", encoding="utf-8") as f:
                            csv.writer(f, lineterminator="\n").writerow(tmp_list)
                    except RuntimeError as e:
                        logger.exception(e)
                else:
                    refresh_period = data[0]
                    timestamps = data[1]
                    collect_time = data[2]
                    fps, jank = self._calculate_results_new(refresh_period, timestamps)
                    logger.debug(f"FPS:{fps:2} Jank:{jank}")
                    fps_list = [collect_time, self.focus_window, fps, jank]
                    if self.fps_queue:
                        self.fps_queue.put(fps_list)
                    if not self.fps_queue:  # 未提供上报队列时直接保存本地结果。
                        try:
                            with open(fps_file, "a+", encoding="utf-8") as f:
                                tmp_list = copy.deepcopy(fps_list)
                                tmp_list[0] = TimeUtils.formatTimeStamp(tmp_list[0])
                                csv.writer(f, lineterminator="\n").writerow(tmp_list)
                        except RuntimeError as e:
                            logger.exception(e)
                time_consume = time.time() - before
                delta_inter = self.frequency - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception:
                logger.error("an exception hanpend in fps _calculator_thread ,reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fps_queue:
                    self.fps_queue.task_done()

    def _collector_thread(self):
        """循环采集帧数据。

        兼容模式通过 ``service call SurfaceFlinger 1013`` 获取帧数，可能需要 root；
        常规模式使用 ``dumpsys SurfaceFlinger --latency``。Android 8.0 及以上版本
        改用 ``dumpsys gfxinfo <package> framestats`` 补充帧时间数据。
        """
        is_first = True
        while not self.stop_event.is_set():
            try:
                before = time.time()
                if self.use_legacy_method:
                    surface_state = self._get_surface_stats_legacy()
                    if surface_state:
                        self.data_queue.put(surface_state)
                else:
                    timestamps = []
                    refresh_period, new_timestamps = self._get_surfaceflinger_frame_data()
                    if refresh_period is None or new_timestamps is None:
                        # Activity 切换且旧窗口消失时，刷新焦点窗口后重新采集。
                        self.focus_window = self.get_focus_activity()
                        logger.debug("refresh_period is None or timestamps is None")
                        continue
                    # 只保留晚于上次采样点的新帧。
                    timestamps += [
                        timestamp
                        for timestamp in new_timestamps
                        if timestamp[1] > self.last_timestamp
                    ]
                    if len(timestamps):
                        first_timestamp = [[0, self.last_timestamp, 0]]
                        if not is_first:
                            timestamps = first_timestamp + timestamps
                        self.last_timestamp = timestamps[-1][1]
                        is_first = False
                    else:
                        # 无新帧可能是窗口切换后仍返回旧数据，也可能是界面没有刷新。
                        is_first = True
                        cur_focus_window = self.get_focus_activity()
                        if self.focus_window != cur_focus_window:
                            self.focus_window = cur_focus_window
                            continue
                    logger.debug(timestamps)
                    self.data_queue.put((refresh_period, timestamps, time.time()))
                    time_consume = time.time() - before
                    delta_inter = self.frequency - time_consume
                    if delta_inter > 0:
                        time.sleep(delta_inter)
            except Exception:
                logger.error("an exception hanpend in fps _collector_thread , reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fps_queue:
                    self.fps_queue.task_done()
        self.data_queue.put("Stop")

    def _clear_surfaceflinger_latency_data(self):
        """清空 SurfaceFlinger 延迟数据，并返回设备是否支持该命令。

        支持时命令不返回内容；不支持时通常返回与 dumpsys SurfaceFlinger 相似的文本。
        """
        if self.focus_window is None:
            results = self.device.adb.run_shell_cmd("dumpsys SurfaceFlinger --latency-clear")
        else:
            results = self.device.adb.run_shell_cmd(
                f"dumpsys SurfaceFlinger --latency-clear {self.focus_window}"
            )
        return not len(results)

    def _get_surfaceflinger_frame_data(self):
        """返回屏幕刷新周期和已完成帧的时间戳列表。

        返回结构为 ``(refresh_period, [[t1, t2, t3], ...])``；应用提前退出或没有
        可用数据时返回 ``(None, None)``。
        """
        # 命令格式：adb -s <DEVICE_SERIAL> shell dumpsys SurfaceFlinger --latency <WINDOW_NAME>
        # 第一行是刷新周期，后续每行是同一帧的三个纳秒时间戳，示例：
        # 16954612
        # 7657467895508     7657482691352     7657493499756
        # 7657484466553     7657499645964     7657511077881
        # 7657500793457     7657516600576     7657527404785
        # 三列依次表示应用开始绘制、SurfaceFlinger 提交前的垂直同步，以及提交完成时间。
        # 第一列与第三列之差是帧延迟；跨越刷新周期的数量可按以下公式计算：
        # 计算公式：ceil((C - A) / refresh-period)
        # 该值持续增大时表示连续发生卡顿，即使平均 FPS 较高也可能不流畅。
        refresh_period = None
        timestamps = []
        nanoseconds_per_second = 1e9
        pending_fence_timestamp = (1 << 63) - 1
        if self.device.adb.get_sdk_version() >= 26:
            results = self.device.adb.run_shell_cmd(
                f"dumpsys SurfaceFlinger --latency {self.focus_window}"
            )
            results = results.replace("\r\n", "\n").splitlines()
            refresh_period = int(results[0]) / nanoseconds_per_second
            results = self.device.adb.run_shell_cmd(
                f"dumpsys gfxinfo {self.package_name} framestats"
            )
            # 将 gfxinfo framestats 结果转换为统一的三时间戳结构。
            results = results.replace("\r\n", "\n").splitlines()
            if not len(results):
                return (None, None)
            isHaveFoundWindow = False
            PROFILEDATA_line = 0
            for line in results:
                if not isHaveFoundWindow:
                    if "Window" in line and self.focus_window in line:
                        isHaveFoundWindow = True
                if not isHaveFoundWindow:
                    continue
                if "PROFILEDATA" in line:
                    PROFILEDATA_line += 1
                fields = []
                fields = line.split(",")
                if fields and "0" == fields[0]:
                    # 提取 INTENDED_VSYNC、VSYNC 和 FRAME_COMPLETED 计算 FPS 与卡顿。
                    timestamp = [int(fields[1]), int(fields[2]), int(fields[13])]
                    if timestamp[1] == pending_fence_timestamp:
                        continue
                    timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                    timestamps.append(timestamp)
                # 到达下一个窗口的数据段时结束当前窗口解析。
                if 2 == PROFILEDATA_line:
                    break
        else:
            results = self.device.adb.run_shell_cmd(
                f"dumpsys SurfaceFlinger --latency {self.focus_window}"
            )
            results = results.replace("\r\n", "\n").splitlines()
            logger.debug("dumpsys SurfaceFlinger --latency result:")
            logger.debug(results)
            if not len(results):
                return (None, None)
            if not results[0].isdigit():
                return (None, None)
            try:
                refresh_period = int(results[0]) / nanoseconds_per_second
            except Exception as e:
                logger.exception(e)
                return (None, None)
            # 未完成帧的 fence 会被 SurfaceFlinger 标记为 INT64_MAX，此处只保留已完成帧。

            for line in results[1:]:
                fields = line.split()
                if len(fields) != 3:
                    continue
                timestamp = [int(fields[0]), int(fields[1]), int(fields[2])]
                if timestamp[1] == pending_fence_timestamp:
                    continue
                timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                timestamps.append(timestamp)
        return (refresh_period, timestamps)

    def _get_surface_stats_legacy(self):
        """返回 JellyBean 之前兼容路径的 Surface 索引和时间戳。

        该路径通过一段时间内 SurfaceFlinger 返回的索引差计算 FPS。
        """
        cur_surface = None
        timestamp = datetime.datetime.now()
        # 该命令可能需要 root 权限。
        ret = self.device.adb.run_shell_cmd("service call SurfaceFlinger 1013")
        if not ret:
            return None
        match = re.search(r"^Result: Parcel\((\w+)", ret)
        if match:
            cur_surface = int(match.group(1), 16)
            return {"page_flip_count": cur_surface, "timestamp": timestamp}
        return None


class FPSMonitor(Monitor):
    """管理 FPS 采集器及其结果目录。"""

    def __init__(
        self,
        device_id,
        package_name=None,
        frequency=1.0,
        timeout=24 * 60 * 60,
        fps_queue=None,
        jank_threshold=166,
        use_legacy=False,
    ):
        """初始化 FPS 监控器。

        :param str device_id: 设备标识。
        :param float frequency: 帧率统计间隔，默认一秒。
        :param int jank_threshold: 卡顿阈值，单位为毫秒。
        :param bool use_legacy: 为 True 时使用 page_flip 统计全屏刷新帧率；否则统计
            当前焦点 Activity 的刷新帧率。
        """
        self.use_legacy = use_legacy
        self.frequency = frequency  # 采样频率
        self.jank_threshold = jank_threshold
        self.device = AndroidDevice(device_id)
        self.timeout = timeout
        if not package_name:
            package_name = self.device.adb.get_foreground_process()
        self.package = package_name
        self.fpscollector = SurfaceStatsCollector(
            self.device,
            self.frequency,
            package_name,
            fps_queue,
            self.jank_threshold,
            self.use_legacy,
        )

    def start(self, start_time):
        """启动 FPS 监控器。"""
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(
                os.path.abspath(os.path.join(os.getcwd(), "../..")),
                "results",
                self.package,
                start_time,
            )
            if not os.path.exists(RuntimeData.package_save_path):
                os.makedirs(RuntimeData.package_save_path)
        self.start_time = start_time
        self.fpscollector.start(start_time)
        logger.debug("FPS monitor has start!")

    def stop(self):
        """停止 FPS 监控器。"""
        self.fpscollector.stop()
        logger.debug("FPS monitor has stop!")

    def save(self):
        pass

    def parse(self, file_path):
        """解析指定的 FPS 数据文件。"""
        pass

    def get_fps_collector(self):
        """返回保存时间、FPS 和卡顿数据的采集器。"""
        return self.fpscollector
