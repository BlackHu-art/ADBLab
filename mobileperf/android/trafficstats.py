# -*- coding: utf-8 -*-
"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""
import csv
import os
import re
import threading

import time

import sys
import traceback

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData
import sys


class TrafficUtils(object):
    @staticmethod
    def getUID(device, pkg):
        """"""
        uid = None
        _cmd = 'dumpsys package %s' % pkg
        out = device.adb.run_shell_cmd(_cmd)
        lines = out.replace('\r', '').splitlines()
        logger.debug("line length: " + str(len(lines)))
        if len(lines) > 0:
            for line in lines:
                if "Unable to find package:" in line:
                    logger.error(" trafficstat: Unable to find package : " + pkg)
                    continue
            adb_result = re.findall(u'userId=(\d+)', out)
            if len(adb_result) > 0:
                uid = adb_result[0]
                logger.debug("getUid for pck: " + pkg + ", UID: " + uid)
        else:
            logger.error(" trafficstat: Unable to find package : " + pkg)
        return uid

    @staticmethod
    def byte2kb(value):
        return round(value / 1024.0, 2)

    # def write


'''
鐜板湪鍙互鑾峰彇鍒版瘡涓猽id鐨勬暣浣撶殑娴侀噺,鍖呮嫭涓婅鍜屼笅琛岀殑娴侀噺锛岃嚦浜庡叿浣撶殑绉诲姩娴侀噺杩樻槸wifi鐨勬祦閲忕敱浜庝笉鍚岀殑鏈哄瀷锛岀綉缁滄帴鍙ｇ殑鍚嶇О涓嶇粺涓€锛屾墍浠ヨ幏鍙栨湁闂锛宎ndroid绯荤粺鏈夊湪
NetworkStatsService 涓鐣欎竴涓帴鍙etMobileIfaces锛岃繑鍥炰簡鏁版嵁娴侀噺鐨勬墍鏈夌綉缁滄帴鍙ｏ紝鍏蜂綋瀹炵幇鏄敞鍐屼竴涓瀵熻€咃紝鍙鍏朵粬鐨勫湴鏂规敞鍐屼簡鏁版嵁鐨勬帴鍙ｏ紝灏遍€氱煡绯荤粺鍚戣繖涓猰obile涓?
娣诲姞杩欎釜鏁版嵁绫诲瀷锛屼粠鑰屽彲浠ヨ幏鍙栧埌鏁版嵁娴侀噺鐨勬墍鏈夌被鍨嬶紝鐩墠adb鐨勬柟娉曟病鏈夋壘鍒板姙娉曞彲浠ュ仛鍖哄垎锛屽彲浠ュ湪浠ュ悗鐨刯ava鐨剆dk浠ｇ爜涓疄鐜皐ifi鍜屾暟鎹殑鍖哄垎鐨勪唬鐮侊紝鍚庣画TODO
update:缃戠粶鎺ュ彛鍙互浠巆at /proc/net/xt_qtaguid/iface_stat灏辨槸涓嶇煡閬搘ifi鍜屾暟鎹殑鎬庝箞鍖哄垎锛屽悗闈ODO
'''


