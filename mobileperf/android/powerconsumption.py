"""
采集 Android 设备的电量、电压、温度和电流等电池指标。
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
from mobileperf.common.utils import TimeUtils, mV2V, transfer_temp, uA2mA


class DevicePowerInfo:
    RE_BATTERY = re.compile(r"level: (\d+) voltage: (\d+) temp: (\d+)")
    RE_CURRENT = re.compile(r"current now: (\S?\d+)")

    def __init__(self, source=None):
        """使用 dumpsys batteryproperties 输出初始化电池信息。"""
        self.source = source
        self.level = 0  # 电量通常以 100 为满量程。
        self.voltage = 0  # 电压
        self.temp = 0  # 温度
        self.current = 0  # 电流由设备底层上报，精度取决于具体设备。
        self._parse()

    def _parse(self):
        if self.source:
            match = self.RE_BATTERY.search(self.source)
            if match:
                self.level = match.group(1)
                self.voltage = match.group(2)
                self.temp = match.group(3)

            match = self.RE_CURRENT.search(self.source)
            if match:
                self.current = match.group(1)

    def __repr__(self):
        return (
            "DevicePowerInfo, "
            + "level:"
            + str(self.level)
            + ", voltage:"
            + str(self.voltage)
            + ", temperature:"
            + str(self.temp)
            + ", current:"
            + str(self.current)
        )


class PowerCollector:
    def __init__(
        self,
        device,
        interval=1.0,
        timeout=24 * 60 * 60,
        power_queue=None,
    ):
        self.device = device
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.power_queue = power_queue

    def start(self, start_time):
        logger.debug("INFO: PowerCollector  start...")
        self.collect_power_thread = threading.Thread(
            target=self._collect_power_thread, args=(start_time,)
        )
        self.collect_power_thread.start()

    def _get_battaryproperties(self):
        """返回设备电量、温度、电压和电流等电池属性。"""
        # Android 5.0 及以上版本优先通过 batteryproperties 获取信息。
        out = self.device.adb.run_shell_cmd("dumpsys batteryproperties")
        out.replace("\r", "")
        power_info = None
        if not out or (isinstance(out, str) and ("Can't find service") in out):
            # Android 4.x 使用 dumpsys battery 兼容路径。
            logger.debug("get battery info from dumpsys battery")
            reg = self.device.adb.run_shell_cmd("dumpsys battery")
            reg.replace("\r", "")
            power_info = DevicePowerInfo()
            power_dic = self._get_powerinfo_dic(reg)
            power_info.level = power_dic["level"]
            power_info.temp = power_dic["temperature"]
            power_info.voltage = power_dic["voltage"]
            current_flag = power_dic["current_flag"]
            if current_flag == -1:
                # 部分版本不在 dumpsys battery 中提供电流，需要读取内核节点。
                power_info.current = self._cat_current()
            else:
                power_info.current = power_dic["current"]
        else:
            power_info = DevicePowerInfo(out)
            if power_info.voltage == "0":  # 部分设备会返回无效零值，此时改用兼容命令。
                logger.debug(" power info from dumpsys properties is 0, trim it")
                reg = self.device.adb.run_shell_cmd("dumpsys battery")
                reg.replace("\r", "")
                power_dic = self._get_powerinfo_dic(reg)
                power_info.level = power_dic["level"]
                power_info.temp = power_dic["temperature"]
                power_info.voltage = power_dic["voltage"]
        logger.debug(power_info)
        return power_info

    def _cat_current(self):
        current = 0
        # Android 9 及以上版本可能无权读取该电流节点。
        reg = self.device.adb.run_shell_cmd("cat /sys/class/power_supply/battery/current_now")
        if isinstance(reg, str) and "No such file or directory" == reg:
            logger.debug("can't get current from file /sys/class/power_supply/battery/current_now")
        elif reg:
            current = reg
        return current

    def _get_powerinfo_dic(self, out):
        """将 dumpsys battery 输出解析为电池信息字典。"""
        dic = {}
        if out:
            level_l = re.findall(r"level:\s?(\d+)", out)
            temp_l = re.findall(r"temperature:\s?(\d+)", out)
            current_l = re.findall(r"current now:\s?(\d+)", out)
            vol_l = re.findall(r"  voltage:\s?(\d+)", out)
            vol_ll = re.findall(r"  voltage:\s?(\d+)", out)
            logger.debug(vol_ll)
            dic["level"] = level_l[0] if len(level_l) else 0
            dic["temperature"] = temp_l[0] if len(temp_l) else 0
            dic["current"] = current_l[0] if len(current_l) else 0
            dic["voltage"] = vol_l[0] if len(vol_l) else 0
            if len(current_l):
                dic["current"] = current_l[0]
                dic["current_flag"] = 1
            else:
                dic["current_flag"] = -1
                dic["current"] = 0
        return dic

    def _collect_power_thread(self, start_time):
        """循环采集电池信息并写入文件或上报队列。"""
        end_time = time.time() + self._timeout
        power_list_titile = ("datetime", "level", "voltage(V)", "tempreture(C)", "current(mA)")
        power_device_file = os.path.join(RuntimeData.package_save_path, "powerinfo.csv")
        try:
            with open(power_device_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(power_list_titile)
                if self.power_queue:
                    power_file_dic = {"power_file": power_device_file}
                    self.power_queue.put(power_file_dic)
        except RuntimeError as e:
            logger.error(e)
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "------------into _collect_power_thread loop thread is : "
                    + str(threading.current_thread().name)
                )
                device_power_info = self._get_battaryproperties()

                if device_power_info.source == "":
                    logger.debug("can't get power info , break!")
                    break
                device_power_info = self.trim_data(device_power_info)
                collection_time = time.time()
                logger.debug(" collection time in powerconsumption is : " + str(collection_time))
                power_tmp_list = [
                    collection_time,
                    device_power_info.level,
                    device_power_info.voltage,
                    device_power_info.temp,
                    device_power_info.current,
                ]

                if self.power_queue:
                    self.power_queue.put(power_tmp_list)

                if not self.power_queue:  # 未提供上报队列时直接保存本地结果。
                    power_tmp_list[0] = TimeUtils.formatTimeStamp(power_tmp_list[0])
                    try:
                        with open(power_device_file, "a+", encoding="utf-8") as writer:
                            writer_p = csv.writer(writer, lineterminator="\n")
                            writer_p.writerow(power_tmp_list)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception:
                logger.error("an exception hanpend in powerconsumption thread , reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.power_queue:
                    self.power_queue.task_done()

    def trim_data(self, power_info):
        power_info.voltage = mV2V(float(power_info.voltage))
        power_info.temp = transfer_temp(float(power_info.temp))
        power_info.current = uA2mA(float(power_info.current))
        return power_info

    def stop(self):
        """停止电池信息采集线程。"""
        logger.debug("INFO: PowerCollector  stop...")
        if self.collect_power_thread.is_alive():
            self._stop_event.set()
            self.collect_power_thread.join(timeout=1)
            self.collect_power_thread = None
            # 采集线程结束后通知上报队列当前任务已经完成。
            if self.power_queue:
                self.power_queue.task_done()


class PowerMonitor:
    def __init__(self, device_id, interval=1.0, timeout=24 * 60 * 60, power_queue=None):
        self.device = AndroidDevice(device_id)
        self.power_collector = PowerCollector(self.device, interval, timeout, power_queue)

    def start(self, start_time):
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(
                os.path.abspath(os.path.join(os.getcwd(), "../..")),
                "results",
                self.device.adb._device_id,
                start_time,
            )
            if not os.path.exists(RuntimeData.package_save_path):
                os.makedirs(RuntimeData.package_save_path)
        self.start_time = start_time
        self.power_collector.start(start_time)
        logger.debug("INFO: PowerMonitor has started...")

    def stop(self):
        self.power_collector.stop()
        logger.debug("INFO: PowerMonitor has stopped...")

    def _get_power_collector(self):
        return self.power_collector

    def save(self):
        pass
