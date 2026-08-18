"""编排 MobilePerf 配置解析、监控器生命周期和采集结果收尾。"""

import argparse
import os
import queue
import sys
import time
from configparser import ConfigParser

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, "../.."))

from mobileperf.android.cpu_top import CpuMonitor
from mobileperf.android.devicemonitor import DeviceMonitor
from mobileperf.android.fd import FdMonitor
from mobileperf.android.fps import FPSMonitor
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.logcat import LogcatMonitor
from mobileperf.android.meminfos import MemMonitor
from mobileperf.android.monkey import Monkey
from mobileperf.android.report import Report
from mobileperf.android.thread_num import ThreadNumMonitor
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.android.trafficstats import TrafficMonitor
from mobileperf.common.log import logger
from mobileperf.common.utils import FileUtils, TimeUtils

_CONFIG_BOM_PREFIXES = ("\ufeff", "\xfe\xff", "\xff\xfe", "\xef\xbb\xbf")


def _remove_config_bom_prefix(content: str) -> str:
    """连续移除配置文件开头的 Unicode 或历史 BOM 表示。"""
    while content:
        for prefix in _CONFIG_BOM_PREFIXES:
            if prefix and content.startswith(prefix):
                content = content[len(prefix) :]
                break
        else:
            break
    return content


def _split_config_list(value: str) -> list[str]:
    """清理分号列表的首尾空白和空项，同时保留顺序与重复项。"""
    return [item.strip() for item in value.split(";") if item.strip()]