class TrafficSnapshot(object):
    '''
    褰撳墠浠?proc/net/xt_qtaguid/stats鑾峰彇鐨勬槸浠庢墜鏈哄紑鏈哄紑濮嬬殑娴侀噺锛屽綋鎵嬫満閲嶅惎鍚庯紝鎵€鏈夌殑鏁版嵁灏嗚娓呴浂锛屾墍浠ュ彲鑳藉緱鑰冭檻鏁版嵁鐨勬寔涔呭寲
    '''

    def __init__(self, source, packagename, uid):
        self.source = source
        self.uid = uid
        self.packagename = packagename
        self.rx_uid_bytes = 0  #/proc/net/xt_qtaguid/iface_stat绗叚涓紝琛ㄧず涓嬭鏁版嵁
        self.rx_uid_packets = 0  #绗竷涓紝涓婅鐨勫寘涓暟
        self.tx_uid_bytes = 0  #绗叓涓?
        self.tx_uid_packets = 0  #绗節涓?
        self.total_uid_bytes = 0  #璇id浠庡紑鏈哄埌鐜板湪鐨勬€绘祦閲忥紝鍖呭惈鏈湴娴侀噺,鐩墠浣跨敤鐨刲ong锛屽彲鑳戒細婧㈠嚭锛岄渶瑕佷紭鍖?
        self.total_uid_packets = 0
        self.lo_uid_bytes = 0  #璇id鐨勬湰鍦版祦閲?
        self.bg_bytes = 0  #杩欎釜uid鐨勫悗鍙版祦閲?
        self.fg_bytes = 0  #杩欎釜uid浠庡紑鏈哄埌鐜板湪寮€濮嬬殑鍓嶅彴娴侀噺
        self._parse()

    def _parse(self):
        sp_lines = self.source.split('\n')
        for line in sp_lines:
            if self.uid and self.uid in line:
                # logger.debug("     target uid : "+str(self.uid))
                tart_list = line.split()
                tag = tart_list[2]
                # logger.debug("         tag is锛?" +tag)
                if tag == '0x0':  #tag鍗砤cct_tag_hex杩欎竴鍒楋紝榛樿鏄?锛岃〃绀轰笌杩欎釜uid鍏宠仈鐨勬祦閲忥紝鏈夋椂鍊欑敤鎴烽渶瑕佸湪鑷繁鐨剈id鍐呮坊鍔犱竴涓叾浠?
                    # tag琛ㄧず杩欎釜妯″潡涓殑瀛愭ā鍧楃殑娴侀噺锛屽氨鍙互閫氳繃setThreadTag
                    # logger.debug("        tart_list: " + str(tart_list))
                    self.rx_uid_bytes += int(tart_list[5])  #涓嶅尯鍒嗙綉缁滅殑绫诲瀷锛岀洿鎺ョ畻鎬诲拰,wifi鍜宮obile, lo鏁版嵁鐨勬€诲拰
                    # logger.debug(self.rx_uid_bytes)
                    self.rx_uid_packets += int(tart_list[6])
                    self.tx_uid_bytes += int(tart_list[7])
                    self.tx_uid_packets += int(tart_list[8])
                    self.total_uid_bytes = self.tx_uid_bytes + self.rx_uid_bytes
                    self.total_uid_packets = self.tx_uid_packets + self.rx_uid_packets
                    if (tart_list[1] == 'lo'):  #瀵瑰簲鐫€iface杩欏垪锛岃〃绀烘湰鍦版祦閲?
                        self.lo_uid_bytes += int(tart_list[5]) + int(tart_list[7])
                        # logger.debug("       lo_uid_bytes: " + str(self.lo_uid_bytes))
                    if (int(tart_list[4]) == 0):  #缁熻鍚庡彴娴侀噺
                        self.bg_bytes += int(tart_list[5]) + int(tart_list[7])
                        # logger.debug("       backgroud data 锛?" +str(self.bg_bytes))
                    elif (int(tart_list[4]) == 1):  #缁熻鍓嶅彴娴侀噺
                        self.fg_bytes += int(tart_list[5]) + int(tart_list[7])
                        # logger.debug("        fg data: " +str(self.fg_bytes))

        logger.debug(" total uid  bytes : " + str(self.total_uid_bytes))

    def __repr__(self):
        return "TrafficSnapshot, " + "package: " + str(self.packagename) + " uid bytes: " + str(self.total_uid_bytes) + " uid pcket byte: " + str(self.total_uid_packets)


