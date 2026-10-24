"""仅标准库的独立冻结交接入口，不加载 Qt 或安装运行锁。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""} and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    """首条请求与后续 COMMIT 都有界；缺少管道授权只退出，不执行缓存文件。"""
    if sys.argv[1:] == ["--self-check"]:
        from core import installer_update_process, installer_update_protocol

        if (installer_update_protocol.HELPER_NAME != "adblab-update-handoff"
                or not callable(installer_update_process.read_pipe_line)
                or any(name.startswith(("PySide", "PyQt")) for name in sys.modules)):
            return 1
        print("installer-update-handoff: ready", flush=True)
        return 0
    if sys.argv[1:] or sys.platform != "win32":
        return 64
    from core.installer_update_process import read_pipe_line
    from core.installer_update_protocol import COMMIT_TIMEOUT, execute_handoff

    try:
        request = json.loads(read_pipe_line(sys.stdin.buffer, timeout=45))
        return execute_handoff(
            request, receive=lambda: read_pipe_line(sys.stdin.buffer, timeout=COMMIT_TIMEOUT),
            send=lambda message: os.write(sys.stdout.fileno(), message + b"\n"),
        )
    except (OSError, EOFError, ValueError, TimeoutError):
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