class StartUp:
    """管理单次 Android 性能采集会话的启动、等待和停止流程。"""

    def __init__(self, device_id=None, package=None, interval=None, config_path=None):
        RuntimeData.top_dir = os.getcwd()
        if "android" in RuntimeData.top_dir:
            RuntimeData.top_dir = FileUtils.get_top_dir()
        logger.debug("RuntimeData.top_dir:" + RuntimeData.top_dir)
        self.config_path = config_path
        self.config_dic = self.parse_data_from_config()
        RuntimeData.config_dic = self.config_dic
        # 显式参数优先于配置文件，便于上层按采集会话覆盖设备、包名和采样频率。
        self.serialnum = device_id if device_id is not None else self.config_dic["serialnum"]
        self.packages = package if package is not None else self.config_dic["package"]
        self.frequency = interval if interval is not None else self.config_dic["frequency"]
        self.timeout = self.config_dic["timeout"]
        self.exceptionlog_list = self.config_dic["exceptionlog"]
        self.device = AndroidDevice(self.serialnum)
        self.stop_file = os.environ.get("MOBILEPERF_STOP_FILE", "")
        # 未配置包名时，将设备当前的前台进程作为采集目标。
        if not self.packages:
            # ADB 适配层使用井号分隔多个前台进程名称。
            self.packages = self.device.adb.get_foreground_process().split("#")
        RuntimeData.packages = self.packages

        # 保留命令行交互状态。
        self.keycode = ""
        self.pid = 0

        self._init_queue()
        self.monitors = []
        self.logcat_monitor = None

    def _init_queue(self):
        """创建各类性能指标的进程内消息队列。"""
        self.cpu_queue = queue.Queue()
        self.mem_queue = queue.Queue()
        self.power_queue = queue.Queue()
        self.traffic_queue = queue.Queue()
        self.fps_queue = queue.Queue()
        self.activity_queue = queue.Queue()
        self.fd_queue = queue.Queue()
        self.thread_queue = queue.Queue()

    def get_queue_dic(self):
        """返回监控器与数据处理器约定的队列映射。"""
        queue_dic = {}
        queue_dic["cpu_queue"] = self.cpu_queue
        queue_dic["mem_queue"] = self.mem_queue
        queue_dic["power_queue"] = self.power_queue
        queue_dic["traffic_queue"] = self.traffic_queue
        queue_dic["fps_queue"] = self.fps_queue
        queue_dic["fd_queue"] = self.fd_queue
        queue_dic["thread_queue"] = self.thread_queue
        queue_dic["activity_queue"] = self.activity_queue
        return queue_dic

    def add_monitor(self, monitor):
        self.monitors.append(monitor)

    def remove_monitor(self, monitor):
        self.monitors.remove(monitor)

    def parse_data_from_config(self):
        """读取并校验包名、采样频率、设备序列号等采集配置。"""
        config_dic = {}
        configpath = self.config_path or os.path.join(
            RuntimeData.top_dir, "mobileperf", "config.conf"
        )
        logger.debug("configpath:%s" % configpath)
        if not os.path.isfile(configpath):
            logger.error("the config file didn't exist: " + configpath)
            raise RuntimeError("the config file didn't exist: " + configpath)
        # 显式使用 UTF-8，避免 Windows 默认编码导致配置解析失败。
        with open(configpath, encoding="utf-8") as f:
            content = _remove_config_bom_prefix(f.read())
        paser = ConfigParser()
        paser.read_string(content, source=configpath)
        config_dic = self.check_config_option(config_dic, paser, "Common", "package")
        config_dic = self.check_config_option(
            config_dic, paser, "Common", "pid_change_focus_package"
        )
        config_dic = self.check_config_option(config_dic, paser, "Common", "frequency")
        config_dic = self.check_config_option(config_dic, paser, "Common", "dumpheap_freq")
        config_dic = self.check_config_option(config_dic, paser, "Common", "timeout")
        config_dic = self.check_config_option(config_dic, paser, "Common", "serialnum")
        config_dic = self.check_config_option(config_dic, paser, "Common", "mailbox")
        config_dic = self.check_config_option(config_dic, paser, "Common", "exceptionlog")
        config_dic = self.check_config_option(config_dic, paser, "Common", "save_path")
        config_dic = self.check_config_option(config_dic, paser, "Common", "phone_log_path")

        # 读取 Monkey 压力测试配置。
        config_dic = self.check_config_option(config_dic, paser, "Common", "monkey")
        for option in self._monkey_config_options():
            config_dic = self.check_config_option(config_dic, paser, "Common", option)
        config_dic = self.check_config_option(config_dic, paser, "Common", "main_activity")
        config_dic = self.check_config_option(config_dic, paser, "Common", "activity_list")

        logger.debug(config_dic)
        return config_dic

    def check_config_option(self, config_dic, parse, section, option):
        if parse.has_option(section, option):
            try:
                config_dic[option] = parse.get(section, option)
                if option == "frequency" or option in self._monkey_int_options():
                    config_dic[option] = (int)(parse.get(section, option))
                if option == "dumpheap_freq":  # 配置值使用分钟，运行时统一转换为秒。
                    config_dic[option] = (int)(parse.get(section, option)) * 60
                if option == "timeout":  # 配置值使用分钟，运行时统一转换为秒。
                    config_dic[option] = (int)(parse.get(section, option)) * 60
                if option in ["package", "exceptionlog", "phone_log_path"]:
                    config_dic[option] = _split_config_list(parse.get(section, option))
                elif option in ["main_activity", "activity_list"]:
                    config_dic[option] = (
                        parse.get(section, option).strip().replace("\n", "").split(";")
                    )
                elif option in [
                    "space_size_check_path",
                    "pid_change_focus_package",
                    "watcher_users",
                ]:
                    config_dic[option] = parse.get(section, option).split(";")
            except Exception:  # 配置值格式错误时沿用既有失败处理。
                if option != "serialnum":
                    logger.debug("config option error:" + option)
                    self._config_error()
                else:
                    config_dic[option] = ""
        else:  # 未配置的可选项使用默认值，必填项进入错误处理。
            if option in self._optional_config_defaults():
                config_dic[option] = self._optional_config_defaults()[option]
            elif option not in [
                "serialnum",
                "main_activity",
                "activity_list",
                "pid_change_focus_package",
                "shell_file",
            ]:
                logger.debug("config option error:" + option)
                self._config_error()
            else:
                config_dic[option] = ""
        return config_dic

    @staticmethod
    def _monkey_config_options():
        return [
            "monkey_throttle",
            "monkey_seed",
            "monkey_ignore_crashes",
            "monkey_ignore_timeouts",
            "monkey_ignore_security",
            "monkey_kill_after_error",
            "monkey_pct_touch",
            "monkey_pct_motion",
            "monkey_pct_trackball",
            "monkey_pct_nav",
            "monkey_pct_majornav",
            "monkey_pct_syskeys",
            "monkey_pct_appswitch",
            "monkey_pct_anyevent",
            "monkey_pct_flip",
            "monkey_pct_pinchzoom",
        ]

    @staticmethod
    def _monkey_int_options():
        return {
            "monkey_throttle",
            "monkey_seed",
            "monkey_pct_touch",
            "monkey_pct_motion",
            "monkey_pct_trackball",
            "monkey_pct_nav",
            "monkey_pct_majornav",
            "monkey_pct_syskeys",
            "monkey_pct_appswitch",
            "monkey_pct_anyevent",
            "monkey_pct_flip",
            "monkey_pct_pinchzoom",
        }

    @staticmethod
    def _optional_config_defaults():
        return {
            "monkey_throttle": 500,
            "monkey_seed": 1000000,
            "monkey_ignore_crashes": "true",
            "monkey_ignore_timeouts": "true",
            "monkey_ignore_security": "true",
            "monkey_kill_after_error": "true",
            "monkey_pct_touch": 15,
            "monkey_pct_motion": 5,
            "monkey_pct_trackball": 0,
            "monkey_pct_nav": 40,
            "monkey_pct_majornav": 30,
            "monkey_pct_syskeys": 5,
            "monkey_pct_appswitch": 0,
            "monkey_pct_anyevent": 5,
            "monkey_pct_flip": 0,
            "monkey_pct_pinchzoom": 0,
        }

    def _monkey_options(self):
        def _enabled(key):
            return str(self.config_dic.get(key, "true")).lower() == "true"

        return {
            "throttle_ms": self.config_dic.get("monkey_throttle", 500),
            "seed": self.config_dic.get("monkey_seed", 1000000),
            "ignore_crashes": _enabled("monkey_ignore_crashes"),
            "ignore_timeouts": _enabled("monkey_ignore_timeouts"),
            "ignore_security": _enabled("monkey_ignore_security"),
            "kill_after_error": _enabled("monkey_kill_after_error"),
            "pct_touch": self.config_dic.get("monkey_pct_touch", 15),
            "pct_motion": self.config_dic.get("monkey_pct_motion", 5),
            "pct_trackball": self.config_dic.get("monkey_pct_trackball", 0),
            "pct_nav": self.config_dic.get("monkey_pct_nav", 40),
            "pct_majornav": self.config_dic.get("monkey_pct_majornav", 30),
            "pct_syskeys": self.config_dic.get("monkey_pct_syskeys", 5),
            "pct_appswitch": self.config_dic.get("monkey_pct_appswitch", 0),
            "pct_anyevent": self.config_dic.get("monkey_pct_anyevent", 5),
            "pct_flip": self.config_dic.get("monkey_pct_flip", 0),
            "pct_pinchzoom": self.config_dic.get("monkey_pct_pinchzoom", 0),
        }

    def _config_error(self):
        logger.error("config error, please config it correctly")
        sys.exit(1)

    def run(self, time_out=None):
        """启动所有采集器并等待超时、停止文件或异常退出信号。"""
        self.clear_heapdump()
        # 启动采集前检查目标设备是否可用。
        if not self.serialnum:
            # 未指定设备序列号时，由 ADB 使用当前连接设备。
            logger.info("serialnum in config file is null,default get connected phone")
        is_device_connect = False
        for i in range(0, 5):
            if self.device.adb.is_connected(self.serialnum):
                is_device_connect = True
                break
            else:
                logger.error("device not found:" + self.serialnum)
                time.sleep(2)
        if not is_device_connect:
            logger.error("after 5 times check,device not found:" + self.serialnum)
            return
        # 应用安装状态仅在会话启动时检查一次。
        if not self.device.adb.is_app_installed(self.packages[0]):
            logger.error("test app not installed:" + self.packages[0])
            return
        try:
            self.add_monitor(
                CpuMonitor(self.serialnum, self.packages, self.frequency, self.timeout)
            )
            self.add_monitor(
                MemMonitor(self.serialnum, self.packages, self.frequency, self.timeout)
            )
            self.add_monitor(
                TrafficMonitor(self.serialnum, self.packages, self.frequency, self.timeout)
            )
            # 软件电量估算误差较大，当前采集流程不启用该监控器。
            self.add_monitor(
                FPSMonitor(self.serialnum, self.packages[0], self.frequency, self.timeout)
            )
            # 高版本 Android 可能限制文件描述符读取权限，监控器自行处理采集失败。
            self.add_monitor(
                FdMonitor(self.serialnum, self.packages[0], self.frequency, self.timeout)
            )
            self.add_monitor(
                ThreadNumMonitor(self.serialnum, self.packages[0], self.frequency, self.timeout)
            )
            if self.config_dic["monkey"] == "true":
                self.add_monitor(
                    Monkey(
                        self.serialnum,
                        self.packages[0],
                        timeout=self.timeout,
                        **self._monkey_options(),
                    )
                )
            if self.config_dic["main_activity"] and self.config_dic["activity_list"]:
                self.add_monitor(
                    DeviceMonitor(
                        self.serialnum,
                        self.packages[0],
                        self.frequency,
                        self.config_dic["main_activity"],
                        self.config_dic["activity_list"],
                        RuntimeData.exit_event,
                    )
                )

            if len(self.monitors):
                start_time = TimeUtils.getCurrentTimeUnderline()
                RuntimeData.start_time = start_time
                if self.config_dic["save_path"]:
                    RuntimeData.package_save_path = os.path.join(
                        self.config_dic["save_path"], self.packages[0], start_time
                    )
                else:
                    RuntimeData.package_save_path = os.path.join(
                        RuntimeData.top_dir, "results", self.packages[0], start_time
                    )
                FileUtils.makedir(RuntimeData.package_save_path)
                self.save_device_info()
                for monitor in self.monitors:
                    # 单个监控器启动失败不阻止其他指标继续采集。
                    try:
                        monitor.start(start_time)
                    except Exception as e:
                        logger.error(e)
                # Logcat 具有独立的阻塞读取生命周期，因此与其他监控器分开管理。
                try:
                    self.logcat_monitor = LogcatMonitor(self.serialnum, self.packages[0])
                    # 仅在配置异常关键字后注册异常日志处理器。
                    if self.exceptionlog_list:
                        self.logcat_monitor.set_exception_list(self.exceptionlog_list)
                        self.logcat_monitor.add_log_handle(self.logcat_monitor.handle_exception)
                    time.sleep(1)
                    self.logcat_monitor.start(start_time)
                except Exception as e:
                    logger.error(e)

                timeout = time_out if time_out is not None else self.config_dic["timeout"]
                endtime = time.time() + timeout
                while time.time() < endtime:  # 保持主线程存活，直至达到任一退出条件。
                    # 测试过程中优先响应应用异常或外部停止信号。
                    if self.check_exit_signal_quit():
                        logger.error("app " + str(self.packages[0]) + " exit signal, quit!")
                        break
                    if self.check_stop_file_quit():
                        logger.info("stop file detected, finish mobileperf and create report")
                        break
                    time.sleep(self.frequency)
                logger.debug("time is up,finish!!!")
                self.stop()
        except KeyboardInterrupt:  # 捕获命令行中断并执行统一收尾。
            logger.debug(" catch keyboardInterrupt, goodbye!!!")
            self.stop()
            os._exit(0)
        except Exception as e:
            logger.error("Exception in run")
            logger.error(e)

    def clear_heapdump(self):
        """删除目标应用超过三天的历史堆转储，避免与本次采集混淆。"""
        filelist = self.device.adb.list_dir("/data/local/tmp")
        if filelist:
            for file in filelist:
                if self.packages[0] in file and self.device.adb.is_overtime_days(
                    "/data/local/tmp/" + file, 3
                ):
                    self.device.adb.delete_file("/data/local/tmp/%s" % file)

    def stop(self):
        """停止监控器、生成报告并回收本次采集产生的设备侧文件。"""
        for monitor in self.monitors:
            try:
                monitor.stop()
            except Exception as e:  # 单个监控器停止失败不得阻断其余监控器的清理。
                logger.error(e)

        try:
            if self.logcat_monitor:
                self.logcat_monitor.stop()
        except Exception as e:
            logger.error("stop exception for logcat monitor")
            logger.error(e)
        if self.config_dic["monkey"] == "true":
            self.device.adb.kill_process("com.android.commands.monkey")
        try:
            # 将测试时长追加到设备信息文件。
            cost_time = round(
                (float)(
                    time.time()
                    - TimeUtils.getTimeStamp(RuntimeData.start_time, TimeUtils.UnderLineFormatter)
                )
                / 3600,
                2,
            )
            self.add_device_info("test cost time:", str(cost_time) + "h")
        except Exception as e:
            logger.error("add test cost time failed")
            logger.error(e)
        try:
            # 根据 CSV 采集结果生成 Excel 汇总文件。
            Report(RuntimeData.package_save_path, self.packages)
        except Exception as e:
            logger.error("create report failed")
            logger.error(e)
        try:
            self.pull_heapdump()
        except Exception as e:
            logger.error("pull heapdump failed")
            logger.error(e)
        try:
            self.pull_log_files()
        except Exception as e:
            logger.error("pull log files failed")
            logger.error(e)
        os._exit(0)

    def memory_analyse(self):
        """保留内存分析兼容入口，当前未启用具体实现。"""
        pass

    def pull_heapdump(self):
        """将目标应用的设备侧堆转储拉取到本次结果目录。"""
        filelist = self.device.adb.list_dir("/data/local/tmp")
        if filelist:
            for file in filelist:
                if self.packages[0] in file:
                    self.device.adb.pull_file(
                        "/data/local/tmp/%s" % file, RuntimeData.package_save_path
                    )

    def pull_log_files(self):
        """将配置的设备日志目录拉取到本次结果目录。"""
        if self.config_dic["phone_log_path"]:
            for src_path in self.config_dic["phone_log_path"]:
                self.device.adb.pull_file(src_path, RuntimeData.package_save_path)

    def save_device_info(self):
        """记录本次采集使用的设备和应用版本信息。"""
        device_file = os.path.join(RuntimeData.package_save_path, "device_test_info.txt")
        with open(device_file, "w+", encoding="utf-8") as writer:
            writer.write("device serialnum:" + self.serialnum + "\n")
            writer.write(
                "device model:"
                + self.device.adb.get_phone_brand()
                + " "
                + self.device.adb.get_phone_model()
                + "\n"
            )
            writer.write("test package:" + self.packages[0] + "\n")
            writer.write("system version:" + self.device.adb.get_system_version() + "\n")
            writer.write(
                "test package ver:" + self.device.adb.get_package_ver(self.packages[0]) + "\n"
            )

    def add_device_info(self, key, value):
        device_file = os.path.join(RuntimeData.package_save_path, "device_test_info.txt")
        with open(device_file, "a+", encoding="utf-8") as writer:
            writer.write(key + ":" + value + "\n")

    def check_exit_signal_quit(self):
        if RuntimeData.exit_event.is_set():
            return True
        else:
            return False

    def check_stop_file_quit(self):
        return bool(self.stop_file and os.path.exists(self.stop_file))


class App:
    """保存应用包名、名称和版本信息的轻量数据对象。"""

    def __init__(self, package, name="", version=""):
        self.package = package
        self.name = name
        self.version = version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run mobileperf collection")
    parser.add_argument("--config", default=None, help="Path to mobileperf config file")
    args = parser.parse_args()
    startup = StartUp(config_path=args.config)
    startup.run()
