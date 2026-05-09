
import logging
import os
import sys
from typing import Optional

ROOT_NAME = "ADBLab"
_DATE_FMT = "%H:%M:%S"

_COLORS = {
    logging.DEBUG:    "\033[36m",  # cyan
    logging.INFO:     "\033[32m",  # green
    logging.WARNING:  "\033[33m",  # yellow
    logging.ERROR:    "\033[31m",  # red
    logging.CRITICAL: "\033[1;41m",  # white on red
}
_RESET = "\033[0m"

_initialized = False


class _ColorFormatter(logging.Formatter):
    def format(self, record):
        s = super().format(record)
        code = _COLORS.get(record.levelno, "")
        # 尝试检测是否在支持颜色的环境中，包括VSCode
        is_tty = sys.stderr.isatty()
        is_vscode = os.environ.get('VSCODE_PID') is not None
        force_color = os.environ.get('FORCE_COLOR', '').lower() in ('1', 'true', 'yes')
        
        return f"{code}{s}{_RESET}" if code and (is_tty or is_vscode or force_color) else s


def _init():
    global _initialized
    if _initialized:
        return
    root = logging.getLogger(ROOT_NAME)
    root.setLevel(logging.DEBUG if os.environ.get("ADBLAB_DEBUG") else logging.INFO)
    root.propagate = False
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(_ColorFormatter(
            fmt="%(asctime)s %(levelname)-7s %(name)-18s | %(message)s",
            datefmt=_DATE_FMT,
        ))
        root.addHandler(h)
    _initialized = True


def get_logger(name: str | None = None):
    _init()
    root = logging.getLogger(ROOT_NAME)
    return root if name is None else root.getChild(name)


def set_level(level: int | str):
    _init()
    logging.getLogger(ROOT_NAME).setLevel(level)


def enable_debug():
    set_level(logging.DEBUG)


if __name__ == "__main__":
    # Create test logger
    logger = get_logger("TestLogger")

    # Test different log levels
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")

    # Test child logger
    sub_logger = get_logger("sub.test")
    sub_logger.info("Message from child logger")
    
    # Test debug mode
    print("\n--- Enabling debug mode ---")
    os.environ["ADBLAB_DEBUG"] = "1"
    debug_logger = get_logger("DebugTest")
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.debug("Now you should see debug messages")
    debug_logger.info("Info message")
    