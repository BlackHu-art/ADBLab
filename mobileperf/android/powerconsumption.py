# -*- coding: utf-8 -*-
"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
 杩欎釜绫绘悳闆嗙殑鏄墜鏈烘暣鏈虹殑鐢垫睜鏂归潰鐨勪俊鎭紝鍖呮嫭鐢垫祦锛岀數閲忥紝鐢靛帇锛岀數姹犳俯搴︼紝鍏呯數鎯呭喌绛?

"""
import csv
import os
import re
import sys
import threading

import time
import traceback

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils
from mobileperf.common.utils import transfer_temp
from mobileperf.common.utils import mV2V
from mobileperf.common.utils import uA2mA
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData


class DevicePowerInfo(object):
    RE_BATTERY = re.compile(r'level: (\d+) voltage: (\d+) temp: (\d+)')
    RE_CURRENT = re.compile(r'current now: (\S?\d+)')

    def __init__(self, source=None):
        '''
        :param source: dumpsys batteryproperties
        :param device:
        '''
        self.source = source
        self.level = 0  #鐢垫睜鐨勭數閲忎竴鑸互100涓烘€诲埢搴?
        self.voltage = 0  #鐢靛帇
        self.temp = 0  #娓╁害
        self.current = 0  #鐢垫祦,杩欎釜鐢垫祦鍊兼潵鑷簬璁惧鐨勫簳灞備笂鎶ワ紝鍑嗙‘鎬у彇鍐充簬鍏蜂綋鐨勮澶囷紝鍙互浣滀负鍙傝€?
        self._parse()

    def _parse(self):
        # logger.debug("into _parse")
        if self.source:
            match = self.RE_BATTERY.search(self.source)
            if (match):
                self.level = match.group(1)
                self.voltage = match.group(2)
                self.temp = match.group(3)
                # logger.debug("into parse level锛?"+str(self.level) + ", voltage: " + str(self.voltage) + ", temp: " + str(self.temp))

            match = self.RE_CURRENT.search(self.source)
            if (match):
                self.current = match.group(1)
                # logger.debug("into parse current: " + str(self.current))

    def __repr__(self):
        return "DevicePowerInfo, " + "level:" + str(self.level) + ", voltage:" + str(self.voltage) + ", temperature:" + str(self.temp) + ", current:" + str(self.current)


class PowerCollector(object):
    def __init__(self, device, interval=1.0, timeout=24 * 60 * 60, power_queue=None, ):
        self.device = device
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.power_queue = power_queue

    def start(self, start_time):
        logger.debug("INFO: PowerCollector  start...")
        self.collect_power_thread = threading.Thread(target=self._collect_power_thread, args=(start_time,))
        self.collect_power_thread.start()

    def _get_battaryproperties(self):
        '''
        :return: 杩斿洖鐢垫睜鐨勭浉鍏冲睘鎬э紝鐢甸噺锛屾俯搴︼紝鐢靛帇锛岀數娴佺瓑
        '''
        # android 5.0鍙婁互涓婄殑鐗堟湰浣跨敤璇ュ懡浠よ幏鍙栫數姹犵殑淇℃伅
        out = self.device.adb.run_shell_cmd("dumpsys batteryproperties")
        out.replace('\r', '')
        power_info = None
        if not out or (isinstance(out, str) and ("Can't find service") in out):
            #4.0鍒?.4浣跨敤璇ュ懡浠よ幏鍙栫數姹犵殑淇℃伅
            logger.debug("get battery info from dumpsys battery")
            reg = self.device.adb.run_shell_cmd("dumpsys battery")
            reg.replace('\r', '')
            power_info = DevicePowerInfo()
            power_dic = self._get_powerinfo_dic(reg)
            power_info.level = power_dic['level']
            power_info.temp = power_dic['temperature']
            power_info.voltage = power_dic['voltage']
            current_flag = power_dic['current_flag']
            if current_flag == -1:
                #鍦?.0鐨勬煇浜涚増鏈笂閫氳繃dumpsys battery娌℃湁鐢垫祦鐨勪俊鎭紝閫氳繃璇ュ懡浠よ幏鍙?
                power_info.current = self._cat_current()
            else:
                power_info.current = power_dic['current']
        else:
            power_info = DevicePowerInfo(out)
            if power_info.voltage == '0':  #涓夋槦鐨勬満鍨嬩笂娴嬭瘯浼氬彂鐜拌繖涓猟ump鍑烘潵鐨勭數鍘嬶紝鐢甸噺锛岀瓑涓? 锛屼笉姝ｇ‘,閲嶆柊鑾峰彇涓?
                logger.debug(" power info from dumpsys properties is 0, trim it")
                reg = self.device.adb.run_shell_cmd("dumpsys battery")
                reg.replace('\r', '')
                power_dic = self._get_powerinfo_dic(reg)
                power_info.level = power_dic['level']
                power_info.temp = power_dic['temperature']
                power_info.voltage = power_dic['voltage']
        logger.debug(power_info)
        return power_info

    def _cat_current(self):
        current = 0
        # cat /sys/class/power_supply/Battery/current_now Android9 涓婃病鏉冮檺
        reg = self.device.adb.run_shell_cmd('cat /sys/class/power_supply/battery/current_now')
        if isinstance(reg, str) and "No such file or directory" == reg:
            logger.debug("can't get current from file /sys/class/power_supply/battery/current_now")
        elif reg:
            current = reg
        return current

    def _get_powerinfo_dic(self, out):
        '''
        :param out: 鐢垫睜鐨刣ump淇℃伅
        :return: 杩斿洖鐢垫睜淇℃伅锛屼互瀛楀吀鐨勬柟寮忚繑鍥?
        '''
        dic = {}
        if out:
            level_l = re.findall(u'level:\s?(\d+)', out)
            temp_l = re.findall(u'temperature:\s?(\d+)', out)
            current_l = re.findall(u'current now:\s?(\d+)', out)
            vol_l = re.findall(u'  voltage:\s?(\d+)', out)
            vol_ll = re.findall(u'  voltage:\s?(\d+)', out)
            logger.debug(vol_ll)
            dic['level'] = level_l[0] if len(level_l) else 0
            dic['temperature'] = temp_l[0] if len(temp_l) else 0
            dic['current'] = current_l[0] if len(current_l) else 0
            dic['voltage'] = vol_l[0] if len(vol_l) else 0
            if len(current_l):
                dic['current'] = current_l[0]
                dic['current_flag'] = 1
            else:
                dic['current_flag'] = -1
                dic['current'] = 0
        return dic

    def _collect_power_thread(self, start_time):
        '''
        鎼滈泦鐢垫睜淇℃伅鐨勭嚎绋?
        :return:
        '''
        end_time = time.time() + self._timeout
        power_list_titile = ("datetime", "level", "voltage(V)", "tempreture(C)", "current(mA)")
        power_device_file = os.path.join(RuntimeData.package_save_path, 'powerinfo.csv')
        try:
            with open(power_device_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(power_list_titile)
                if self.power_queue:
                    power_file_dic = {'power_file': power_device_file}
                    self.power_queue.put(power_file_dic)
        except RuntimeError as e:
            logger.error(e)
        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug("------------into _collect_power_thread loop thread is : " + str(threading.current_thread().name))
                device_power_info = self._get_battaryproperties()

                if device_power_info.source == '':
                    logger.debug("can't get power info , break!")
                    break
                device_power_info = self.trim_data(device_power_info)  #debug
                collection_time = time.time()
                logger.debug(" collection time in powerconsumption is : " + str(collection_time))
                power_tmp_list = [collection_time, device_power_info.level, device_power_info.voltage,
                                  device_power_info.temp, device_power_info.current]

                if self.power_queue:
                    self.power_queue.put(power_tmp_list)

                if not self.power_queue:  #涓轰簡鏈湴鍗曚釜鑴氭湰杩愯
                    power_tmp_list[0] = TimeUtils.formatTimeStamp(power_tmp_list[0])
                    try:
                        with open(power_device_file, 'a+', encoding="utf-8") as writer:
                            writer_p = csv.writer(writer, lineterminator='\n')
                            writer_p.writerow(power_tmp_list)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except:
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
        '''
        缁堟power妯″潡鐨勬暟鎹噰闆嗗伐浣?
        :return:
        '''
        logger.debug("INFO: PowerCollector  stop...")
        if (self.collect_power_thread.is_alive()):
            self._stop_event.set()
            self.collect_power_thread.join(timeout=1)
            self.collect_power_thread = None
            #绾跨▼缁撴潫鏃讹紝闇€瑕侀€氱煡闃熷垪缁撴潫鑷繁
            if self.power_queue:
                self.power_queue.task_done()


class PowerMonitor(object):
    def __init__(self, device_id, interval=1.0, timeout=24 * 60 * 60, power_queue=None):
        self.device = AndroidDevice(device_id)
        self.power_collector = PowerCollector(self.device, interval, timeout, power_queue)

    def start(self, start_time):
        if not RuntimeData.package_save_path:
            RuntimeData.package_save_path = os.path.join(os.path.abspath(os.path.join(os.getcwd(), "../..")), 'results', self.device.adb._device_id, start_time)
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


if __name__ == "__main__":
    monitor = PowerMonitor("DWT7N19306001517", 5)
    monitor.start(TimeUtils.getCurrentTimeUnderline())
    time.sleep(10)
    monitor.stop()
#     monitor.save()
