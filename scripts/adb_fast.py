"""快速 ADB 命令行入口；复用应用协议模块，不修改服务和系统配置。"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

# 直接执行脚本时也使用仓库内的正式协议实现。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.adb_transport import AdbError, execute


def main(argv: list[str] | None = None) -> int:
    """提供显式命令入口；拒绝未支持的选项与服务器配置，失败不回退原生 ADB。"""
    parser = argparse.ArgumentParser(
        description="Fast local ADB devices / non-interactive shell via existing server on 5037."
    )
    parser.add_argument("-s", "--serial", default=os.environ.get("ANDROID_SERIAL") or None)
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="total network timeout (seconds)"
    )
    parser.add_argument("command", choices=("devices", "shell"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if any(
        os.environ.get(name)
        for name in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT")
    ):
        parser.error("custom ADB server environment is not supported; use native adb")
    if options.serial is not None and (
        not options.serial or any(ord(c) < 33 or ord(c) == 127 for c in options.serial)
    ):
        parser.error("invalid device selector")
    if options.command == "devices" and options.args not in ([], ["-l"]):
        parser.error("supported syntax: devices [-l]")
    if options.command == "shell" and (
        not options.args or not " ".join(options.args).strip() or options.args[0].startswith("-")
    ):
        parser.error("shell requires a command; interactive mode and shell options are unsupported")
    if "\0" in " ".join(options.args):
        parser.error("command contains a NUL character")
    try:
        return execute(
            options.command,
            options.args,
            serial=options.serial,
            timeout=options.timeout,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
        )
    except TimeoutError:
        print(
            "adb-fast: timeout; command was not retried and remote completion is unknown.",
            file=sys.stderr,
        )
        return 124
    except KeyboardInterrupt:
        print(
            "adb-fast: interrupted; connection closed, remote completion is unknown.",
            file=sys.stderr,
        )
        return 130
    except ConnectionRefusedError:
        print(
            "adb-fast: local server unavailable; run native adb start-server once.", file=sys.stderr
        )
        return 1
    except AdbError as exc:
        print(f"adb-fast: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print(
            "adb-fast: connection or output I/O failed; command was not retried.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
