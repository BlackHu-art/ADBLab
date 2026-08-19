"""纯 Python 进程工具：TCP 端口占用查找与进程树终止。

不依赖 Qt，不使用 shell 字符串拼接或 netstat/tasklist/taskkill；供主应用与
MobilePerf 内核等执行边界共用（ADR-0003 Phase 1）。
"""

from __future__ import annotations

import psutil


def find_pids_listening_on(port: int) -> list[int]:
    """返回监听指定 TCP 端口的进程 PID 列表（去重、保序）。

    无法读取全部连接（跨用户权限不足等）时返回已收集到的部分结果，不抛异常。
    """
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError(f"invalid port: {port!r}")
    pids: list[int] = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            local_port = getattr(conn.laddr, "port", None)
            if local_port != port:
                continue
            pid = conn.pid
            if pid is not None and pid not in pids:
                pids.append(pid)
    except (psutil.AccessDenied, psutil.Error, OSError):
        pass
    return pids


def process_name(pid: int) -> str:
    """返回进程名；进程不存在或不可读时返回空字符串。"""
    try:
        return psutil.Process(pid).name() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return ""


def kill_process_tree(pid: int, *, force: bool = True) -> tuple[bool, str]:
    """终止指定进程及其子进程（先子后父），返回 (是否已确认退出, 说明)。

    ``force=True`` 时先 terminate，超时再 kill；``force=False`` 只 terminate。
    进程本就不存在视为已终止成功，返回 (True, "already-exited")。
    """
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True, "already-exited"
    except (psutil.AccessDenied, OSError) as error:
        return False, str(error)
    _kill_children(parent, force)
    if not _kill_one(parent, force):
        return False, f"parent-{pid}-kill-failed"
    try:
        parent.wait(timeout=3)
        return True, "terminated"
    except psutil.TimeoutExpired:
        return False, f"parent-{pid}-still-alive"
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return True, "terminated"


def _kill_children(parent: psutil.Process, force: bool) -> None:
    """递归终止子进程，先处理最深层后代。"""
    try:
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return
    for child in children:
        _kill_one(child, force)
    for child in children:
        try:
            child.wait(timeout=1)
        except (psutil.TimeoutExpired, psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _kill_one(proc: psutil.Process, force: bool) -> bool:
    """终止单个进程；已退出视为成功。"""
    try:
        if proc.is_running():
            proc.terminate()
        else:
            return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return True
    except (psutil.AccessDenied, OSError):
        return False
    try:
        proc.wait(timeout=1)
        return True
    except psutil.TimeoutExpired:
        if not force:
            return False
        try:
            proc.kill()
            proc.wait(timeout=2)
            return True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except (psutil.TimeoutExpired, psutil.AccessDenied, OSError):
            return False
