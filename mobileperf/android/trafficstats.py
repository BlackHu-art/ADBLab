"""采集并解析应用 UID、设备和进程维度的网络流量。"""

import csv
import os
import re
import threading
import time
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice, _shq
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class TrafficUtils:
    @staticmethod
    def getUID(device, pkg):
        """从 dumpsys package 输出中解析目标包的 UID。"""
        uid = None
        _cmd = f"dumpsys package {_shq(pkg)}"
        out = device.adb.run_shell_cmd(_cmd)
        lines = out.replace("\r", "").splitlines()
        logger.debug("line length: " + str(len(lines)))
        if len(lines) > 0:
            for line in lines:
                if "Unable to find package:" in line:
                    logger.error(" trafficstat: Unable to find package : " + pkg)
                    continue
            adb_result = re.findall(r"userId=(\d+)", out)
            if len(adb_result) > 0:
                uid = adb_result[0]
                logger.debug("getUid for pck: " + pkg + ", UID: " + uid)
        else:
            logger.error(" trafficstat: Unable to find package : " + pkg)
        return uid

    @staticmethod
    def byte2kb(value):
        return round(value / 1024.0, 2)


# UID 统计可获得总体收发流量，但厂商网络接口命名不同，无法可靠区分 Wi-Fi 和移动网络。


class TrafficSnapshot:
    """解析 ``/proc/net/xt_qtaguid/stats`` 中从设备启动起累计的 UID 流量。"""

    def __init__(self, source, packagename, uid):
        self.source = source
        self.uid = uid
        self.packagename = packagename
        self.rx_uid_bytes = 0  # UID 接收字节数。
        self.rx_uid_packets = 0  # UID 接收数据包数。
        self.tx_uid_bytes = 0  # UID 发送字节数。
        self.tx_uid_packets = 0  # UID 发送数据包数。
        self.total_uid_bytes = 0  # UID 自设备启动以来的总流量，包含本地流量。
        self.total_uid_packets = 0
        self.lo_uid_bytes = 0  # UID 的本地回环流量。
        self.bg_bytes = 0  # UID 的后台流量。
        self.fg_bytes = 0  # UID 的前台流量。
        self._parse()

    def _parse(self):
        sp_lines = self.source.split("\n")
        for line in sp_lines:
            tart_list = line.split()
            # /proc/net/xt_qtaguid/stats 列序：idx iface acct_tag_hex uid cnt_set rx_bytes ...
            if len(tart_list) < 9 or not self.uid or tart_list[3] != self.uid:
                continue
            tag = tart_list[2]
            if tag == "0x0":  # 只统计与 UID 直接关联的默认 acct_tag_hex。
                    self.rx_uid_bytes += int(tart_list[5])  # 汇总所有网络接口的接收字节。
                    self.rx_uid_packets += int(tart_list[6])
                    self.tx_uid_bytes += int(tart_list[7])
                    self.tx_uid_packets += int(tart_list[8])
                    self.total_uid_bytes = self.tx_uid_bytes + self.rx_uid_bytes
                    self.total_uid_packets = self.tx_uid_packets + self.rx_uid_packets
                    if tart_list[1] == "lo":  # iface 为 lo 时记录本地回环流量。
                        self.lo_uid_bytes += int(tart_list[5]) + int(tart_list[7])
                    if int(tart_list[4]) == 0:  # set 字段为 0 表示后台流量。
                        self.bg_bytes += int(tart_list[5]) + int(tart_list[7])
                    elif int(tart_list[4]) == 1:  # set 字段为 1 表示前台流量。
                        self.fg_bytes += int(tart_list[5]) + int(tart_list[7])

        logger.debug(" total uid  bytes : " + str(self.total_uid_bytes))

    def __repr__(self):
        return (
            "TrafficSnapshot, "
            + "package: "
            + str(self.packagename)
            + " uid bytes: "
            + str(self.total_uid_bytes)
            + " uid pcket byte: "
            + str(self.total_uid_packets)
        )


