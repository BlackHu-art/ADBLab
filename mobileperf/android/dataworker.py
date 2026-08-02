# -*- coding: utf-8 -*-
"""消费各性能采集队列，并把统一时间轴的数据写入 CSV。"""
import csv
import os
import threading
import time
import sys
import copy
import json

import queue
import traceback

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))
from mobileperf.common.utils import TimeUtils, FileUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData


class DataWorker(object):
    """汇总各采集器数据，并负责性能数据的内存聚合与文件落盘。"""

    def __init__(self, queuedic):
        self.queuedic = queuedic
        self.fps_queue = self.get_fps_queue()
        self.cpu_queue = self.get_cpu_queue()
        self.mem_queue = self.get_mem_queue()
        self.power_queue = self.get_power_queue()
        self.traffic_queue = self.get_traffic_queue()
        self.activity_queue = self.get_activity_queue()
        self.fd_queue = self.get_fd_queue()
        self.thread_queue = self.get_thread_queue()
        self.fps_filename = ''
        self.power_filename = ''
        self.traffic_filename = ''
        self.cpu_filename = ''
        self.mem_filename = ''
        self.activity_file = ''
        self.fd_file = ''
        self.thread_file = ''
        self._stop_event = threading.Event()
        self.timestamp = time.time()
        self.interval = 2
        self.first_time = True
        self.perf_data = {"task_id": "", "activity": [], 'launch_time': [], 'cpu': [], "mem": [],
                          'traffic': [], "fluency": [], 'power': [], "fd": [], "thread": []}

    def start(self, interval, start_time):
        self.interval = interval
        self.starttime = start_time
        self.dataworker_thread = threading.Thread(target=self._handle_data_thread)
        self.dataworker_thread.start()
        logger.debug("DataWorker started...")

    def stop(self):
        if self.dataworker_thread.is_alive():
            self._stop_event.set()
            self.dataworker_thread.join(timeout=1)
            self.dataworker_thread = None
        logger.debug("DataWorker stopped ")

    def get_cpu_queue(self):
        return self._get_queue('cpu_queue')

    def get_mem_queue(self):
        return self._get_queue('mem_queue')

    def get_power_queue(self):
        return self._get_queue('power_queue')

    def get_traffic_queue(self):
        return self._get_queue('traffic_queue')

    def get_fps_queue(self):
        return self._get_queue('fps_queue')

    def get_fd_queue(self):
        return self._get_queue('fd_queue')

    def get_thread_queue(self):
        return self._get_queue('thread_queue')

    def get_activity_queue(self):
        return self._get_queue('activity_queue')

    def _get_queue(self, key):
        if self.queuedic:
            return self.queuedic[key]
        else:
            raise RuntimeError('no %s queue exist,please creat' % key)

    def _handle_data_thread(self):
        """在独立线程中消费所有采集器队列，并按同一时间戳聚合数据。"""
        time.sleep(1)
        while not self._stop_event.is_set():
            try:
                # 电量队列作为每轮聚合的同步起点，其他队列使用超时避免永久等待。
                # 处理电量数据。
                self.perf_data = {"task_id": "", "activity": [], 'launch_time': [], 'cpu': [], "mem": [],
                                  'traffic': [], "fluency": [], 'power': [], "fd": [], "thread": []}
                try:
                    power_data = self.power_queue.get()
                    if isinstance(power_data, list):
                        self.timestamp = power_data[0]
                    logger.debug("dataworker logger timestamp: " + str(self.timestamp))
                    logger.info("now collecting data")
                    self._get_power_save(power_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker power queue Empty")

                # 处理流量数据。
                try:
                    traffic_data = self.traffic_queue.get(timeout=2)
                    self._get_traffic_save(traffic_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker traffic queue Empty")

                # 处理帧率数据。
                try:
                    fps_data = self.fps_queue.get(timeout=2)
                    self._get_fps_save(fps_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker fps queue Empty")

                # 处理 CPU 数据。
                try:
                    cpu_data = self.cpu_queue.get(timeout=2)
                    self._get_cpu_save(cpu_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker cpu queue Empty")

                # 处理内存数据。
                try:
                    mem_data = self.mem_queue.get(timeout=2)
                    self._get_mem_save(mem_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker mem queue Empty")

                try:
                    fd_data = self.fd_queue.get(timeout=2)
                    self._get_fd_save(fd_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker fd_data queue Empty")

                try:
                    thread_data = self.thread_queue.get(timeout=2)
                    self._get_thread_save(thread_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker thread queue Empty")

                try:
                    activity_data = self.activity_queue.get(timeout=2)
                    self._get_activity_save(activity_data, self.timestamp)
                except queue.Empty:
                    logger.debug("dataworker activity queue Empty")

            except Exception as e:
                logger.error(e)
                s = traceback.format_exc()
                logger.debug(s)  # 堆栈仅进入开发诊断通道。
            logger.debug("perf_str put in queue:" + json.dumps(self.perf_data))
            time.sleep(self.interval)

    def _get_fps_save(self, fps_data, timestamp):
        if isinstance(fps_data, dict):
            self.fps_filename = fps_data['fps_file']
            logger.debug("fps_filename: " + str(self.fps_filename))
        else:
            try:
                # 列表字段依次为采集时间、Activity、FPS 和卡顿数。
                fps_data[0] = timestamp
                dic = {"time": fps_data[0] * 1000, "activity": fps_data[1], "fps": fps_data[2], "jank": fps_data[3]}
                self.perf_data['fluency'].append(dic)
                with open(self.fps_filename, 'a+') as writer:
                    logger.debug("dataworker write fps data in  dataworker銆俧ps timestamp: " + str(fps_data[0]))
                    fps_data[0] = TimeUtils.formatTimeStamp(fps_data[0])
                    tmp_dic = copy.deepcopy(dic)
                    tmp_dic["time"] = fps_data[0]
                    logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(fps_data)

            except Exception as e:
                s = traceback.format_exc()
                logger.error(s)  # 记录落盘失败时的完整堆栈。
                logger.error("fps save error")

    def _get_cpu_save(self, cpu_data, timestamp):
        if isinstance(cpu_data, dict):
            self.cpu_filename = cpu_data['cpu_file']
            logger.debug("cpu_filename: " + str(self.cpu_filename))
        else:
            try:
                # CPU 列表包含总占用、系统占用、进程标识及进程占用等固定字段。
                cpu_data[0] = timestamp
                dic = {"time": cpu_data[0] * 1000, "total": cpu_data[1], "cpu_jiffies": cpu_data[4],
                       "user": cpu_data[2], "sys": cpu_data[3],
                       "pck_jiffies": cpu_data[8],
                       "pid_cpu": cpu_data[9]
                       }
                self.perf_data['cpu'].append(dic)
                with open(self.cpu_filename, 'a+') as writer:
                    logger.debug("write cpu data in  dataworker mem timestamp: " + str(cpu_data[0]))
                    cpu_data[0] = TimeUtils.formatTimeStamp(cpu_data[0])
                    tmp_dic = copy.deepcopy(dic)
                    tmp_dic["time"] = cpu_data[0]
                    logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(cpu_data)

            except Exception as e:
                logger.error('cpu save error')
                s = traceback.format_exc()
                logger.error(s)

    def _get_mem_save(self, mem_data, timestamp):
        if isinstance(mem_data, dict):
            self.mem_filename = mem_data['mem_file']
            logger.debug("mem_filename: " + str(self.mem_filename))
        else:
            try:
                # 内存列表包含总量、空闲量、进程标识、PSS 和堆内存等固定字段。
                mem_data[0] = timestamp
                dic = {"time": mem_data[0] * 1000, "total": mem_data[1],
                       "free": mem_data[2],
                       "pss": mem_data[5],
                       "heap": mem_data[6]
                       }
                self.perf_data['mem'].append(dic)

                with open(self.mem_filename, 'a+') as writer:
                    logger.debug("write mem data in  dataworker銆傘€傘€傘€傘€傘€?mem timestamp: " + str(mem_data[0]))
                    if isinstance(mem_data[0], float):
                        mem_data[0] = TimeUtils.formatTimeStamp(mem_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = mem_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(mem_data)

            except Exception as e:
                logger.error('mem save error')
                s = traceback.format_exc()
                logger.debug(s)

    def _get_fd_save(self, fd_data, timestamp):
        if isinstance(fd_data, dict):
            self.fd_file = fd_data['fd_file']
            logger.debug("fd_file: " + str(self.fd_file))
        else:
            try:
                # 文件描述符列表依次包含采集时间、包名、PID 和数量。
                fd_data[0] = timestamp
                dic = {"time": fd_data[0] * 1000, "package": fd_data[1],
                       "pid": fd_data[2],
                       "fd": fd_data[3]
                       }
                self.perf_data['fd'].append(dic)

                with open(self.fd_file, 'a+') as writer:
                    logger.debug("write fd data in  dataworker銆傘€傘€傘€傘€傘€?fd timestamp: " + str(fd_data[0]))
                    if isinstance(fd_data[0], float):
                        fd_data[0] = TimeUtils.formatTimeStamp(fd_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = fd_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(fd_data)

            except Exception as e:
                logger.error('fd save error')
                s = traceback.format_exc()
                logger.debug(s)

    def _get_thread_save(self, thread_data, timestamp):
        if isinstance(thread_data, dict):
            self.thread_file = thread_data['thread_file']
            logger.debug("thread_file: " + str(self.thread_file))
        else:
            try:
                # 线程列表依次包含采集时间、包名、PID 和线程数。
                thread_data[0] = timestamp
                dic = {"time": thread_data[0] * 1000, "package": thread_data[1],
                       "pid": thread_data[2],
                       "thread": thread_data[3]
                       }
                self.perf_data['thread'].append(dic)

                with open(self.thread_file, 'a+') as writer:
                    logger.debug("write thread data in  dataworker銆傘€傘€傘€傘€傘€?thread timestamp: " + str(thread_data[0]))
                    if isinstance(thread_data[0], float):
                        thread_data[0] = TimeUtils.formatTimeStamp(thread_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = thread_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(thread_data)

            except Exception as e:
                logger.error('thread save error')
                s = traceback.format_exc()
                logger.debug(s)

    def _get_power_save(self, power_data, timestamp):
        if isinstance(power_data, dict):
            self.power_filename = power_data['power_file']
            logger.debug("dataworker power_filename: " + str(self.power_filename))
        else:
            try:
                # 电量列表依次包含采集时间、电量、电压、温度和电流。
                power_data[0] = timestamp
                dic = {"time": power_data[0] * 1000, "level": power_data[1],
                       "vol": power_data[2], "temp": power_data[3], "current": power_data[4]}
                self.perf_data['power'].append(dic)

                with open(self.power_filename, 'a+') as writer:
                    logger.debug("write power data in dataworker銆傘€傘€傘€傘€傘€?timestamp:" + str(power_data[0]))
                    if isinstance(power_data[0], float):
                        power_data[0] = TimeUtils.formatTimeStamp(power_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = power_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(power_data)
            except Exception as e:
                logger.error('power save error')
                s = traceback.format_exc()
                logger.debug(s)

    def _get_traffic_save(self, traffic_data, timestamp):
        if isinstance(traffic_data, dict):
            self.traffic_filename = traffic_data['traffic_file']
            logger.debug("dataworker traffic_filename: " + str(self.traffic_filename))
        else:
            try:
                # 流量列表包含 UID 总量、收发包、前后台和回环流量等固定字段。
                traffic_data[0] = timestamp
                dic = {"time": traffic_data[0] * 1000,
                       "total": traffic_data[3],
                       "total_packets": traffic_data[4],
                       "rx": traffic_data[5],
                       "rx_packets": traffic_data[6],
                       "tx": traffic_data[7],
                       "tx_packets": traffic_data[8],
                       "fg": traffic_data[9],
                       "bg": traffic_data[10],
                       "lo": traffic_data[11]}
                self.perf_data['traffic'].append(dic)

                with open(self.traffic_filename, 'a+') as writer:
                    logger.debug("write traffic data in dataworker traffic data timestamp: " + str(traffic_data[0]))
                    if isinstance(traffic_data[0], float):
                        traffic_data[0] = TimeUtils.formatTimeStamp(traffic_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = traffic_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(traffic_data)
            except Exception as e:
                logger.error("traffic save error")
                s = traceback.format_exc()
                logger.debug(s)

    def _get_activity_save(self, activity_data, timestamp):
        if self.first_time:
            activity_title = ("datetime", "current_activity")
            self.first_time = False
            self.activity_file = os.path.join(RuntimeData.package_save_path, 'current_activity.csv')
            try:
                with open(self.activity_file, 'a+') as af:
                    csv.writer(af, lineterminator='\n').writerow(activity_title)
            except Exception as e:
                logger.error("file not found: " + str(self.activity_file))
        else:
            try:
                activity_data[0] = timestamp
                dic = {"time": activity_data[0] * 1000, "name": activity_data[1]}
                self.perf_data['activity'].append(dic)

                with open(self.activity_file, 'a+') as writer:
                    if isinstance(activity_data[0], float):
                        activity_data[0] = TimeUtils.formatTimeStamp(activity_data[0])
                        tmp_dic = copy.deepcopy(dic)
                        tmp_dic["time"] = activity_data[0]
                        logger.debug(tmp_dic)
                    writer_p = csv.writer(writer, lineterminator='\n')
                    writer_p.writerow(activity_data)

            except Exception as e:
                logger.error("activity save error ")
                s = traceback.format_exc()
                logger.debug(s)
