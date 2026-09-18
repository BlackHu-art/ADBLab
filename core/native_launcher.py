"""隔离 frozen 运行库环境后启动外部原生程序，不导入 Qt 或应用业务模块。"""

from __future__ import annotations

import ctypes
import ntpath
import os
import subprocess
import sys
from contextlib import ExitStack
from ctypes import wintypes


def sanitize_environment(environment: dict[str, str], root: str) -> dict[str, str]:
    """仅移除解包目录及其子目录的 PATH 项，保留同名前缀目录和 frozen 元数据。"""
    cleaned = dict(environment)
    if not root:
        return cleaned
    normalized_root = ntpath.normcase(ntpath.abspath(root))

    def belongs_to_extraction(entry: str) -> bool:
        candidate = entry.strip().strip('"')
        if not candidate:
            return False
        normalized = ntpath.normcase(ntpath.abspath(candidate))
        try:
            return ntpath.commonpath((normalized_root, normalized)) == normalized_root
        except ValueError:
            return False

    for key, value in environment.items():
        if key.upper() == "PATH":
            cleaned[key] = ";".join(
                entry for entry in value.split(";") if not belongs_to_extraction(entry)
            )
    return cleaned


def _kernel():
    """独立定义 Win32 函数签名，句柄由本次启动的清理栈独占。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD,
    ]
    kernel.WaitForMultipleObjects.restype = wintypes.DWORD
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    return kernel


def _control_cancelled(kernel, handles) -> bool:
    """取消或原属主退出即终止；监视失效必须报错，不能继续运行失管进程。"""
    state = kernel.WaitForMultipleObjects(len(handles), handles, False, 0)
    if state in (0, 1):
        return True
    if state != 258:
        raise ctypes.WinError(ctypes.get_last_error())
    return False


def _startup_info(resources: ExitStack):
    """复制真实标准句柄限定继承，兼容 sys.std* 为 None 的 windowed helper。"""
    import _winapi
    import msvcrt

    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESTDHANDLES
    duplicates = []
    process = _winapi.GetCurrentProcess()
    for attribute, code, access in (
        ("hStdInput", _winapi.STD_INPUT_HANDLE, os.O_RDONLY),
        ("hStdOutput", _winapi.STD_OUTPUT_HANDLE, os.O_WRONLY),
        ("hStdError", _winapi.STD_ERROR_HANDLE, os.O_WRONLY),
    ):
        handle = _winapi.GetStdHandle(code)
        # 缺少真实标准句柄才落到空设备，不能用 Python 流对象判断管道是否存在。
        with ExitStack() as fallback:
            if handle in (None, 0, -1, ctypes.c_void_p(-1).value):
                descriptor = os.open(os.devnull, access | os.O_BINARY)
                fallback.callback(os.close, descriptor)
                handle = msvcrt.get_osfhandle(descriptor)
            duplicate = _winapi.DuplicateHandle(
                process, handle, process, 0, True, _winapi.DUPLICATE_SAME_ACCESS,
            )
        resources.callback(_winapi.CloseHandle, duplicate)
        duplicates.append(duplicate)
        setattr(startup, attribute, duplicate)
    startup.lpAttributeList = {"handle_list": duplicates}
    return startup


def _setup_failure() -> int:
    """诊断只写真实 stderr 的固定脱敏文本；坏句柄不得覆盖原本的失败状态。"""
    if sys.platform == "win32":
        import _winapi

        try:
            handle = _winapi.GetStdHandle(_winapi.STD_ERROR_HANDLE)
            if handle not in (None, 0, -1, ctypes.c_void_p(-1).value):
                _winapi.WriteFile(
                    handle, b"ADBLab native launcher: setup or process creation failed.\n",
                )
        except OSError:
            return 2
    return 2


def launch(argv: list[str]) -> int:
    """执行绝对路径 exe；取消或属主退出返回 130，准备失败返回 2。

    参数必须为 ``--cancel-event 名称 --owner PID -- exe 参数...``。控制句柄在
    创建目标前获得且不可继承；仅本 helper 清理 DLL 搜索路径。创建窗口期间的
    取消由创建后的再次检查收敛，只结束直接拥有的客户端，不回收独立 ADB server。
    """
    if sys.platform != "win32":
        return _setup_failure()
    child = None
    try:
        if len(argv) < 6 or argv[0] != "--cancel-event" or argv[2] != "--owner" or argv[4] != "--":
            return _setup_failure()
        event_name, owner_pid, command = argv[1], int(argv[3]), argv[5:]
        if not event_name or not 0 < owner_pid <= 0xFFFFFFFF:
            return _setup_failure()
        program = command[0]
        if (
            not os.path.isabs(program)
            or not os.path.isfile(program)
            or not program.lower().endswith(".exe")
        ):
            return _setup_failure()
        kernel = _kernel()
        with ExitStack() as controls:
            event = kernel.OpenEventW(0x00100000, False, event_name)
            if not event:
                return _setup_failure()
            controls.callback(kernel.CloseHandle, event)
            owner = kernel.OpenProcess(0x00100000, False, owner_pid)
            if not owner:
                return _setup_failure()
            controls.callback(kernel.CloseHandle, owner)
            handles = (wintypes.HANDLE * 2)(event, owner)
            if _control_cancelled(kernel, handles):
                return 130
            if not kernel.SetDllDirectoryW(None):
                return _setup_failure()
            environment = sanitize_environment(dict(os.environ), getattr(sys, "_MEIPASS", ""))
            with ExitStack() as streams:
                startup = _startup_info(streams)
                child = subprocess.Popen(
                    command, env=environment, startupinfo=startup,
                    close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            while True:
                if _control_cancelled(kernel, handles):
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    return 130
                try:
                    returncode = child.wait(timeout=0.05)
                    # sys.exit 只接受有符号 C int；转换表示才能保留 Windows DWORD 原码。
                    return returncode - (1 << 32) if returncode > 0x7FFFFFFF else returncode
                except subprocess.TimeoutExpired:
                    continue
    except (OSError, ValueError):
        return _setup_failure()
    finally:
        # 创建成功后的任何监视或管道异常均须回收本次客户端，不能遗留失管进程。
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