class NetDevInfo:
    """解析 ``/proc/net/dev`` 或 ``/proc/<pid>/net/dev`` 的接口统计。

    输出遵循 ``接口名: 接收字段... 发送字段...`` 格式，例如
    ``wlan0: <rx_bytes> ... <tx_bytes> ...``。
    """

    def __init__(self, source):
        self.source = source
        self.mobile_total = 0
        self.mobile_rx = 0
        self.mobile_tx = 0
        self.wifi_total = 0
        self.wifi_rx = 0
        self.wifi_tx = 0
        self.total = 0
        self.rx = 0
        self.tx = 0
        self._parse()

    def _parse(self):
        sp_lines = self.source.split("\n")
        for line in sp_lines:
            # wlan0 的第 1、9 个数值字段分别表示接收和发送字节数。
            if "wlan0:" in line:
                items = line.split()
                if len(items) < 10:
                    continue
                self.wifi_rx = int(items[1])
                self.wifi_tx = int(items[9])
                self.wifi_total = self.wifi_rx + self.wifi_tx
                logger.debug(
                    "wifi_rx : "
                    + items[1]
                    + " wifi_tx : "
                    + items[9]
                    + " total wifi:"
                    + str(self.wifi_total)
                )
                # rmnet0 表示移动网络接口流量。
            if "rmnet0:" in line:
                items = line.split()
                if len(items) < 10:
                    continue
                self.mobile_rx = int(items[1])
                self.mobile_tx = int(items[9])
                self.mobile_total = self.mobile_rx + self.mobile_tx
                logger.debug(
                    "mobile_rx : "
                    + items[1]
                    + " mobile_tx : "
                    + items[9]
                    + " total mobile:"
                    + str(self.mobile_total)
                )
            self.rx = self.wifi_rx + self.mobile_rx
            self.tx = self.wifi_tx + self.mobile_tx
            self.total = self.wifi_total + self.mobile_total

    def __repr__(self):
        return "NetDevInfo "


