# -*- coding: utf-8 -*-
"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""
import os
import re

import sys, csv
import threading
import random
import time
import traceback

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))
from mobileperf.common.log import logger
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.android.globaldata import RuntimeData
from mobileperf.common.utils import TimeUtils


class DeviceMonitor(object):
    '''
    涓€涓洃鎺х被锛岀洃鎺ф墜鏈轰腑鐨勪竴浜涚姸鎬佸彉鍖栵紝鐩墠鐩戞帶搴旂敤鏄惁鍗歌浇锛岃幏鍙栧墠鍙版鍦ㄦ椿鍔ㄧ殑activity
    '''

    def __init__(self, device_id, packagename, interval=1.0, main_activity=[], activity_list=[], event=None, activity_queue=None):
        ''''
        :param list main_activity 鎸囧畾妯″潡鐨勪富鍏ュ彛
        :param list activity_list : 闄愬埗榛樿鑼冨洿鐨刟ctivity鍒楄〃锛岄粯璁や负绌猴紝鍒欎笉闄愬埗
        '''
        self.uninstall_flag = event
        self.device = AndroidDevice(device_id)
        self.packagename = packagename
        self.interval = interval
        self.main_activity = main_activity
        self.activity_list = activity_list
        self.stop_event = threading.Event()
        self.activity_queue = activity_queue
        self.current_activity = None

    def start(self, starttime):
        self.activity_monitor_thread = threading.Thread(target=self._activity_monitor_thread)
        self.activity_monitor_thread.start()
        logger.debug("DeviceMonitor activitymonitor has started...")

        # self.uninstaller_checker_thread = threading.Thread(target=self._uninstaller_checker_thread)
        # self.uninstaller_checker_thread.start()
        # logger.debug("DeviceMonitor uninstaller checker has started...")

    def stop(self):
        if self.activity_monitor_thread.is_alive():
            self.stop_event.set()
            self.activity_monitor_thread.join(timeout=1)
            self.activity_monitor_thread = None
            if self.activity_queue:
                self.activity_queue.task_done()
        logger.debug("DeviceMonitor stopped!")

    def _activity_monitor_thread(self):
        activity_title = ("datetime", "current_activity")
        self.activity_file = os.path.join(RuntimeData.package_save_path, 'current_activity.csv')
        try:
            with open(self.activity_file, 'a+') as af:
                csv.writer(af, lineterminator='\n').writerow(activity_title)
        except Exception as e:
            logger.error("file not found: " + str(self.activity_file))

        while not self.stop_event.is_set():
            try:
                before = time.time()
                self.current_activity = self.device.adb.get_current_activity()
                collection_time = time.time()
                activity_list = [collection_time, self.current_activity]
                if self.activity_queue:
                    logger.debug("activity monitor thread activity_list: " + str(activity_list))
                    self.activity_queue.put(activity_list)
                if self.current_activity:
                    logger.debug("current activity: " + self.current_activity)
                    if self.main_activity and self.activity_list:
                        if self.current_activity not in self.activity_list:
                            start_activity = self.packagename + "/" + self.main_activity[
                                random.randint(0, len(self.main_activity) - 1)]
                            logger.debug("start_activity:" + start_activity)
                            self.device.adb.start_activity(start_activity)
                    activity_tuple = (TimeUtils.getCurrentTime(), self.current_activity)
                    # 鍐欐枃浠?
                    try:
                        with open(self.activity_file, 'a+', encoding="utf-8") as writer:
                            writer_p = csv.writer(writer, lineterminator='\n')
                            writer_p.writerow(activity_tuple)
                    except RuntimeError as e:
                        logger.error(e)
                time_consume = time.time() - before
                delta_inter = self.interval - time_consume
                logger.debug("get app activity time consumed: " + str(time_consume))
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception as e:
                s = traceback.format_exc()
                logger.debug(s)  # 灏嗗爢鏍堜俊鎭墦鍗板埌log涓?
                if self.activity_queue:
                    self.activity_queue.task_done()

    # 杩欎釜妫€鏌ラ鐜囦笉鐢ㄩ偅涔堥珮
    def _uninstaller_checker_thread(self):
        '''
        杩欎釜鏂规硶鐢ㄨ疆璇㈢殑鏂瑰紡鏌ヨ鎸囧畾鐨勫簲鐢ㄦ槸鍚﹁鍗歌浇锛屼竴鏃﹀嵏杞戒細寰€涓荤嚎绋嬪彂閫佷竴涓嵏杞界殑淇″彿锛岀粓姝㈢▼搴?
        :return:
        '''
        while not self.stop_event.is_set():
            before = time.time()
            is_installed = self.device.adb.is_app_installed(self.packagename)
            if not is_installed:
                if self.uninstall_flag and isinstance(self.uninstall_flag, threading._Event):
                    logger.debug("uninstall flag is set, as the app has checked uninstalled!")
                    self.uninstall_flag.set()
            time_consume = time.time() - before
            delta_inter = self.interval * 10 - time_consume
            logger.debug("check installed app: " + self.packagename + ", time consumed: " + str(time_consume) + ", is installed: " + str(is_installed))
            if delta_inter > 0:
                time.sleep(delta_inter)


if __name__ == '__main__':
    monitor = DeviceMonitor("NVGILZSO99999999", "com.taobao.taobao", 2)
    monitor.start(time.time())
    time.sleep(60)
    monitor.stop()
