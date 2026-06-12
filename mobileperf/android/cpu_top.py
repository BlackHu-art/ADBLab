# -*- coding: utf-8 -*-
"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""
import csv
import os
import re
import os, sys
import threading
import time
import traceback

from datetime import datetime

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))

from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils, FileUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData


class DeviceCpuinfo(object):
    pass


class PckCpuinfo(object):
    '''
    瀛樺偍鏌愪釜鍖卌pu鐨勭浉鍏充俊鎭紝璁″垝瀛樺偍鐨勪俊鎭湁锛氬寘鍚嶏紝pid锛寀id锛岀粰瀹氬寘鐨刯iffies(浠庡紑鏈哄紑濮嬬畻)鏉ヨ嚜/proc/pid/stats
    璇ヨ繘绋嬬殑cpu鍗犳湁鐜囷紝鐜板湪鍙互閫氳繃top鑾峰彇杩樻槸鑷繁閫氳繃鍓嶅悗鐨刯iffies璁＄畻锛?
    鍒濇纭畾浣跨敤top 鐩存帴杩涜缁熻.娉ㄦ剰top涓殑鏁板€煎熀鏈笂鏄灛鏃跺€硷紝閲囨牱鐨勬暟鎹篃鏄潵鑷簬/proc/pid/stat(鍏蜂綋杩涚▼鐨刢pu%)
    '''
    #  1:cpu   2:user   3:nice  4:sys  5:idle     6:iow  7:irq    8:sirq   9:host
    #400%cpu  56%user   1%nice  46%sys 285%idle   0%iow  10%irq   2%sirq   0%host
    #User 0%, System 0%, IOW 0%, IRQ 0%

    RE_CPU = re.compile(r'User (\d+)\%\, System (\d+)\%\, IOW (\d+)\%\, IRQ (\d+)\%')
    RE_CPU_O = re.compile(r'(\d+)\%cpu\s+(\d+)\%user\s+(\d+)\%nice\s+(\d+)\%sys\s+(\d+)\%idle\s+(\d+)\%iow\s+(\d+)\%irq\s+(\d+)\%sirq\s+(\d+)\%host')

    def __init__(self, packages, source, sdkversion):
        '''
        :param packages: 搴旂敤鐨勫寘鍚?
        :param source: 鏁版嵁婧愶紝鏉ヨ嚜浜巃db shell top.
        '''
        self.source = source
        self.sdkversion = sdkversion
        self.datetime = ''
        self.packages = packages
        self.pid = 0
        self.uid = ''
        self.pck_cpu_rate = ''
        self.pck_pyc = ''
        self.uid_cpu_rate = ''
        #鍚屼竴涓簲鐢ㄦ湁鏃跺€欐湁澶氫釜杩涚▼,姣忎釜杩涚▼閮戒細鍑虹幇cpu鍗犳瘮杈冨ぇ鐨勬儏鍐碉紝涓轰簡缁熻鍑嗙‘锛岄拡瀵瑰杩涚▼鐨勬儏鍐碉紝鍚屼竴鏉op鍛戒护鏈€濂借繑鍥炲鏉¤褰曪紝浠ヤ究鏌ョ湅璇︽儏
        #椤哄簭鏄紱[datetime, packagename, pid, uid, pid cpu, uid cpu, pcy,uid cpu]
        self.package_list = []

        self.device_cpu_rate = ''  #鏁存満鐨刢pu浣跨敤鐜?
        self.system_rate = ""
        self.user_rate = ''
        self.nice_rate = ''
        self.idle_rate = ''
        self.iow_rate = ''
        self.irq_rate = ''
        self.total_pid_cpu = 0
        self._parse_cpu_usage()
        self._parse_package()
        # self.sum_procs_cpurate()

    def _parse_package(self):
        '''
        瑙ｆ瀽top鍛戒护涓殑鍖呯殑cpu淇℃伅
        :return:
        '''
        if self.packages == None or self.packages == "":
            logger.error("no process name input, please input")

        for package in self.packages:
            package_dic = {"package": package,
                           "pid": "",
                           "pid_cpu": ""}
            sp_lines = self.source.split('\n')
            for line in sp_lines:
                # logger.debug(line)
                if package in line:  #瑙ｆ瀽杩涚▼cpu淇℃伅
                    tmp = line.split()
                    self.pid = tmp[0]
                    target_pck = tmp[-1]  #浠庝腑瑙ｆ瀽鍑虹殑鏈€鍚庝竴涓€兼槸鍖呭悕
                    self.datetime = TimeUtils.getCurrentTime()
                    logger.debug("cpuinfos, _parse top target_pck is : " + str(target_pck) + " , self.pacakgename : " + package)
                    if package == target_pck:  #鍙粺璁″寘鍚嶅畬鍏ㄧ浉鍚岀殑杩涚▼
                        if int(self.pid) > 0:
                            logger.debug("cpuinfos, into _parse_pck packege is target package, pid is :" + str(self.pid))
                            # logger.debug("into _parse_pck packege is target package, pid is :" + str(self.pid))
                            cpu_index = self.get_cpucol_index()
                            uid_index = self.get_uidcol_index()
                            if (len(tmp) > cpu_index):
                                self.pck_cpu_rate = tmp[cpu_index]
                                # CPU% 9% 鏈夌殑鏍煎紡浼氭湁%
                                self.pck_cpu_rate = self.pck_cpu_rate.replace("%", "")
                            if (len(tmp) > uid_index):
                                self.uid = tmp[uid_index]
                            package_dic = {"package": package,
                                           "pid": self.pid,
                                           "pid_cpu": str(self.pck_cpu_rate),
                                           "uid": self.uid}
                            # self.package_list.append(package_dic)
                            # 灏唗op涓В鏋愬嚭鏉ョ殑淇℃伅淇濆瓨鍦ㄤ竴涓垪琛ㄤ腑锛屼綔涓轰竴鏉¤褰曟坊鍔犲湪package_list涓?
                            logger.debug("package: " + package + ", cpu_rate: " + str(self.pck_cpu_rate))
                            self.total_pid_cpu = self.total_pid_cpu + float(self.pck_cpu_rate)
                        break
            self.package_list.append(package_dic)
            logger.debug(package_dic)

    def _parse_cpu_usage(self):
        '''
        浠巘op涓В鏋愬嚭cpu鐨勪俊鎭?
        :return:
        '''
        if self.sdkversion < 26:  #android 8.0涔嬪墠鐨勭増鏈?
            match = self.RE_CPU.search(self.source)
            if (match):
                self.user_rate = match.group(1)
                self.system_rate = match.group(2)
                self.iow_rate = match.group(3)
                self.irq_rate = match.group(4)
                self.device_cpu_rate = int(self.user_rate) + int(self.system_rate)
                logger.debug("  cpuinfos,device system_rate: %s" % self.system_rate)
                logger.debug("  cpuinfos, device user_rate: %s" % self.user_rate)
                logger.debug("  cpuinfos, device device_cpu_rate: %s" % self.device_cpu_rate)
        else:  #8.0鍙婂叾浠ヤ笂鐨勭増鏈?turandot 27
            #  1:cpu   2:user   3:nice  4:sys  5:idle     6:iow  7:irq    8:sirq   9:host
            match = self.RE_CPU_O.search(self.source)
            if (match):
                self.user_rate = match.group(2)
                self.nice_rate = match.group(3)
                self.system_rate = match.group(4)
                self.idle_rate = match.group(5)
                self.iow_rate = match.group(6)
                self.irq_rate = match.group(7)
                self.device_cpu_rate = int(self.user_rate) + int(self.system_rate)
                logger.debug("8.0 or higher, user_rate: " + str(self.user_rate) + ", sys: " + str(self.system_rate) + ",device cpu: " + str(self.device_cpu_rate))
                logger.debug("idle_rate: %s" % self.idle_rate)

    def sum_procs_cpurate(self):
        '''
        鏈夋椂鍊欐垜浠渶瑕佺煡閬撴暣涓簲鐢ㄧ殑cpu鍗犳瘮鎯呭喌锛岀敱浜庢瘡涓簲鐢ㄤ腑鍙兘浼氬寘鍚涓繘绋嬶紝鎵€浠ラ渶瑕佸皢杩欎簺鍊肩疮鍔?
        绱姞灞炰簬鍚屼竴涓猆ID鐨勬墍鏈夎繘绋嬬殑cpu浣跨敤鐜?
        :return: 鎵€鏈夎繖浜涜繘绋媍pu%鐨勫拰
        '''
        summ = 0
        if self.source:
            sp_lines = self.source.split("\n")
            for line in sp_lines:
                if self.uid != "" and self.uid in line:  #鍏堣繃婊ゅ嚭鏈夌浉鍚寀id鐨勮
                    tmp = line.split()
                    cpu_index = self.get_cpucol_index()
                    summ = summ + int(tmp[cpu_index].replace("%", ""))
            self.uid_cpu_rate = str(summ) + "%"
            for i in range(len(self.package_list)):
                self.package_list[i].append(self.uid_cpu_rate)
                logger.debug("cpuinfos, sum_procs_cpurate , afer append uid cpu rate, the package list is : " + str(self.package_list))

    def get_cpucol_index(self):
        '''
        瀹為檯娴嬭瘯涓彂鐜颁笉鍚岀殑鏈哄瀷top鍛戒护涓殑cpu浣跨敤鐜囦笉涓€瀹氬湪绗笁鍒楋紝鎵€浠ラ渶瑕佽幏鍙栧埌杩欎釜鍊煎湪绗嚑鍒椼€?
        :return: cpu%鎵€鍦ㄧ殑鍒楁爣
        '''

        # return self.get_col_index(self.source, "CPU%", 2)
        return self.get_col_index(self.source, ["CPU]", "CPU%"], 2)

    def get_pcycol_index(self):
        '''
        :return: top涓璸yc鐨勫垪鏍?
        '''
        return self.get_col_index(self.source, ["PCY"], -1)

    def get_packagenamecol_index(self):
        '''
        :return: top涓殑packagename鐨勫垪鏍?
        '''
        # return self.get_col_index(self.source,"Name",-1)
        return self.get_col_index(self.source, ["ARGS"], -1)

    def get_vsscol_index(self):
        return self.get_col_index(self.source, ["VSS"], -1)

    def get_rss_col_index(self):
        return self.get_col_index(self.source, ["RSS"], -1)

    def get_uidcol_index(self):
        '''
        鐢变簬uid鐨勫垪鍚嶅湪涓嶅悓鏈哄櫒涓婁細鏈夊樊鍒紝杩欓噷鍗曠嫭鍖哄垎
        :return: adb shell top涓璾id鍒楃殑鍒楁爣
        '''
        if self.source:
            sp_lines = self.source.split("\n")
            for line in sp_lines:
                if 'UID' in line:
                    line_sp = line.split()
                    for key, item in enumerate(line_sp):
                        if item == "UID":
                            return key
                elif 'USER' in line:
                    line_sp = line.split()
                    for key, item in enumerate(line_sp):
                        if item == "USER":
                            return key
        return 8

    def get_col_index(self, s, col_name_list, default):
        '''
        杩斿洖top涓垪鏍囩殑閫氱敤鐨勬柟娉?
        :param s: 涓€鏉op鍛戒护鐨勫€?
        :param col_name: 鍒楀悕鍒楄〃 鍙兘浼氭湁涓嶅悓鏍煎紡
        :param default:榛樿杩斿洖鐨勫垪鏍?
        :return:
        '''
        s = s.split("\n")
        if s:
            for line in s:
                line = line.strip()
                for col_name in col_name_list:
                    if col_name in line:
                        line_sp = re.split(r"\[%|\s+", line)
                        for key, item in enumerate(line_sp):
                            if item == col_name:
                                logger.debug('=========== item == col_name: ' + col_name + " index : " + str(key))
                                return key
        return default


