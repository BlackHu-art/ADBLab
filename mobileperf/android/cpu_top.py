"""
采集并解析 Android top 输出中的整机和目标进程 CPU 指标。
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
from mobileperf.common.utils import FileUtils, TimeUtils


class DeviceCpuinfo:
    pass


class PckCpuinfo:
    """解析一次 top 输出中的整机和目标包 CPU 数据。

    进程 CPU 占用率直接取自 top；该值是采样时刻的瞬时值，底层数据通常来自
    ``/proc/<pid>/stat``。
    """

    # Android 8.0 及以上版本可能返回以下表头和汇总格式。
    # 表头：1:cpu 2:user 3:nice 4:sys 5:idle 6:iow 7:irq 8:sirq 9:host
    # 汇总：400%cpu 56%user 1%nice 46%sys 285%idle 0%iow 10%irq 2%sirq 0%host
    # 较旧版本可能返回：User 0%, System 0%, IOW 0%, IRQ 0%

    RE_CPU = re.compile(r"User (\d+)\%\, System (\d+)\%\, IOW (\d+)\%\, IRQ (\d+)\%")
    RE_CPU_O = re.compile(
        r"(\d+)\%cpu\s+(\d+)\%user\s+(\d+)\%nice\s+(\d+)\%sys\s+(\d+)\%idle\s+(\d+)\%iow\s+(\d+)\%irq\s+(\d+)\%sirq\s+(\d+)\%host"
    )

    def __init__(self, packages, source, sdkversion):
        """初始化解析器。

        :param packages: 需要统计的应用包名列表。
        :param source: ``adb shell top`` 的文本输出。
        """
        self.source = source
        self.sdkversion = sdkversion
        self.datetime = ""
        self.packages = packages
        self.pid = 0
        self.uid = ""
        self.pck_cpu_rate = ""
        self.pck_pyc = ""
        self.uid_cpu_rate = ""
        # 同一应用可能包含多个进程，因此保留每个匹配进程的独立记录。
        # 记录字段包括时间、包名、PID、UID、进程 CPU、调度策略等信息。
        self.package_list = []

        self.device_cpu_rate = ""  # 整机 CPU 使用率
        self.system_rate = ""
        self.user_rate = ""
        self.nice_rate = ""
        self.idle_rate = ""
        self.iow_rate = ""
        self.irq_rate = ""
        self.total_pid_cpu = 0
        self._parse_cpu_usage()
        self._parse_package()

    def _parse_package(self):
        """解析 top 输出中与目标包完全匹配的进程 CPU 信息。"""
        if self.packages is None or self.packages == "":
            logger.error("no process name input, please input")
            return

        for package in self.packages:
            package_dic = {"package": package, "pid": "", "pid_cpu": ""}
            sp_lines = self.source.split("\n")
            for line in sp_lines:
                if package in line:  # 先筛选可能包含目标进程 CPU 信息的行。
                    tmp = line.split()
                    self.pid = tmp[0]
                    target_pck = tmp[-1]  # top 输出的最后一列是进程名。
                    self.datetime = TimeUtils.getCurrentTime()
                    logger.debug(
                        "cpuinfos, _parse top target_pck is : "
                        + str(target_pck)
                        + " , self.pacakgename : "
                        + package
                    )
                    if package == target_pck:  # 只统计进程名与包名完全相同的记录。
                        if int(self.pid) > 0:
                            logger.debug(
                                "cpuinfos, into _parse_pck packege is target package, pid is :"
                                + str(self.pid)
                            )
                            cpu_index = self.get_cpucol_index()
                            uid_index = self.get_uidcol_index()
                            if len(tmp) > cpu_index:
                                self.pck_cpu_rate = tmp[cpu_index]
                                # 部分 top 版本会在 CPU 数值后附带百分号。
                                self.pck_cpu_rate = self.pck_cpu_rate.replace("%", "")
                            if len(tmp) > uid_index:
                                self.uid = tmp[uid_index]
                            package_dic = {
                                "package": package,
                                "pid": self.pid,
                                "pid_cpu": str(self.pck_cpu_rate),
                                "uid": self.uid,
                            }
                            logger.debug(
                                "package: " + package + ", cpu_rate: " + str(self.pck_cpu_rate)
                            )
                            self.total_pid_cpu = self.total_pid_cpu + float(self.pck_cpu_rate or 0)
                        break
            self.package_list.append(package_dic)
            logger.debug(package_dic)

    def _parse_cpu_usage(self):
        """根据 Android 版本解析 top 中的整机 CPU 汇总信息。"""
        if self.sdkversion < 26:  # Android 8.0 之前的输出格式
            match = self.RE_CPU.search(self.source)
            if match:
                self.user_rate = match.group(1)
                self.system_rate = match.group(2)
                self.iow_rate = match.group(3)
                self.irq_rate = match.group(4)
                self.device_cpu_rate = int(self.user_rate) + int(self.system_rate)
                logger.debug(f"  cpuinfos,device system_rate: {self.system_rate}")
                logger.debug(f"  cpuinfos, device user_rate: {self.user_rate}")
                logger.debug(f"  cpuinfos, device device_cpu_rate: {self.device_cpu_rate}")
        else:  # Android 8.0 及以上版本的输出格式
            # 表头顺序与类定义处保留的 Android 8.0 输出样例一致。
            match = self.RE_CPU_O.search(self.source)
            if match:
                self.user_rate = match.group(2)
                self.nice_rate = match.group(3)
                self.system_rate = match.group(4)
                self.idle_rate = match.group(5)
                self.iow_rate = match.group(6)
                self.irq_rate = match.group(7)
                self.device_cpu_rate = int(self.user_rate) + int(self.system_rate)
                logger.debug(
                    "8.0 or higher, user_rate: "
                    + str(self.user_rate)
                    + ", sys: "
                    + str(self.system_rate)
                    + ",device cpu: "
                    + str(self.device_cpu_rate)
                )
                logger.debug(f"idle_rate: {self.idle_rate}")

    def get_cpucol_index(self):
        """返回 CPU 百分比字段在当前 top 输出中的列索引。"""
        return self.get_col_index(self.source, ["CPU]", "CPU%"], 2)

    def get_uidcol_index(self):
        """兼容 UID 和 USER 两种表头并返回对应列索引。"""
        if self.source:
            sp_lines = self.source.split("\n")
            for line in sp_lines:
                if "UID" in line:
                    line_sp = line.split()
                    for key, item in enumerate(line_sp):
                        if item == "UID":
                            return key
                elif "USER" in line:
                    line_sp = line.split()
                    for key, item in enumerate(line_sp):
                        if item == "USER":
                            return key
        return 8

    def get_col_index(self, s, col_name_list, default):
        """按候选列名查找 top 字段索引，未找到时返回默认值。"""
        s = s.split("\n")
        if s:
            for line in s:
                line = line.strip()
                for col_name in col_name_list:
                    if col_name in line:
                        line_sp = re.split(r"\[%|\s+", line)
                        for key, item in enumerate(line_sp):
                            if item == col_name:
                                logger.debug(
                                    "=========== item == col_name: "
                                    + col_name
                                    + " index : "
                                    + str(key)
                                )
                                return key
        return default


class CpuCollector:
    """通过 top 命令按固定间隔采集 CPU 信息。"""

    def __init__(self, device, packages, interval=1, timeout=24 * 60 * 60):
        """配置采集设备、目标包、采集间隔和最长运行时间。"""
        self.device = device
        self.packages = packages
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.cpu_list = []
        self.sdkversion = self.get_sdkversion()
        # 使用批处理模式，避免 top 交互界面截断进程名。
        self.top_cmd = f"top -b -n 1 -d {self._interval:d}"
        ret = self.device.adb.run_shell_cmd(self.top_cmd)
        if ret and 'Invalid argument "-b"' in ret:
            logger.debug("top -b not support")
            self.top_cmd = f"top -n 1 -d {self._interval:d}"
        logger.debug("sdk version : " + str(self.sdkversion))

    def get_sdkversion(self):
        sdk = self.device.adb.get_sdk_version()
        if sdk is None:
            sdk = 25
        return sdk

    def start(self, start_time):
        """启动后台线程采集 CPU 信息。"""
        self.collect_package_cpu_thread = threading.Thread(
            target=self._collect_package_cpu_thread, args=(start_time,), daemon=True
        )
        self.collect_package_cpu_thread.start()
        logger.debug("INFO: CpuCollector start...")

    def stop(self):
        """停止 CPU 采集线程和仍在运行的 top 进程。"""
        logger.debug("INFO: CpuCollector stop...")
        if self.collect_package_cpu_thread.is_alive():
            self._stop_event.set()
            self.collect_package_cpu_thread.join(timeout=2)
            self.collect_package_cpu_thread = None

        if hasattr(self, "_top_pipe"):
            if self._top_pipe.poll() is None:  # 仍在运行时主动终止 top 进程。
                self._top_pipe.terminate()

    def _top_cpuinfo(self):
        self._top_pipe = self.device.adb.run_shell_cmd(self.top_cmd, sync=False)
        out = self._top_pipe.stdout.read()
        error = self._top_pipe.stderr.read()
        if error:
            logger.error("into cpuinfos error : " + str(error))
            return
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="ignore")
        elif not isinstance(out, str):
            out = str(out)
        out = out.replace("\r", "")
        if not out.strip():
            logger.debug("top output is empty")
            return
        top_file = os.path.join(RuntimeData.package_save_path, "top.txt")
        with open(top_file, "a+", encoding="utf-8") as writer:
            writer.write(TimeUtils.getCurrentTime() + " top info:\n")
            writer.write(out + "\n\n")
        # 原始 top 文件超过 100 MB 时删除，避免长期采集占满磁盘。
        if FileUtils.get_FileSize(top_file) > 100:
            os.remove(top_file)
        return PckCpuinfo(self.packages, out, self.sdkversion)

    def _collect_package_cpu_thread(self, start_time):
        """按指定间隔循环采集并保存 CPU 信息。"""
        end_time = time.time() + self._timeout
        cpu_title = ["datetime", "device_cpu_rate%", "user%", "system%", "idle%"]
        cpu_file = os.path.join(RuntimeData.package_save_path, "cpuinfo.csv")
        for i in range(0, len(self.packages)):
            cpu_title.extend(["package", "pid", "pid_cpu%"])
        if len(self.packages) > 1:
            cpu_title.append("total_pid_cpu%")
        try:
            with open(cpu_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(cpu_title)
        except RuntimeError as e:
            logger.error(e)
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                logger.debug(
                    "---------------cpuinfos, into _collect_package_cpu_thread loop thread is : "
                    + str(threading.current_thread().name)
                )
                before = time.time()
                # top 命令自身包含采样间隔，因此需要扣除命令执行耗时。
                cpu_info = self._top_cpuinfo()
                after = time.time()
                time_consume = after - before
                logger.debug("  ============== time consume for cpu info : " + str(time_consume))
                if cpu_info is None or cpu_info.source == "" or not cpu_info.package_list:
                    logger.debug("cpuinfos, can't get cpu info, continue")
                    continue
                self.cpu_list.extend(
                    [
                        TimeUtils.getCurrentTime(),
                        str(cpu_info.device_cpu_rate),
                        cpu_info.user_rate,
                        cpu_info.system_rate,
                        cpu_info.idle_rate,
                    ]
                )
                for i in range(0, len(self.packages)):
                    if len(cpu_info.package_list) == len(self.packages):
                        self.cpu_list.extend(
                            [
                                cpu_info.package_list[i]["package"],
                                cpu_info.package_list[i]["pid"],
                                cpu_info.package_list[i]["pid_cpu"],
                            ]
                        )
                if len(self.packages) > 1:
                    self.cpu_list.append(cpu_info.total_pid_cpu)
                # 按命令耗时校准休眠时间，保持整体采集频率稳定。
                logger.debug("INFO: CpuMonitor save cpu_device_list: " + str(self.cpu_list))
                try:
                    with open(cpu_file, "a+", encoding="utf-8") as df:
                        csv.writer(df, lineterminator="\n").writerow(self.cpu_list)
                        del self.cpu_list[:]
                except RuntimeError as e:
                    logger.error(e)

                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception as e:
                logger.error("an exception hanpend in cpu thread , reason unkown!, e:")
                logger.error(e)
                s = traceback.format_exc()
                logger.debug(s)  # 将异常堆栈写入调试日志。
                if getattr(self, "cpu_queue", None):
                    self.cpu_queue.task_done()
        logger.debug("stop event is set or timeout")


class CpuMonitor:
    """管理 CPU 采集器及其结果目录。"""

    def __init__(self, device_id, packages, interval=5, timeout=24 * 60 * 60):
        self.device = AndroidDevice(device_id)
        self.packages = packages
        self.cpu_collector = CpuCollector(self.device, packages, interval, timeout)

    def start(self, start_time):
        """启动 CPU 监控并按需创建结果目录。"""
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(
                os.path.abspath(os.path.join(os.getcwd(), "../..")),
                "results",
                self.packages[0],
                start_time,
            )
            if not os.path.exists(RuntimeData.package_save_path):
                os.makedirs(RuntimeData.package_save_path)
        self.start_time = start_time
        self.cpu_collector.start(start_time)
        logger.debug("INFO: CpuMonitor has started...")

    def stop(self):
        self.cpu_collector.stop()
        logger.debug("INFO: CpuMonitor has stopped...")

    def save(self):
        pass
