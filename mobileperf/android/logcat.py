"""采集设备 logcat，并提取异常日志和应用启动耗时。"""

import csv
import os
import sys
import time

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, "../.."))

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.basemonitor import Monitor
from mobileperf.common.log import logger
from mobileperf.common.utils import FileUtils, TimeUtils, ms2s


class LogcatMonitor(Monitor):
    """管理设备 logcat 的启动、停止和实时回调。"""

    def __init__(self, device_id, package=None, **regx_config):
        """初始化目标设备、进程过滤条件和日志匹配配置。

        :param str device_id: 设备标识
        :param list package : 监控的进程列表，列表为空时，监控所有进程
        :param dict regx_config : 按配置标识注册的日志正则表达式
        """
        super().__init__(**regx_config)
        self.package = package
        self.device_id = device_id
        self.device = AndroidDevice(device_id)
        self.running = False  # 标记 logcat 是否已经启动。
        self.launchtime = LaunchTime(self.device_id, self.package)
        self.exception_log_list = []
        self.start_time = None

        self.append_log_line_num = 0
        self.file_log_line_num = 0
        self.log_file_create_time = None

    def start(self, start_time):
        """启动 logcat 并注册启动耗时回调。"""
        self.start_time = start_time
        # 注册启动耗时回调。
        self.add_log_handle(self.launchtime.handle_launchtime)
        logger.debug("logcatmonitor start...")
        # 捕获全部缓冲区和进程日志，缓冲区含义参考 Android 官方文档。
        # https://developer.android.com/studio/command-line/logcat#alternativeBuffers
        # 默认缓冲区只有 main、system 和 crash，此处显式输出全部缓冲区。
        if not self.running:
            self.device.adb.start_logcat(RuntimeData.package_save_path, [], " -b all")
            time.sleep(1)
            self.running = True

    def stop(self):
        """移除回调并停止设备 logcat 进程。"""
        logger.debug("logcat monitor: stop...")
        self.remove_log_handle(self.launchtime.handle_launchtime)
        logger.debug("logcat monitor: stopped")
        if self.exception_log_list:
            self.remove_log_handle(self.handle_exception)
        self.device.adb.stop_logcat()
        self.running = False

    def parse(self, file_path):
        pass

    def set_exception_list(self, exception_log_list):
        self.exception_log_list = exception_log_list

    def add_log_handle(self, handle):
        """添加实时日志处理器，每产生一条日志就调用一次。"""
        self.device.adb._logcat_handle.append(handle)

    def remove_log_handle(self, handle):
        """删除已经注册的实时日志处理器。"""
        self.device.adb._logcat_handle.remove(handle)

    def handle_exception(self, log_line):
        """匹配最新日志中的异常关键字，并保存异常文本和旧进程堆栈。"""

        for tag in self.exception_log_list:
            if tag in log_line:
                logger.debug("exception Info: " + log_line)
                tmp_file = os.path.join(RuntimeData.package_save_path, "exception.log")
                with open(tmp_file, "a+", encoding="utf-8") as f:
                    f.write(log_line + "\n")
                process_stack_log_file = os.path.join(
                    RuntimeData.package_save_path,
                    "process_stack_%s_%s.log" % (self.package, TimeUtils.getCurrentTimeUnderline()),
                )
                # 进程异常退出后 PID 可能变化，只允许使用异常发生时保存的旧 PID。
                if RuntimeData.old_pid:
                    self.device.adb.get_process_stack_from_pid(
                        RuntimeData.old_pid, process_stack_log_file
                    )


class LaunchTime:
    def __init__(self, deviceid, packagename=""):
        # 启动记录会在每次写入 CSV 后清空，避免长时间采集持续占用内存。
        self.launch_list = [
            ("datetime", "packagenme/activity", "this_time(s)", "total_time(s)", "launchtype")
        ]
        self.packagename = packagename

    def handle_launchtime(self, log_line):
        """解析最新的 Activity 启动或 fully drawn 日志，并写入启动记录。"""
        ltag = ""
        if "am_activity_launch_time" in log_line or "am_activity_fully_drawn_time" in log_line:
            # 同时兼容普通启动和 fully drawn 两种系统事件。
            if "am_activity_launch_time" in log_line:
                ltag = "normal launch"
            elif "am_activity_fully_drawn_time" in log_line:
                ltag = "fullydrawn launch"
            logger.debug("launchtime log:" + log_line)
        if ltag:
            content = []
            timestamp = time.time()
            content.append(TimeUtils.formatTimeStamp(timestamp))
            temp_list = log_line.split()[-1].replace("[", "").replace("]", "").split(",")[2:5]
            for i in range(len(temp_list)):
                content.append(temp_list[i])
            content.append(ltag)
            logger.debug("Launch Info: " + str(content))
            if len(content) == 5:
                content = self.trim_value(content)
                if content:
                    self.update_launch_list(content, timestamp)

    def trim_value(self, content):
        try:
            content[2] = ms2s(float(content[2]))  # 将本次启动耗时转换为秒。
            content[3] = ms2s(float(content[3]))  # 将总启动耗时转换为秒。
        except Exception as e:
            logger.error(e)
            return []
        return content

    def update_launch_list(self, content, timestamp):
        self.launch_list.append(content)
        tmp_file = os.path.join(RuntimeData.package_save_path, "launch_logcat.csv")
        perf_data = {
            "task_id": "",
            "launch_time": [],
            "cpu": [],
            "mem": [],
            "traffic": [],
            "fluency": [],
            "power": [],
        }
        dic = {
            "time": timestamp,
            "act_name": content[1],
            "this_time": content[2],
            "total_time": content[3],
            "launch_type": content[4],
        }
        perf_data["launch_time"].append(dic)
        with open(tmp_file, "a+", encoding="utf-8") as f:
            csvwriter = csv.writer(f, lineterminator="\n")  # 显式换行符可避免 CSV 空行。
            logger.debug("save launchtime data to csv: " + str(self.launch_list))
            csvwriter.writerows(self.launch_list)
            del self.launch_list[:]


if __name__ == "__main__":
    logcat_monitor = LogcatMonitor("85I7UO4PFQCINJL7", "com.yunos.tv.alitvasr")
    # 仅在配置异常关键字时注册异常日志处理器。
    exceptionlog_list = ["fatal exception", "has died"]
    if exceptionlog_list:
        logcat_monitor.set_exception_list(exceptionlog_list)
        logcat_monitor.add_log_handle(logcat_monitor.handle_exception)
    start_time = TimeUtils.getCurrentTimeUnderline()
    RuntimeData.package_save_path = os.path.join(
        FileUtils.get_top_dir(), "results", "com.yunos.tv.alitvasr", start_time
    )
    logcat_monitor.start(start_time)
