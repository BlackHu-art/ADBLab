"""采集应用 UID 或设备网络流量，无法可靠归属的进程指标保留为空。"""

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
    ``wlan0: <rx_bytes> ... <tx_bytes> ...``。只汇总明确支持的 Wi-Fi 与蜂窝
    接口族；回环、VPN、叠加接口和未知接口不纳入，避免同一流量重复统计。
    ``available`` 区分有效零流量与缺失或不完整的受支持接口统计。
    """

    _WIFI_INTERFACE = re.compile(r"wlan[0-9]+")
    _MOBILE_INTERFACE = re.compile(r"rmnet(?:_data)?[0-9]+")

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
        self.available = False
        self.interfaces = {}
        self._parse()

    def _parse(self):
        complete = True
        for line in self.source.splitlines():
            interface, separator, counters = line.partition(":")
            if not separator:
                continue
            interface = interface.strip()
            is_wifi = self._WIFI_INTERFACE.fullmatch(interface) is not None
            if not is_wifi and self._MOBILE_INTERFACE.fullmatch(interface) is None:
                continue
            fields = counters.split()
            try:
                rx, tx = int(fields[0]), int(fields[8])
            except (IndexError, ValueError):
                complete = False
                continue
            if rx < 0 or tx < 0:
                complete = False
                continue
            self.available = True
            self.interfaces[interface] = (rx, tx)
            if is_wifi:
                self.wifi_rx += rx
                self.wifi_tx += tx
            else:
                self.mobile_rx += rx
                self.mobile_tx += tx
        self.wifi_total = self.wifi_rx + self.wifi_tx
        self.mobile_total = self.mobile_rx + self.mobile_tx
        self.rx = self.wifi_rx + self.mobile_rx
        self.tx = self.wifi_tx + self.mobile_tx
        self.total = self.rx + self.tx
        # 设备总量要求所有受支持接口完整，部分统计不能成为后续累计增量的基线。
        self.available = self.available and complete

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
        out = out.replace("\r", "")
        return TrafficSnapshot(out, packagename, uid)

    def _cat_traffic_device_dev(self):
        """读取受支持接口的设备快照；非空但无法解析时按失败样本处理。"""
        out = self.device.adb.run_shell_cmd("cat /proc/net/dev")
        out = out.replace("\r", "")
        snapshot = NetDevInfo(out)
        if out and not snapshot.available:
            raise RuntimeError(
                "Device traffic unavailable: missing or incomplete interface counters"
            )
        return snapshot

    def _collect_traffic_thread(self, start_time):
        # Android 10 之前从 /proc/net/xt_qtaguid/stats 读取 UID 流量。
        if self.sdk_version < 29:
            self.get_traffic_with_stats()
        else:
            # Android 10 起只从 /proc/net/dev 读取设备流量，进程流量标记为不可用。
            self.get_traffic_with_dev()

    def _wait_for_next_sample(self, delay, end_time):
        """失败和慢命令也至少短暂等待，并允许停止信号立即打断。"""
        remaining = max(0, end_time - time.time())
        if remaining:
            self._stop_event.wait(min(max(0.01, delay), remaining))

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
                    self._wait_for_next_sample(self._interval, end_time)
                    continue

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
                self._wait_for_next_sample(delta_inter, end_time)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
                self._wait_for_next_sample(self._interval, end_time)
            except Exception:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                self._wait_for_next_sample(self._interval, end_time)

    def get_traffic_with_dev(self):
        """采集设备流量；保留 CSV 进程列，但无法可靠归属的字节数写空值。"""
        end_time = time.time() + self._timeout
        self.traffic_init = True
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
        device_grow = NetDevInfo("")
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug(
                    "--------- into _collect_traffic_thread loop thread is : "
                    + str(threading.current_thread().name)
                )
                try:
                    device_cur_net = self._cat_traffic_device_dev()
                except Exception:
                    # 失联或不完整快照使接口连续性未知，恢复后先重建基线。
                    self.device_init_net = None
                    raise

                if device_cur_net.source == "" or device_cur_net.source is None:
                    self.device_init_net = None
                    self._wait_for_next_sample(self._interval, end_time)
                    continue

                if self.device_init_net is not None:
                    increment = self.get_net_from_begin(self.device_init_net, device_cur_net)
                    device_grow.rx += increment.rx
                    device_grow.tx += increment.tx
                    device_grow.total = device_grow.rx + device_grow.tx
                self.device_init_net = device_cur_net
                collection_time = time.time()
                logger.debug(" collection time in traffic is : " + str(collection_time))
                net_row = [
                    collection_time,
                    TrafficUtils.byte2kb(device_grow.total),
                    TrafficUtils.byte2kb(device_grow.rx),
                    TrafficUtils.byte2kb(device_grow.tx),
                ]
                for package in self.packages:
                    pid = self.device.adb.get_pid_from_pck(package)
                    if pid is None:
                        logger.error(f"package pid not found {package}:")
                    # /proc/<pid>/net/dev 属于网络命名空间，不能作为该进程的流量。
                    net_row.extend([package, pid if pid is not None else "", "", "", ""])

                if len(self.packages) > 1:
                    net_row.append("")

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
                self._wait_for_next_sample(delta_inter, end_time)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
                self._wait_for_next_sample(self._interval, end_time)
            except Exception:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                self._wait_for_next_sample(self._interval, end_time)

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
        """只累计连续存在且收发计数均未回退的接口；新接口或重置只建立基线。"""
        net_info = NetDevInfo("")
        for interface, (rx, tx) in current_net_info.interfaces.items():
            previous = begin_net_info.interfaces.get(interface)
            if previous is None:
                continue
            old_rx, old_tx = previous
            if rx < old_rx or tx < old_tx:
                continue
            net_info.rx += rx - old_rx
            net_info.tx += tx - old_tx
        net_info.total = net_info.rx + net_info.tx
        return net_info

    def stop(self):
        logger.debug("INFO: TrafficCollecor  stop...")
        if self.collect_traffic_thread.is_alive():
            self._stop_event.set()
            self.collect_traffic_thread.join(timeout=1)
            self.collect_traffic_thread = None


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
