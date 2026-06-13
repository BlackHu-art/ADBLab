# -*- coding: utf-8 -*-

"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""
import csv
import math
import os
import re
import sys
import threading
import time
import random
import traceback

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))

from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils,FileUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData


class Monkey(object):
    '''
    monkey执行器
    '''

    DEFAULT_THROTTLE_MS = 500
    DEFAULT_EVENT_COUNT = 1200000000
    LEGACY_EVENT_COUNT_THRESHOLD = 10000000

    def __init__(
            self,
            device_id,
            package=None,
            timeout=None,
            throttle_ms=DEFAULT_THROTTLE_MS,
            seed=1000000,
            ignore_crashes=True,
            ignore_timeouts=True,
            ignore_security=True,
            kill_after_error=True,
            pct_touch=15,
            pct_motion=5,
            pct_trackball=0,
            pct_nav=40,
            pct_majornav=30,
            pct_syskeys=5,
            pct_appswitch=0,
            pct_anyevent=5,
            pct_flip=0,
            pct_pinchzoom=0):
        '''构造器

        :param str device_id: 设备id
        :param str process : monkey测试的包名
        :param timeout : monkey运行时长，单位秒。旧调用未传或传超大事件数时保持兼容。
        :param throttle_ms : monkey事件间隔，单位毫秒
        '''
        self.package = package
        self.device = AndroidDevice(device_id)  # 设备
        self.running = False  # monkey监控器的启动状态(启动/结束)
        self.throttle_ms = max(1, int(throttle_ms))
        self.seed = max(0, int(seed))
        self.ignore_crashes = bool(ignore_crashes)
        self.ignore_timeouts = bool(ignore_timeouts)
        self.ignore_security = bool(ignore_security)
        self.kill_after_error = bool(kill_after_error)
        self.pct_touch = self._percent(pct_touch)
        self.pct_motion = self._percent(pct_motion)
        self.pct_trackball = self._percent(pct_trackball)
        self.pct_nav = self._percent(pct_nav)
        self.pct_majornav = self._percent(pct_majornav)
        self.pct_syskeys = self._percent(pct_syskeys)
        self.pct_appswitch = self._percent(pct_appswitch)
        self.pct_anyevent = self._percent(pct_anyevent)
        self.pct_flip = self._percent(pct_flip)
        self.pct_pinchzoom = self._percent(pct_pinchzoom)
        self.timeout = None
        self.event_count = self.DEFAULT_EVENT_COUNT
        if timeout is not None:
            timeout_value = max(1, int(timeout))
            if timeout_value >= self.LEGACY_EVENT_COUNT_THRESHOLD:
                self.event_count = timeout_value
            else:
                self.timeout = timeout_value
                self.event_count = self._event_count_for_timeout(timeout_value)
        self._stop_event = threading.Event()

    def start(self,start_time):
        '''启动monkey
        '''
        self.start_time = start_time
        if not self.running:
            self.running = True
            # time.sleep(1)
            self.start_monkey(self.package, self.event_count, self.timeout)

    def stop(self):
        '''结束monkey
        '''
        self.stop_monkey()

    def start_monkey(self, package, event_count=None, timeout_seconds=None):
        '''运行monkey进程
        '''
        if hasattr(self, '_monkey_running') and self.running == True:
            logger.warn(u'monkey process have started,not need start')
            return
        event_count = max(1, int(event_count if event_count is not None else self.event_count))
        self.monkey_cmd = self._build_monkey_cmd(package, event_count)
        if timeout_seconds is not None:
            logger.info("start monkey for %ss, throttle=%sms, events=%s, pct_total=%s" % (
                timeout_seconds,
                self.throttle_ms,
                event_count,
                self._event_percentage_total(),
            ))
        else:
            logger.info("start monkey, throttle=%sms, events=%s, pct_total=%s" % (
                self.throttle_ms,
                event_count,
                self._event_percentage_total(),
            ))
        self._log_pipe = self.device.adb.run_shell_cmd(self.monkey_cmd, sync=False)
        self._monkey_thread = threading.Thread(target=self._monkey_thread_func, args=[RuntimeData.package_save_path])
        # self._monkey_thread.setDaemon(True)
        self._monkey_thread.start()

    def _build_monkey_cmd(self, package, event_count):
        args = [
            "monkey",
            "-p", str(package),
            "-v", "-v", "-v",
            "-s", str(self.seed),
        ]
        if self.ignore_crashes:
            args.append("--ignore-crashes")
        if self.ignore_timeouts:
            args.append("--ignore-timeouts")
        if self.ignore_security:
            args.append("--ignore-security-exceptions")
        if self.kill_after_error:
            args.append("--kill-process-after-error")
        args.extend([
            "--pct-appswitch", str(self.pct_appswitch),
            "--pct-touch", str(self.pct_touch),
            "--pct-syskeys", str(self.pct_syskeys),
            "--pct-motion", str(self.pct_motion),
            "--pct-trackball", str(self.pct_trackball),
            "--pct-majornav", str(self.pct_majornav),
            "--pct-nav", str(self.pct_nav),
            "--pct-anyevent", str(self.pct_anyevent),
            "--pct-flip", str(self.pct_flip),
            "--pct-pinchzoom", str(self.pct_pinchzoom),
            "--throttle", str(self.throttle_ms),
            str(max(1, int(event_count))),
        ])
        return " ".join(args)

    @staticmethod
    def _percent(value):
        return max(0, min(100, int(value)))

    def _event_percentage_total(self):
        return sum([
            self.pct_appswitch,
            self.pct_touch,
            self.pct_syskeys,
            self.pct_motion,
            self.pct_trackball,
            self.pct_majornav,
            self.pct_nav,
            self.pct_anyevent,
            self.pct_flip,
            self.pct_pinchzoom,
        ])

    def _event_count_for_timeout(self, timeout_seconds):
        # monkey没有原生按时长运行参数，只能用事件数约束；事件数按throttle换算，
        # 结束时仍由StartUp.stop()主动kill，保证和性能采集窗口一致收尾。
        return max(1, int(math.ceil((max(1, int(timeout_seconds)) * 1000) / self.throttle_ms)) + 1)

    def stop_monkey(self):
        self.running = False
        self._stop_event.set()
        logger.debug("stop monkey")
        if hasattr(self, '_log_pipe'):
            if self._log_pipe.poll() == None: #判断logcat进程是否存在
                self._log_pipe.terminate()
        try:
            self.device.adb.kill_process("com.android.commands.monkey")
        except Exception as e:
            logger.debug("kill monkey skipped: %s" % e)
        if hasattr(self, '_monkey_thread') and self._monkey_thread.is_alive():
            self._monkey_thread.join(timeout=2)

    def _monkey_thread_func(self,save_dir):
        '''获取monkey线程，保存monkey日志，monkey Crash日志暂不处理，后续有需要再处理
        '''
        self.append_log_line_num = 0
        self.file_log_line_num = 0
        self.log_file_create_time = None
        log_is_none = 0
        logs = []
        logger.debug("monkey_thread_func")
        if RuntimeData.start_time is None:
            RuntimeData.start_time = TimeUtils.getCurrentTime()
        while self.running:
            try:
                log = self._log_pipe.stdout.readline().strip()
                if not isinstance(log, str):
                    # 先编码为unicode
                    try:
                        log = str(log, "utf8")
                    except Exception as e:
                        log = repr(log)
                        logger.error('str error:' + log)
                        logger.error(e)
                if log:
                    logs.append(log)
                    self.append_log_line_num = self.append_log_line_num + 1
                    self.file_log_line_num = self.file_log_line_num + 1
                    # if self.append_log_line_num > 1000:
                    if self.append_log_line_num > 100:
                        if not self.log_file_create_time:
                            self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        log_file = os.path.join(save_dir,
                                                'monkey_%s.log' % self.log_file_create_time)
                        self.append_log_line_num = 0
                        # 降低音量，避免音量过大，导致语音指令失败
                        self.device.adb.run_shell_cmd("input keyevent 25")
                        self.save(log_file, logs)
                        logs = []
                    # 新建文件
                    if self.file_log_line_num > 600000:
                        # if self.file_log_line_num > 200:
                        self.file_log_line_num = 0
                        self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        log_file = os.path.join(save_dir, 'monkey_%s.log' % self.log_file_create_time)
                        self.save(log_file, logs)
                        logs = []
                else:
                    log_is_none = log_is_none + 1
                    if log_is_none % 1000 == 0:
                        logger.info("log is none")
                        if not self.device.adb.is_process_running("com.android.commands.monkey") and self.running:
                            self.device.adb.kill_process("com.android.commands.monkey")
                            self._log_pipe = self.device.adb.run_shell_cmd(self.monkey_cmd, sync=False)
            except:
                logger.error("an exception hanpend in monkey thread, reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)

    def save(self, save_file_path, loglist):
        monkey_file = os.path.join(save_file_path)
        with open(monkey_file, 'a+', encoding="utf-8") as log_f:
            for log in loglist:
                log_f.write(log + "\n")


if __name__ == "__main__":
    test_pacakge_list = ["com.alibaba.ailabs.genie.musicplayer","com.alibaba.ailabs.genie.contacts","com.alibaba.ailabs.genie.launcher",
            "com.alibaba.ailabs.genie.shopping","com.youku.iot"]
    device = AndroidDevice()
    # device.adb.kill_process("monkey")
    # for i in range(0, 10):
    #     for package in test_pacakge_list:
    #         monkey = Monkey("",package,1200000000)
    #         monkey.start(TimeUtils.getCurrentTimeUnderline())
    #         time.sleep(60*60*2)
    #         monkey.stop()
    start_time = TimeUtils.getCurrentTimeUnderline()
    logger.debug(start_time)
    RuntimeData.top_dir = FileUtils.get_top_dir()
    RuntimeData.package_save_path = os.path.join(RuntimeData.top_dir, 'results', "com.alibaba.ailabs.genie.contacts", start_time)
    main_activity = ["com.alibaba.ailabs.genie.contacts.MainActivity"]
    activity_list = ["com.alibaba.ailabs.genie.contacts.MainActivity",
                     "com.alibaba.ailabs.genie.contacts.cmd.CmdDispatchActivity",
                     "com.alibaba.ailabs.genie.contacts.cmd.transform.VoipToPstnActivity",
                     "com.alibaba.ailabs.genie.contacts.add.AddContactsActivity"]
    monkey = Monkey("WST4DYVWKBFEV8Q4","com.alibaba.ailabs.genie.smartapp")
    monkey.start(start_time)
