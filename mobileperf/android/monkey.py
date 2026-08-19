"""构造、运行并停止 Android Monkey 稳定性测试。"""

import math
import os
import threading
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import FileUtils, TimeUtils


class Monkey:
    """管理 Monkey 命令、输出线程和停止清理。"""

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
        pct_pinchzoom=0,
    ):
        """初始化 Monkey 目标、事件分布和运行时限。

        :param str device_id: 设备标识
        :param str package: Monkey 测试的包名
        :param timeout: Monkey 运行时长，单位秒；超大值按旧事件数语义兼容
        :param throttle_ms: Monkey 事件间隔，单位毫秒
        """
        self.package = package
        self.device = AndroidDevice(device_id)
        self.running = False  # 标记 Monkey 是否已经启动。
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

    def start(self, start_time):
        """记录开始时间并启动 Monkey。"""
        self.start_time = start_time
        if not self.running:
            self.running = True
            self.start_monkey(self.package, self.event_count, self.timeout)

    def stop(self):
        """停止 Monkey 进程和日志读取线程。"""
        self.stop_monkey()

    def start_monkey(self, package, event_count=None, timeout_seconds=None):
        """构造命令并启动 Monkey 进程及日志读取线程。"""
        if hasattr(self, "_monkey_running") and self.running:
            logger.warn("monkey process have started,not need start")
            return
        event_count = max(1, int(event_count if event_count is not None else self.event_count))
        self.monkey_cmd = self._build_monkey_cmd(package, event_count)
        if timeout_seconds is not None:
            logger.info(
                f"start monkey for {timeout_seconds}s, throttle={self.throttle_ms}ms, "
                f"events={event_count}, pct_total={self._event_percentage_total()}"
            )
        else:
            logger.info(
                f"start monkey, throttle={self.throttle_ms}ms, "
                f"events={event_count}, pct_total={self._event_percentage_total()}"
            )
        self._log_pipe = self.device.adb.run_shell_cmd(self.monkey_cmd, sync=False)
        self._monkey_thread = threading.Thread(
            target=self._monkey_thread_func,
            args=[RuntimeData.package_save_path],
            daemon=True,
        )
        self._monkey_thread.start()

    def _build_monkey_cmd(self, package, event_count):
        args = [
            "monkey",
            "-p",
            str(package),
            "-v",
            "-v",
            "-v",
            "-s",
            str(self.seed),
        ]
        if self.ignore_crashes:
            args.append("--ignore-crashes")
        if self.ignore_timeouts:
            args.append("--ignore-timeouts")
        if self.ignore_security:
            args.append("--ignore-security-exceptions")
        if self.kill_after_error:
            args.append("--kill-process-after-error")
        args.extend(
            [
                "--pct-appswitch",
                str(self.pct_appswitch),
                "--pct-touch",
                str(self.pct_touch),
                "--pct-syskeys",
                str(self.pct_syskeys),
                "--pct-motion",
                str(self.pct_motion),
                "--pct-trackball",
                str(self.pct_trackball),
                "--pct-majornav",
                str(self.pct_majornav),
                "--pct-nav",
                str(self.pct_nav),
                "--pct-anyevent",
                str(self.pct_anyevent),
                "--pct-flip",
                str(self.pct_flip),
                "--pct-pinchzoom",
                str(self.pct_pinchzoom),
                "--throttle",
                str(self.throttle_ms),
                str(max(1, int(event_count))),
            ]
        )
        return " ".join(args)

    @staticmethod
    def _percent(value):
        return max(0, min(100, int(value)))

    def _event_percentage_total(self):
        return sum(
            [
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
            ]
        )

    def _event_count_for_timeout(self, timeout_seconds):
        # Monkey 没有原生按时长运行参数，只能按 throttle 换算事件数。
        # 结束时仍由 StartUp.stop() 主动终止，保证与性能采集窗口一致收尾。
        return max(1, int(math.ceil((max(1, int(timeout_seconds)) * 1000) / self.throttle_ms)) + 1)

    def stop_monkey(self):
        self.running = False
        self._stop_event.set()
        logger.debug("stop monkey")
        if hasattr(self, "_log_pipe"):
            if self._log_pipe.poll() is None:  # 判断 Monkey 进程是否存在。
                self._log_pipe.terminate()
        try:
            self.device.adb.kill_process("com.android.commands.monkey")
        except Exception as e:
            logger.debug(f"kill monkey skipped: {e}")
        if hasattr(self, "_monkey_thread") and self._monkey_thread.is_alive():
            self._monkey_thread.join(timeout=2)

    def _monkey_thread_func(self, save_dir):
        """持续读取并分片保存 Monkey 日志，异常关键字由其他监控器处理。"""
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
                    # 兼容旧 ADB 接口返回的字节串。
                    try:
                        log = str(log, "utf8")
                    except Exception as e:
                        log = repr(log)
                        logger.error("str error:" + log)
                        logger.error(e)
                if log:
                    logs.append(log)
                    self.append_log_line_num = self.append_log_line_num + 1
                    self.file_log_line_num = self.file_log_line_num + 1
                    if self.append_log_line_num > 100:
                        if not self.log_file_create_time:
                            self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        log_file = os.path.join(
                            save_dir, f"monkey_{self.log_file_create_time}.log"
                        )
                        self.append_log_line_num = 0
                        # 降低音量，避免音量过大导致语音指令失败。
                        self.device.adb.run_shell_cmd("input keyevent 25")
                        self.save(log_file, logs)
                        logs = []
                    # 单个日志文件达到行数上限后切换到新的时间戳文件。
                    if self.file_log_line_num > 600000:
                        self.file_log_line_num = 0
                        self.log_file_create_time = TimeUtils.getCurrentTimeUnderline()
                        log_file = os.path.join(
                            save_dir, f"monkey_{self.log_file_create_time}.log"
                        )
                        self.save(log_file, logs)
                        logs = []
                else:
                    log_is_none = log_is_none + 1
                    if log_is_none % 1000 == 0:
                        logger.info("log is none")
                        if (
                            not self.device.adb.is_process_running("com.android.commands.monkey")
                            and self.running
                        ):
                            self.device.adb.kill_process("com.android.commands.monkey")
                            self._log_pipe = self.device.adb.run_shell_cmd(
                                self.monkey_cmd, sync=False
                            )
            except Exception:
                logger.error("an exception hanpend in monkey thread, reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)

    def save(self, save_file_path, loglist):
        monkey_file = os.path.join(save_file_path)
        with open(monkey_file, "a+", encoding="utf-8") as log_f:
            for log in loglist:
                log_f.write(log + "\n")


if __name__ == "__main__":
    test_pacakge_list = [
        "com.alibaba.ailabs.genie.musicplayer",
        "com.alibaba.ailabs.genie.contacts",
        "com.alibaba.ailabs.genie.launcher",
        "com.alibaba.ailabs.genie.shopping",
        "com.youku.iot",
    ]
    device = AndroidDevice()
    start_time = TimeUtils.getCurrentTimeUnderline()
    logger.debug(start_time)
    RuntimeData.top_dir = FileUtils.get_top_dir()
    RuntimeData.package_save_path = os.path.join(
        RuntimeData.top_dir, "results", "com.alibaba.ailabs.genie.contacts", start_time
    )
    main_activity = ["com.alibaba.ailabs.genie.contacts.MainActivity"]
    activity_list = [
        "com.alibaba.ailabs.genie.contacts.MainActivity",
        "com.alibaba.ailabs.genie.contacts.cmd.CmdDispatchActivity",
        "com.alibaba.ailabs.genie.contacts.cmd.transform.VoipToPstnActivity",
        "com.alibaba.ailabs.genie.contacts.add.AddContactsActivity",
    ]
    monkey = Monkey("WST4DYVWKBFEV8Q4", "com.alibaba.ailabs.genie.smartapp")
    monkey.start(start_time)