class NetDevInfo(object):
    '''
    瑙ｆ瀽proc/net/dev 缁撴灉 瑙ｆ瀽/proc/%d/net/dev 缁撴灉 杈撳嚭鏍煎紡涓€鏍?
    绀轰緥缁撴灉
    Inter-|   Receive                                                |  Transmit
         face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
        rmnet4:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun03:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_r_ims01:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun02:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        dummy0:       0       0    0    0    0     0          0         0     1610      23    0    0    0     0       0          0
        rmnet2:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun11:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_ims00:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun10:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_emc0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun13:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun00:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun04:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet5:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
         wlan0: 1241518561  840807    0    0    0     0          0         7  7225770   73525    0    6    0     0       0          0
        rmnet_r_ims00:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet3:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun01:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
          sit0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun14:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        ip_vti0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        ip6tnl0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet1:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        ip6_vti0:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_r_ims11:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_r_ims10:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet6:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
        rmnet_tun12:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
            lo: 3796620     292    0    0    0     0          0         0  3796620     292    0    0    0     0       0          0
        rmnet_ims10:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0

    '''

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
        sp_lines = self.source.split('\n')
        for line in sp_lines:
            # wlan0: 1241508864 840739 0 0 0 0 0 7 7149177 73416 0 6 0 0 0 0
            # 鑾峰彇鍏朵腑 鎺ュ彈娴侀噺1241508864 鍙戦€佹祦閲?149177
            if "wlan0:" in line:
                items = line.split()
                self.wifi_rx = int(items[1])
                self.wifi_tx = int(items[9])
                self.wifi_total = self.wifi_rx + self.wifi_tx
                logger.debug("wifi_rx : " + items[1] + " wifi_tx : " + items[9] + " total wifi:" + str(self.wifi_total))
                # 绉诲姩 3 4 5G 娴侀噺
                # rmnet0: 362133448 298441 0 0 0 0 0 0 10641124 91012 0 0 0 0 0 0
            if "rmnet0:" in line:
                items = line.split()
                self.mobile_rx = int(items[1])
                self.mobile_tx = int(items[9])
                self.mobile_total = self.wifi_rx + self.wifi_tx
                logger.debug("mobile_rx : " + items[1] + " mobile_tx : " + items[9] + " total mobile:" + str(self.mobile_total))
            self.rx = self.wifi_rx + self.mobile_rx
            self.tx = self.wifi_tx + self.mobile_tx
            self.total = self.wifi_total + self.mobile_total

    def __repr__(self):
        return "NetDevInfo "