class CpuCollector(object):
    '''
    閫氳繃top鍛戒护鎼滈泦cpu淇℃伅鐨勪竴涓被
    '''

    def __init__(self, device, packages, interval=1, timeout=24 * 60 * 60):
        '''

        :param device: 鍏蜂綋鐨勮澶囧疄渚?
        :param packages: 搴旂敤鐨勫寘鍚嶅垪琛?
        :param interval: 鏁版嵁閲囬泦鐨勯鐜?
        :param timeout: 閲囬泦鐨勮秴鏃讹紝瓒呰繃杩欎釜鏃堕棿锛屼换鍔′細鍋滄閲囬泦,榛樿鏄?4涓皬鏃?
        '''
        self.device = device
        self.packages = packages
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.cpu_list = []
        self.sdkversion = self.get_sdkversion()
        # top鍙兘浼氭湁杩涚▼鍚嶆樉绀轰笉鍏ㄧ殑闂 鍔?b鍗冲彲
        self.top_cmd = 'top -b -n 1 -d %d' % self._interval
        ret = self.device.adb.run_shell_cmd(self.top_cmd)
        if ret and 'Invalid argument "-b"' in ret:
            logger.debug("top -b not support")
            self.top_cmd = 'top -n 1 -d %d' % self._interval
        logger.debug("sdk version : " + str(self.sdkversion))

    def get_sdkversion(self):
        sdk = self.device.adb.get_sdk_version()
        if sdk == None:
            sdk = 25
        return sdk

    def start(self, start_time):
        '''
        鍚姩涓€涓悳闆嗗櫒鏉ュ惎鍔ㄤ竴涓柊鐨勭嚎绋嬫悳闆哻pu淇℃伅
        :return:
        '''
        self.collect_package_cpu_thread = threading.Thread(target=self._collect_package_cpu_thread, args=(start_time,))
        self.collect_package_cpu_thread.start()
        logger.debug("INFO: CpuCollector start...")

    def stop(self):
        '''
        鍋滄cpu鐨勬悳闆嗗櫒
        :return:
        '''
        logger.debug("INFO: CpuCollector stop...")
        if (self.collect_package_cpu_thread.is_alive()):
            self._stop_event.set()
            self.collect_package_cpu_thread.join(timeout=2)
            self.collect_package_cpu_thread = None

        if hasattr(self, "_top_pipe"):
            if self._top_pipe.poll() == None:  #鏌ョ湅top杩涚▼鏄惁浠嶇劧瀛樺湪锛屽鏋滆繕瀛樺湪锛屽氨缁撴潫鎺?
                self._top_pipe.terminate()

    def _top_cpuinfo(self):
        self._top_pipe = self.device.adb.run_shell_cmd(self.top_cmd, sync=False)
        out = self._top_pipe.stdout.read()
        error = self._top_pipe.stderr.read()
        if error:
            logger.error("into cpuinfos error : " + str(error))
            return
        out = str(out, "utf-8")
        out.replace('\r', '')
        top_file = os.path.join(RuntimeData.package_save_path, 'top.txt')
        with open(top_file, "a+", encoding="utf-8") as writer:
            writer.write(TimeUtils.getCurrentTime() + " top info:\n")
            writer.write(out + "\n\n")
        #閬垮厤鏂囦欢杩囧ぇ锛岃秴杩?00M娓呯悊
        if FileUtils.get_FileSize(top_file) > 100:
            os.remove(top_file)
        return PckCpuinfo(self.packages, out, self.sdkversion)

    def get_max_freq(self):
        out = self.device.adb.run_shell_cmd("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq")
        out.replace('\r', '')
        max_freq_file = os.path.join(RuntimeData.package_save_path, 'scaling_max_freq.txt')
        with open(max_freq_file, "a+", encoding="utf-8") as writer:
            writer.write(TimeUtils.getCurrentTime() + " scaling_max_freq:\n")
            writer.write(out + "\n\n")

    def _collect_package_cpu_thread(self, start_time):
        '''
        鎸夌収鎸囧畾棰戠巼锛屽惊鐜悳闆哻pu鐨勪俊鎭?
        :return:
        '''
        end_time = time.time() + self._timeout
        cpu_title = ["datetime", "device_cpu_rate%", "user%", "system%", "idle%"]
        cpu_file = os.path.join(RuntimeData.package_save_path, 'cpuinfo.csv')
        for i in range(0, len(self.packages)):
            cpu_title.extend(["package", "pid", "pid_cpu%"])
        if len(self.packages) > 1:
            cpu_title.append("total_pid_cpu%")
        try:
            with open(cpu_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(cpu_title)
        except RuntimeError as e:
            logger.error(e)
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                logger.debug("---------------cpuinfos, into _collect_package_cpu_thread loop thread is : " + str(threading.current_thread().name))
                before = time.time()
                #涓轰簡cpu鍊肩殑鍑嗙‘鎬э紝灏嗛噰闆嗙殑鏃堕棿闂撮殧鏀惧湪top鍛戒护涓簡
                cpu_info = self._top_cpuinfo()
                after = time.time()
                time_consume = after - before
                logger.debug("  ============== time consume for cpu info : " + str(time_consume))
                if cpu_info == None or cpu_info.source == '' or not cpu_info.package_list:
                    logger.debug("cpuinfos, can't get cpu info, continue")
                    continue
                self.cpu_list.extend([TimeUtils.getCurrentTime(), str(cpu_info.device_cpu_rate), cpu_info.user_rate, cpu_info.system_rate, cpu_info.idle_rate])
                for i in range(0, len(self.packages)):
                    if len(cpu_info.package_list) == len(self.packages):
                        self.cpu_list.extend([cpu_info.package_list[i]["package"], cpu_info.package_list[i]["pid"], cpu_info.package_list[i]["pid_cpu"]])
                if len(self.packages) > 1:
                    self.cpu_list.append(cpu_info.total_pid_cpu)
                #鏍″噯鏃堕棿锛岀敱浜巘op鎵ц闇€瑕佽€楁椂锛岄渶瑕佸皢杩欎釜鎹熻€楀姞涓婂幓
                logger.debug("INFO: CpuMonitor save cpu_device_list: " + str(self.cpu_list))
                try:
                    with open(cpu_file, 'a+', encoding="utf-8") as df:
                        csv.writer(df, lineterminator='\n').writerow(self.cpu_list)
                        del self.cpu_list[:]
                except RuntimeError as e:
                    logger.error(e)

                # self.get_max_freq()
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception as e:
                logger.error("an exception hanpend in cpu thread , reason unkown!, e:")
                logger.error(e)
                s = traceback.format_exc()
                logger.debug(s)  #灏嗗爢鏍堜俊鎭墦鍗板埌log涓?
                if self.cpu_queue:
                    self.cpu_queue.task_done()
        logger.debug("stop event is set or timeout")


class CpuMonitor(object):
    '''
    cpu 鐩戞帶鍣?
    '''

    def __init__(self, device_id, packages, interval=5, timeout=24 * 60 * 60):
        self.device = AndroidDevice(device_id)
        self.packages = packages
        self.cpu_collector = CpuCollector(self.device, packages, interval, timeout)

    def start(self, start_time):
        '''
        鍚姩涓€涓猚pu鐩戞帶鍣紝鐩戞帶cpu淇℃伅
        :return:
        '''
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(os.path.abspath(os.path.join(os.getcwd(), "../..")), 'results', self.packages[0], start_time)
            if not os.path.exists(RuntimeData.package_save_path):
                os.makedirs(RuntimeData.package_save_path)
        self.start_time = start_time
        self.cpu_collector.start(start_time)
        logger.debug("INFO: CpuMonitor has started...")

    def stop(self):
        self.cpu_collector.stop()
        logger.debug("INFO: CpuMonitor has stopped...")

    def _get_cpu_collector(self):
        return self.cpu_collector

    def save(self):
        pass


if __name__ == "__main__":
    # RuntimeData.package_save_path = "/Users/look/Desktop/project/mobileperf-mac/results/com.yunos.tv.alitvasr/2019_03_25_22_07_57/"
    # monitor = CpuMonitor("O77DFAWSSGV4Z5AU", ["com.yunos.tv.alitvasr", "com.alibaba.ailabs.genie.contacts"], 5)
    # monitor = CpuMonitor("O77DFAWSSGV4Z5AU", ["com.yunos.tv.alitvasr"], 5)
    monitor = CpuMonitor("85I7UO4PFQCINJL7", ["com.yunos.tv.alitvasr"], 5)
    monitor.start(TimeUtils.getCurrentTimeUnderline())
    time.sleep(180)
    monitor.stop()
