"""构造、运行并停止 Android Monkey 稳定性测试。"""

import math
import os
import subprocess
import threading
import traceback

from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.log import logger
from mobileperf.common.utils import FileUtils, TimeUtils


class MonkeyError(RuntimeError):
    """所请求的 Monkey 未成功启动、执行或停止，采集不能报告正常完成。"""


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
        self._log_pipe = None
        self._monkey_thread = None
        self._owns_process = False
        self._failure = None

    def start(self, start_time):
        """记录开始时间并启动 Monkey。"""
        self.start_time = start_time
        if not self.running:
            self.start_monkey(self.package, self.event_count, self.timeout)

    def stop(self):
        """停止 Monkey 进程和日志读取线程。"""
        self.stop_monkey()

    def start_monkey(self, package, event_count=None, timeout_seconds=None):
        """构造命令并启动 Monkey 进程及日志读取线程。"""
        if self.running or (self._monkey_thread is not None and self._monkey_thread.is_alive()):
            logger.warning("Monkey 已在运行，忽略重复启动")
            return
        if self._owns_process:
            self.stop_monkey()
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
        self._stop_event.clear()
        self._failure = None
        try:
            # Monkey 的失败诊断可能写入 stderr；合并后由同一个 reader 持续排空。
            self._log_pipe = self.device.adb.run_shell_cmd(
                self.monkey_cmd, sync=False, merge_stderr=True
            )
            if self._log_pipe is None:
                raise RuntimeError("Monkey 未返回可读取的进程")
            self._owns_process = True
            if self._log_pipe.stdout is None:
                raise RuntimeError("Monkey 未返回可读取的输出管道")
            self.running = True
            self._monkey_thread = threading.Thread(
                target=self._monkey_thread_func,
                args=[RuntimeData.package_save_path],
                daemon=True,
            )
            self._monkey_thread.start()
        except Exception as exc:
            self.running = False
            self._failure = MonkeyError("Monkey 启动失败，请检查设备连接和运行日志。")
            try:
                self.stop_monkey()
            except MonkeyError:
                logger.debug("Monkey 启动失败后的清理仍未完成", exc_info=True)
            raise self._failure from exc

    def raise_if_failed(self):
        """将后台 reader 的失败交回采集主线程，避免只留下日志却报告成功。"""
        if self._failure is not None:
            raise self._failure

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
        """停止本实例启动的 Monkey，并有界等待本地进程和日志 reader。"""
        self.running = False
        self._stop_event.set()
        if not self._owns_process:
            return
        failure = None
        try:
            self._reap_local_process()
        except (OSError, subprocess.TimeoutExpired) as exc:
            failure = exc
        try:
            self.device.adb.kill_process("com.android.commands.monkey")
        except Exception as exc:
            failure = failure or exc
        if self._monkey_thread is not None and self._monkey_thread.is_alive():
            self._monkey_thread.join(timeout=2)
            if self._monkey_thread.is_alive():
                failure = failure or RuntimeError("Monkey 日志线程尚未退出")
        if failure is not None:
            raise MonkeyError("Monkey 停止未完成，请检查设备连接和运行日志。") from failure
        self._close_process_streams()
        self._owns_process = False

    def _reap_local_process(self):
        """终止 adb 客户端后确认其退出，避免 reader 留在阻塞读取中。"""
        process = self._log_pipe
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _close_process_streams(self):
        """reader 结束后释放本次 Popen 创建的管道。"""
        if self._log_pipe is None:
            return
        for stream in (self._log_pipe.stdin, self._log_pipe.stdout, self._log_pipe.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _monkey_thread_func(self, save_dir):
        """持续读取并分片保存 Monkey 日志，异常关键字由其他监控器处理。"""
        self.append_log_line_num = 0
        self.file_log_line_num = 0
        self.log_file_create_time = None
        logs = []
        logger.debug("monkey_thread_func")
        if RuntimeData.start_time is None:
            RuntimeData.start_time = TimeUtils.getCurrentTime()
        try:
            process = self._log_pipe
            if process is None or process.stdout is None:
                raise RuntimeError("Monkey 进程或输出管道尚未建立")
            while not self._stop_event.is_set():
                raw_line = process.stdout.readline()
                if not raw_line:
                    exit_code = process.poll()
                    if exit_code is not None:
                        if exit_code != 0 and not self._stop_event.is_set():
                            self._failure = MonkeyError(
                                f"Monkey 运行失败（退出码 {exit_code}），请查看 Monkey 日志。"
                            )
                            logger.error(self._failure)
                        break
                    self._stop_event.wait(0.1)
                    continue
                log = raw_line.strip()
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
        except Exception:
            if not self._stop_event.is_set():
                self._failure = MonkeyError("Monkey 日志读取失败，请检查设备连接和日志目录。")
                logger.error(self._failure)
                logger.debug(traceback.format_exc())
        finally:
            try:
                if logs:
                    stamp = self.log_file_create_time or TimeUtils.getCurrentTimeUnderline()
                    self.save(os.path.join(save_dir, f"monkey_{stamp}.log"), logs)
                self._reap_local_process()
            except (OSError, subprocess.TimeoutExpired):
                self._failure = self._failure or MonkeyError("Monkey 日志或进程清理失败。")
                logger.error(self._failure)
                logger.debug(traceback.format_exc())
            finally:
                self.running = False
                self._close_process_streams()

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