class TrafficCollecor(object):
    def __init__(self, device, packages, interval=1.0, timeout=24 * 60 * 60, traffic_queue=None):
        self.device = device
        self.packages = packages
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.traffic_queue = traffic_queue
        self.sdk_version = self.device.adb.get_sdk_version()

        #鏄惁棣栨鍚姩锛岄粯璁ゆ槸
        self.traffic_init = True
        self.traffic_init_dic = {}

    def start(self, start_time):
        logger.debug("INFO: TrafficCollecor  start...")
        self.collect_traffic_thread = threading.Thread(target=self._collect_traffic_thread, args=(start_time,))
        self.collect_traffic_thread.start()

    def _cat_traffic_data(self, packagename, uid):
        out = self.device.adb.run_shell_cmd("cat /proc/net/xt_qtaguid/stats")
        out.replace('\r', '')
        return TrafficSnapshot(out, packagename, uid)

    def _cat_traffic_device_dev(self):
        out = self.device.adb.run_shell_cmd("cat /proc/net/dev")
        # traffic_file = os.path.join(RuntimeData.package_save_path, 'traffic.txt')
        # with open(traffic_file, "a+", encoding="utf-8") as writer:
        #     writer.write(TimeUtils.getCurrentTime() + " cat /proc/net/dev info:\n")
        #     writer.write(out + "\n\n")
        out.replace('\r', '')
        return NetDevInfo(out)

    def _cat_traffic_pid_dev(self, pid):
        out = self.device.adb.run_shell_cmd("cat /proc/%d/net/dev" % pid)
        # traffic_file = os.path.join(RuntimeData.package_save_path, 'traffic.txt')
        # with open(traffic_file, "a+", encoding="utf-8") as writer:
        #     writer.write(TimeUtils.getCurrentTime() + " cat /proc/"+str(pid)+"/net/dev info:\n")
        #     writer.write(out + "\n\n")
        out.replace('\r', '')
        return NetDevInfo(out)

    def _collect_traffic_thread(self, start_time):
        # < android10 鐢?proc/net/xt_qtaguid/stats 鑾峰彇uid 娴侀噺锛孉ndroid10 鎵句笉鍒拌鏂囦欢
        if self.sdk_version < 29:
            self.get_traffic_with_stats()
        else:
            # android 10 鐢?/proc/net/dev  /proc/pid/net/dev 鑾峰彇鏁存満 pid wifi娴侀噺
            self.get_traffic_with_dev()

    def get_traffic_with_stats(self):
        end_time = time.time() + self._timeout
        uid = TrafficUtils.getUID(self.device, self.packages[0])
        traffic_list_title = (
            "datetime", "packagename", "uid", "uid_total(KB)", "uid_total_packets", "rx(KB)", "rx_packets", "tx(KB)",
            "tx_packets", "fg(KB)", "bg(KB)", "lo(KB)")
        traffic_file = os.path.join(RuntimeData.package_save_path, 'traffics_uid.csv')
        try:
            with open(traffic_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(traffic_list_title)
                if self.traffic_queue:
                    traffic_file_dic = {'traffic_file': traffic_file}
                    self.traffic_queue.put(traffic_file_dic)
        except RuntimeError as e:
            logger.error(e)

        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug("----------------- into _collect_traffic_thread loop thread is : " + str(
                    threading.current_thread().name) + ", current uid is : " + str(uid))
                traffic_snapshot = self._cat_traffic_data(self.packages[0], uid)

                if traffic_snapshot.source == '' or traffic_snapshot.source == None:
                    continue  # 鑾峰彇涓嶅埌鍊肩殑鏃跺€欙紝鐩存帴涓嶆墽琛屼笅闈㈢殑浠ｇ爜浜嗭紝缂轰竴涓?
                    # retry_count = retry_count - 1
                    # if retry_count <= 0:
                    #     logger.debug("traffic, can't get traffic info, try six times, break...")
                    #     break

                if self.traffic_init:
                    self.traffic_init_dic = self.get_traffic_init_data(traffic_snapshot)
                    self.traffic_init = False
                traffic_snapshot = self.get_data_from_threadstart(traffic_snapshot)

                collection_time = time.time()
                logger.debug(" collection time in traffic is : " + str(collection_time))
                traffic_list_temp = [collection_time, traffic_snapshot.packagename, traffic_snapshot.uid,
                                     TrafficUtils.byte2kb(traffic_snapshot.total_uid_bytes),
                                     traffic_snapshot.total_uid_packets,
                                     TrafficUtils.byte2kb(traffic_snapshot.rx_uid_bytes),
                                     traffic_snapshot.rx_uid_packets,
                                     TrafficUtils.byte2kb(traffic_snapshot.tx_uid_bytes),
                                     traffic_snapshot.tx_uid_packets, TrafficUtils.byte2kb(traffic_snapshot.fg_bytes),
                                     TrafficUtils.byte2kb(traffic_snapshot.bg_bytes),
                                     TrafficUtils.byte2kb(traffic_snapshot.lo_uid_bytes)]
                logger.debug(traffic_list_temp)
                if self.traffic_queue:
                    self.traffic_queue.put(traffic_list_temp)

                if not self.traffic_queue:  # 涓轰簡鏈湴鍗曚釜鏂囦欢鍗曠嫭杩愯
                    traffic_list_temp[0] = TimeUtils.formatTimeStamp(traffic_list_temp[0])
                    try:
                        with open(traffic_file, 'a+', encoding="utf-8") as f:
                            writer = csv.writer(f, lineterminator='\n')
                            writer.writerow(traffic_list_temp)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                logger.debug(" -----------traffic timeconsumed: " + str(time_consume))
                # 鏍″噯鏃堕棿锛岀敱浜庢墽琛屽懡浠よ闇€瑕佽€楁椂锛岄渶瑕佸皢杩欎釜鎹熻€楀姞涓婂幓
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
            except Exception as e:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                if self.traffic_queue:
                    self.traffic_queue.task_done()

    def get_traffic_with_dev(self):
        end_time = time.time() + self._timeout
        traffic_title = ["datetime", "device_total(KB)", "device_receive(KB)", "device_transport(KB)"]
        traffic_file = os.path.join(RuntimeData.package_save_path, 'traffic.csv')
        for i in range(0, len(self.packages)):
            traffic_title.extend(["package", "pid", "pid_rx(KB)", "pid_tx(KB)", "pid_total(KB)"])
        if len(self.packages) > 1:
            traffic_title.append("total_proc_traffic(kB)")
        try:
            with open(traffic_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(traffic_title)
        except RuntimeError as e:
            logger.error(e)
        self.device_init_net = None
        self.pck_init_net_list = []
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug("--------- into _collect_traffic_thread loop thread is : " + str(threading.current_thread().name))
                device_cur_net = self._cat_traffic_device_dev()

                if device_cur_net.source == '' or device_cur_net.source == None:
                    continue

                if self.traffic_init:
                    self.device_init_net = device_cur_net
                    # self.traffic_init = False
                device_grow = self.get_net_from_begin(self.device_init_net, device_cur_net)
                collection_time = time.time()
                logger.debug(" collection time in traffic is : " + str(collection_time))
                net_row = [collection_time, TrafficUtils.byte2kb(device_grow.total),
                           TrafficUtils.byte2kb(device_grow.rx),
                           TrafficUtils.byte2kb(device_grow.tx)]
                self.total_pck_net = 0
                for i in range(0, len(self.packages)):
                    pid = self.device.adb.get_pid_from_pck(self.packages[i])
                    pck_net_info = self._cat_traffic_pid_dev(pid)
                    if not pck_net_info.source:
                        logger.error("package net dev failed %s:" % self.packages[i])
                        continue
                    if self.traffic_init:
                        self.pck_init_net_list.append(pck_net_info)
                        if i == len(self.packages) - 1:
                            self.traffic_init = False
                    pck_grow = self.get_net_from_begin(self.pck_init_net_list[i], pck_net_info)
                    self.total_pck_net = self.total_pck_net + pck_grow.wifi_total
                    net_row.extend([self.packages[i], pid, TrafficUtils.byte2kb(pck_grow.rx),
                                    TrafficUtils.byte2kb(pck_grow.tx), TrafficUtils.byte2kb(pck_grow.total)])

                if len(self.packages) > 1:
                    net_row.append(TrafficUtils.byte2kb(self.total_pck_net))

                if self.traffic_queue:
                    self.traffic_queue.put(net_row)
                if not self.traffic_queue:  # 涓轰簡鏈湴鍗曚釜鏂囦欢鍗曠嫭杩愯
                    net_row[0] = TimeUtils.formatTimeStamp(net_row[0])
                    try:
                        with open(traffic_file, 'a+', encoding="utf-8") as f:
                            writer = csv.writer(f, lineterminator='\n')
                            writer.writerow(net_row)
                    except RuntimeError as e:
                        logger.error(e)
                logger.debug(net_row)
                after = time.time()
                time_consume = after - before
                logger.debug(" -----------traffic timeconsumed: " + str(time_consume))
                # 鏍″噯鏃堕棿锛岀敱浜庢墽琛屽懡浠よ闇€瑕佽€楁椂锛岄渶瑕佸皢杩欎釜鎹熻€楀姞涓婂幓
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except RuntimeError as e:
                logger.error(" trafficstats RuntimeError ")
                logger.error(e)
            except Exception as e:
                logger.error("an exception hanpend in traffic thread , reason unkown! e: ")
                s = traceback.format_exc()
                logger.debug(s)
                if self.traffic_queue:
                    self.traffic_queue.task_done()

    def get_traffic_init_data(self, traffic_snapshot):
        #灏嗛娆″惎鍔ㄧ殑娴侀噺鐨勭浉鍏崇殑鏁版嵁瀛樻斁鍦ㄥ瓧鍏镐腑锛屼互渚垮皢娴侀噺鐨勮捣濮嬬偣瀹氫綅杩欎釜绾?
        # 绋嬪惎鍔ㄧ殑鏃跺€欙紙鎴戜滑鐜板湪浠庢墜鏈轰腑鎶撳嚭鏉ョ殑鏁版嵁鏄粠鎵嬫満寮€鏈轰綔涓鸿捣濮嬬偣鏉ョ畻鐨勶級
        traffic_data_dic = {}
        # if self.traffic_init:#
        traffic_data_dic['package'] = traffic_snapshot.packagename
        traffic_data_dic['total'] = traffic_snapshot.total_uid_bytes
        traffic_data_dic['total_packets'] = traffic_snapshot.total_uid_packets
        traffic_data_dic['rx'] = traffic_snapshot.rx_uid_bytes
        traffic_data_dic['rx_packets'] = traffic_snapshot.rx_uid_packets
        traffic_data_dic['tx'] = traffic_snapshot.tx_uid_bytes
        traffic_data_dic['tx_packets'] = traffic_snapshot.tx_uid_packets
        traffic_data_dic['fg'] = traffic_snapshot.fg_bytes
        traffic_data_dic['bg'] = traffic_snapshot.bg_bytes
        traffic_data_dic['lo'] = traffic_snapshot.lo_uid_bytes
        logger.debug(traffic_data_dic)
        return traffic_data_dic

    def get_data_from_threadstart(self, traffic_snapshot):
        # 鑾峰彇浠庡綋鍓嶇嚎绋嬪紑濮嬬殑娴侀噺鍊?
        traffic_snapshot.total_uid_bytes = traffic_snapshot.total_uid_bytes - self.traffic_init_dic['total'] if (traffic_snapshot.total_uid_bytes - self.traffic_init_dic['total']) >= 0 else 0
        traffic_snapshot.total_uid_packets = traffic_snapshot.total_uid_packets - self.traffic_init_dic['total_packets'] if (traffic_snapshot.total_uid_packets - self.traffic_init_dic[
            'total_packets']) >= 0 else 0
        traffic_snapshot.rx_uid_bytes = traffic_snapshot.rx_uid_bytes - self.traffic_init_dic['rx'] if (traffic_snapshot.rx_uid_bytes - self.traffic_init_dic['rx']) >= 0 else 0
        traffic_snapshot.rx_uid_packets = traffic_snapshot.rx_uid_packets - self.traffic_init_dic['rx_packets'] if (traffic_snapshot.rx_uid_packets - self.traffic_init_dic['rx_packets']) >= 0 else 0
        traffic_snapshot.tx_uid_bytes = traffic_snapshot.tx_uid_bytes - self.traffic_init_dic['tx'] if (traffic_snapshot.tx_uid_bytes - self.traffic_init_dic['tx']) >= 0 else 0
        traffic_snapshot.tx_uid_packets = traffic_snapshot.tx_uid_packets - self.traffic_init_dic['tx_packets'] if (traffic_snapshot.tx_uid_packets - self.traffic_init_dic['tx_packets']) >= 0 else 0
        traffic_snapshot.fg_bytes = traffic_snapshot.fg_bytes - self.traffic_init_dic['fg'] if (traffic_snapshot.fg_bytes - self.traffic_init_dic['fg']) >= 0 else 0
        traffic_snapshot.bg_bytes = traffic_snapshot.bg_bytes - self.traffic_init_dic['bg'] if (traffic_snapshot.bg_bytes - self.traffic_init_dic['bg']) >= 0 else 0
        traffic_snapshot.lo_uid_bytes = traffic_snapshot.lo_uid_bytes - self.traffic_init_dic['lo'] if (traffic_snapshot.lo_uid_bytes - self.traffic_init_dic['lo']) >= 0 else 0
        logger.debug(traffic_snapshot)
        return traffic_snapshot

    def get_net_from_begin(self, begin_net_info, current_net_info):
        # 鑾峰彇浠庡綋鍓嶅紑濮嬬殑娴侀噺澧炲€?
        net_info = NetDevInfo("")
        net_info.total = current_net_info.total - begin_net_info.total
        net_info.rx = current_net_info.rx - begin_net_info.rx
        net_info.tx = current_net_info.tx - begin_net_info.tx
        return net_info

    def stop(self):
        logger.debug("INFO: TrafficCollecor  stop...")
        if (self.collect_traffic_thread.is_alive()):
            self._stop_event.set()
            self.collect_traffic_thread.join(timeout=1)
            self.collect_traffic_thread = None
            if self.traffic_queue:
                self.traffic_queue.task_done()


class TrafficMonitor(object):
    def __init__(self, device_id, packages, interval=1.0, timeout=10 * 60, traffic_queue=None):
        self.device = AndroidDevice(device_id)
        self.stop_event = threading.Event()
        self.packages = packages
        self.traffic_colloctor = TrafficCollecor(self.device, self.packages, interval, timeout, traffic_queue)

    def start(self, start_time):
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(os.path.abspath(os.path.join(os.getcwd(), "../..")), 'results', self.packages[0], start_time)
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
        '''
        榛樿淇濆瓨锛屼繚瀛樺湪褰撳墠鐩綍鐨剅esults/TrafficInfos鏂囦欢澶逛笅
        :return:
        '''
        pass


if __name__ == "__main__":
    monitor = TrafficMonitor("UYT5T18615007121", ["com.taobao.taobao"], 2)
    monitor.start(TimeUtils.getCurrentTime())
    time.sleep(60)
    monitor.stop()
