"""纯 Python 进程工具：TCP 端口占用查找与进程树终止。

不依赖 Qt，不使用 shell 字符串拼接或 netstat/tasklist/taskkill；供主应用与
MobilePerf 内核等执行边界共用（ADR-0003 Phase 1）。ADR-0005 Step C 起，
``ProcessRunner`` 的树杀路径也统一委托到本模块。
"""

from __future__ import annotations

import time

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


def process_executable(pid: int) -> str:
    """返回进程可执行文件绝对路径；进程不存在或不可读时返回空字符串。"""

    try:
        return psutil.Process(pid).exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return ""


def kill_process_tree(
    pid: int,
    *,
    force: bool = True,
    timeout: float | None = None,
) -> tuple[bool, str]:
    """终止指定进程及其子进程（先子后父），返回 (是否已确认退出, 说明)。

    ``force=True`` 时先 terminate，超时再 kill；``force=False`` 只 terminate。
    进程本就不存在视为已终止成功，返回 (True, "already-exited")；
    子进程无法枚举或未确认退出时，父进程即使退出也不能报告整棵树成功。

    ``timeout`` 为可选总时限（秒）：提供时所有 terminate/wait/kill 步骤共享该
    绝对截止时间，剩余时间不足即放弃并返回失败；``None`` 时使用各步骤的默认
    等待（每个进程正常退出等待 1s、kill 后 2s）。
    """

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True, "already-exited"
    except (psutil.AccessDenied, OSError) as error:
        return False, str(error)
    deadline = _deadline(timeout)
    children_stopped = _kill_children(parent, force, deadline)
    if not _kill_one(parent, force, deadline):
        return False, f"parent-{pid}-kill-failed"
    if not children_stopped:
        return False, "children-not-confirmed-exited"
    return True, "terminated"


def _deadline(timeout: float | None) -> float | None:
    """把可选总时限换算为绝对截止时间；``None`` 表示无截止时间。"""

    if timeout is None:
        return None
    return time.monotonic() + max(0.0, float(timeout))


def _remaining_or(deadline: float | None, default: float) -> float | None:
    """无截止时间时返回默认等待；有截止时间时返回剩余秒数（不足 0 返回 0）。"""

    if deadline is None:
        return default
    return max(0.0, deadline - time.monotonic())


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _kill_children(parent: psutil.Process, force: bool, deadline: float | None) -> bool:
    """终止全部已枚举的后代；任一成员无法确认退出时返回 False。"""

    if _expired(deadline):
        return False
    try:
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False
    stopped = True
    for child in children:
        if _expired(deadline):
            return False
        # 即使已有后代失败也继续清理其余成员，避免短路留下可停止的进程。
        stopped = _kill_one(child, force, deadline) and stopped
    return stopped


def _kill_one(proc: psutil.Process, force: bool, deadline: float | None) -> bool:
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
        proc.wait(timeout=_remaining_or(deadline, 1.0))
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return True
    except (psutil.AccessDenied, OSError):
        return False
    except psutil.TimeoutExpired:
        if not force or _expired(deadline):
            return False
        try:
            proc.kill()
            proc.wait(timeout=_remaining_or(deadline, 2.0))
            return True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except (psutil.TimeoutExpired, psutil.AccessDenied, OSError):
            return False