class TrafficCollecor:
    def __init__(self, device, packages, interval=1.0, timeout=24 * 60 * 60, traffic_queue=None):
        self.device = device
        self.packages = packages
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.traffic_queue = traffic_queue
        self.sdk_version = self.device.adb.get_sdk_version()

        # 首轮采样只建立基线，后续结果均计算相对增量。
        self.traffic_init = True
        self.traffic_init_dic = {}

    def start(self, start_time):
        logger.debug("INFO: TrafficCollecor  start...")
        self.collect_traffic_thread = threading.Thread(
            target=self._collect_traffic_thread, args=(start_time,), daemon=True
        )
        self.collect_traffic_thread.start()

    def _cat_traffic_data(self, packagename, uid):
        out = self.device.adb.run_shell_cmd("cat /proc/net/xt_qtaguid/stats")
        out.replace("\r", "")
        return TrafficSnapshot(out, packagename, uid)

    def _cat_traffic_device_dev(self):
        out = self.device.adb.run_shell_cmd("cat /proc/net/dev")
        out.replace("\r", "")
        return NetDevInfo(out)

    def _cat_traffic_pid_dev(self, pid):
        out = self.device.adb.run_shell_cmd(f"cat /proc/{pid:d}/net/dev")
        out.replace("\r", "")
        return NetDevInfo(out)

    def _collect_traffic_thread(self, start_time):
        # Android 10 之前从 /proc/net/xt_qtaguid/stats 读取 UID 流量。
        if self.sdk_version < 29:
            self.get_traffic_with_stats()
        else:
            # Android 10 起分别从设备和进程的 /proc/net/dev 读取流量。
            self.get_traffic_with_dev()

    def get_traffic_with_stats(self):
        end_time = time.time() + self._timeout
        uid = TrafficUtils.getUID(self.device, self.packages[0])
        traffic_list_title = (
            "datetime",
            "packagename",
            "uid",
            "uid_total(KB)",
            "uid_total_packets",
            "rx(KB)",
            "rx_packets",
            "tx(KB)",
            "tx_packets",
            "fg(KB)",
            "bg(KB)",
            "lo(KB)",
        )
        traffic_file = os.path.join(RuntimeData.package_save_path, "traffics_uid.csv")
        try:
            with open(traffic_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(traffic_list_title)
                if self.traffic_queue:
                    traffic_file_dic = {"traffic_file": traffic_file}
                    self.traffic_queue.put(traffic_file_dic)
        except RuntimeError as e:
            logger.error(e)

        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "----------------- into _collect_traffic_thread loop thread is : "
                    + str(threading.current_thread().name)
                    + ", current uid is : "
                    + str(uid)
                )
                traffic_snapshot = self._cat_traffic_data(self.packages[0], uid)

                if traffic_snapshot.source == "" or traffic_snapshot.source is None:
                    continue  # 本轮没有采集结果时直接等待下一轮。

                if self.traffic_init:
                    self.traffic_init_dic = self.get_traffic_init_data(traffic_snapshot)
                    self.traffic_init = False
                traffic_snapshot = self.get_data_from_threadstart(traffic_snapshot)

                collection_time = time.time()
                logger.debug(" collection time in traffic is : " + str(collection_time))
                traffic_list_temp = [
                    collection_time,
                    traffic_snapshot.packagename,
                    traffic_snapshot.uid,
                    TrafficUtils.byte2kb(traffic_snapshot.total_uid_bytes),
                    traffic_snapshot.total_uid_packets,
                    TrafficUtils.byte2kb(traffic_snapshot.rx_uid_bytes),
                    traffic_snapshot.rx_uid_packets,
                    TrafficUtils.byte2kb(traffic_snapshot.tx_uid_bytes),
                    traffic_snapshot.tx_uid_packets,
                    TrafficUtils.byte2kb(traffic_snapshot.fg_bytes),
                    TrafficUtils.byte2kb(traffic_snapshot.bg_bytes),
                    TrafficUtils.byte2kb(traffic_snapshot.lo_uid_bytes),
                ]
                logger.debug(traffic_list_temp)
                if self.traffic_queue:
                    self.traffic_queue.put(traffic_list_temp)

                if not self.traffic_queue:  # 无上游消费者时直接写入本地 CSV。
                    traffic_list_temp[0] = TimeUtils.formatTimeStamp(traffic_list_temp[0])
                    try:
                        with open(traffic_file, "a+", encoding="utf-8") as f:
                            writer = csv.writer(f, lineterminator="\n")
                            writer.writerow(traffic_list_temp)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                logger.debug(" -----------traffic timeconsumed: " + str(time_consume))
                # 扣除命令执行耗时，使采样周期尽量接近配置间隔。
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
            except Exception:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                if self.traffic_queue:
                    self.traffic_queue.task_done()

    def get_traffic_with_dev(self):
        end_time = time.time() + self._timeout
        traffic_title = [
            "datetime",
            "device_total(KB)",
            "device_receive(KB)",
            "device_transport(KB)",
        ]
        traffic_file = os.path.join(RuntimeData.package_save_path, "traffic.csv")
        for i in range(0, len(self.packages)):
            traffic_title.extend(["package", "pid", "pid_rx(KB)", "pid_tx(KB)", "pid_total(KB)"])
        if len(self.packages) > 1:
            traffic_title.append("total_proc_traffic(kB)")
        try:
            with open(traffic_file, "a+") as df:
                csv.writer(df, lineterminator="\n").writerow(traffic_title)
        except RuntimeError as e:
            logger.error(e)
        self.device_init_net = None
        self.pck_init_net_list = []
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "--------- into _collect_traffic_thread loop thread is : "
                    + str(threading.current_thread().name)
                )
                device_cur_net = self._cat_traffic_device_dev()

                if device_cur_net.source == "" or device_cur_net.source is None:
                    continue

                if self.traffic_init:
                    self.device_init_net = device_cur_net
                device_grow = self.get_net_from_begin(self.device_init_net, device_cur_net)
                collection_time = time.time()
                logger.debug(" collection time in traffic is : " + str(collection_time))
                net_row = [
                    collection_time,
                    TrafficUtils.byte2kb(device_grow.total),
                    TrafficUtils.byte2kb(device_grow.rx),
                    TrafficUtils.byte2kb(device_grow.tx),
                ]
                self.total_pck_net = 0
                for i in range(0, len(self.packages)):
                    pid = self.device.adb.get_pid_from_pck(self.packages[i])
                    pck_net_info = self._cat_traffic_pid_dev(pid)
                    if not pck_net_info.source:
                        logger.error(f"package net dev failed {self.packages[i]}:")
                        continue
                    if self.traffic_init:
                        self.pck_init_net_list.append(pck_net_info)
                        if i == len(self.packages) - 1:
                            self.traffic_init = False
                    pck_grow = self.get_net_from_begin(self.pck_init_net_list[i], pck_net_info)
                    self.total_pck_net = self.total_pck_net + pck_grow.wifi_total
                    net_row.extend(
                        [
                            self.packages[i],
                            pid,
                            TrafficUtils.byte2kb(pck_grow.rx),
                            TrafficUtils.byte2kb(pck_grow.tx),
                            TrafficUtils.byte2kb(pck_grow.total),
                        ]
                    )

                if len(self.packages) > 1:
                    net_row.append(TrafficUtils.byte2kb(self.total_pck_net))

                if self.traffic_queue:
                    self.traffic_queue.put(net_row)
                if not self.traffic_queue:  # 无上游消费者时直接写入本地 CSV。
                    net_row[0] = TimeUtils.formatTimeStamp(net_row[0])
                    try:
                        with open(traffic_file, "a+", encoding="utf-8") as f:
                            writer = csv.writer(f, lineterminator="\n")
                            writer.writerow(net_row)
                    except RuntimeError as e:
                        logger.error(e)
                logger.debug(net_row)
                after = time.time()
                time_consume = after - before
                logger.debug(" -----------traffic timeconsumed: " + str(time_consume))
                # 扣除命令执行耗时，使采样周期尽量接近配置间隔。
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
            except Exception:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                if self.traffic_queue:
                    self.traffic_queue.task_done()

    def get_traffic_init_data(self, traffic_snapshot):
        # 设备返回的是开机累计值，保存首轮快照才能计算本次采集增量。
        traffic_data_dic = {}
        traffic_data_dic["package"] = traffic_snapshot.packagename
        traffic_data_dic["total"] = traffic_snapshot.total_uid_bytes
        traffic_data_dic["total_packets"] = traffic_snapshot.total_uid_packets
        traffic_data_dic["rx"] = traffic_snapshot.rx_uid_bytes
        traffic_data_dic["rx_packets"] = traffic_snapshot.rx_uid_packets
        traffic_data_dic["tx"] = traffic_snapshot.tx_uid_bytes
        traffic_data_dic["tx_packets"] = traffic_snapshot.tx_uid_packets
        traffic_data_dic["fg"] = traffic_snapshot.fg_bytes
        traffic_data_dic["bg"] = traffic_snapshot.bg_bytes
        traffic_data_dic["lo"] = traffic_snapshot.lo_uid_bytes
        logger.debug(traffic_data_dic)
        return traffic_data_dic

    def get_data_from_threadstart(self, traffic_snapshot):
        # 从累计值中扣除本次采集基线，并把计数器回退保护为零。
        traffic_snapshot.total_uid_bytes = (
            traffic_snapshot.total_uid_bytes - self.traffic_init_dic["total"]
            if (traffic_snapshot.total_uid_bytes - self.traffic_init_dic["total"]) >= 0
            else 0
        )
        traffic_snapshot.total_uid_packets = (
            traffic_snapshot.total_uid_packets - self.traffic_init_dic["total_packets"]
            if (traffic_snapshot.total_uid_packets - self.traffic_init_dic["total_packets"]) >= 0
            else 0
        )
        traffic_snapshot.rx_uid_bytes = (
            traffic_snapshot.rx_uid_bytes - self.traffic_init_dic["rx"]
            if (traffic_snapshot.rx_uid_bytes - self.traffic_init_dic["rx"]) >= 0
            else 0
        )
        traffic_snapshot.rx_uid_packets = (
            traffic_snapshot.rx_uid_packets - self.traffic_init_dic["rx_packets"]
            if (traffic_snapshot.rx_uid_packets - self.traffic_init_dic["rx_packets"]) >= 0
            else 0
        )
        traffic_snapshot.tx_uid_bytes = (
            traffic_snapshot.tx_uid_bytes - self.traffic_init_dic["tx"]
            if (traffic_snapshot.tx_uid_bytes - self.traffic_init_dic["tx"]) >= 0
            else 0
        )
        traffic_snapshot.tx_uid_packets = (
            traffic_snapshot.tx_uid_packets - self.traffic_init_dic["tx_packets"]
            if (traffic_snapshot.tx_uid_packets - self.traffic_init_dic["tx_packets"]) >= 0
            else 0
        )
        traffic_snapshot.fg_bytes = (
            traffic_snapshot.fg_bytes - self.traffic_init_dic["fg"]
            if (traffic_snapshot.fg_bytes - self.traffic_init_dic["fg"]) >= 0
            else 0
        )
        traffic_snapshot.bg_bytes = (
            traffic_snapshot.bg_bytes - self.traffic_init_dic["bg"]
            if (traffic_snapshot.bg_bytes - self.traffic_init_dic["bg"]) >= 0
            else 0
        )
        traffic_snapshot.lo_uid_bytes = (
            traffic_snapshot.lo_uid_bytes - self.traffic_init_dic["lo"]
            if (traffic_snapshot.lo_uid_bytes - self.traffic_init_dic["lo"]) >= 0
            else 0
        )
        logger.debug(traffic_snapshot)
        return traffic_snapshot

    def get_net_from_begin(self, begin_net_info, current_net_info):
        # 计算设备或进程从本次采集开始后的网络增量。
        net_info = NetDevInfo("")
        net_info.total = current_net_info.total - begin_net_info.total
        net_info.rx = current_net_info.rx - begin_net_info.rx
        net_info.tx = current_net_info.tx - begin_net_info.tx
        return net_info

    def stop(self):
        logger.debug("INFO: TrafficCollecor  stop...")
        if self.collect_traffic_thread.is_alive():
            self._stop_event.set()
            self.collect_traffic_thread.join(timeout=1)
            self.collect_traffic_thread = None
            if self.traffic_queue:
                self.traffic_queue.task_done()


class TrafficMonitor:
    def __init__(self, device_id, packages, interval=1.0, timeout=10 * 60, traffic_queue=None):
        self.device = AndroidDevice(device_id)
        self.stop_event = threading.Event()
        self.packages = packages
        self.traffic_colloctor = TrafficCollecor(
            self.device, self.packages, interval, timeout, traffic_queue
        )

    def start(self, start_time):
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
        self.traffic_colloctor.start(start_time)
        logger.debug("INFO: TrafficMonitor has started...")

    def stop(self):
        self.traffic_colloctor.stop()
        logger.debug("INFO: TrafficMonitor has stopped...")

    def _get_traffic_collector(self):
        return self.traffic_colloctor

    def save(self):
        """保留旧 Monitor 接口；流量采集过程已经实时写入结果文件。"""
        pass


if __name__ == "__main__":
    monitor = TrafficMonitor("UYT5T18615007121", ["com.taobao.taobao"], 2)
    monitor.start(TimeUtils.getCurrentTime())
    time.sleep(60)
    monitor.stop()
