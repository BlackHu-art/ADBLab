"""在独立 pytest 进程中记录一次堆异常原生栈，不改变异常处理与业务代码。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import gc
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
LATE_SYMBOLS = "--late-symbols" in sys.argv
FOCUS_SLICE = "--focus-slice" in sys.argv
OUTPUT = Path(__file__).with_name(
    "native-heap-stack-focus-late.txt" if LATE_SYMBOLS else "native-heap-stack.txt"
)
LOCAL_SYMBOLS = Path(__file__).with_name("native-local-symbols")
LOCAL_SYMBOLS.mkdir(exist_ok=True)
LOG_FD = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
PROCESS_HEAP_CORRUPTION = 0xC0000374
MAX_FRAMES = 72


class ExceptionRecord(ctypes.Structure):
    _fields_ = [
        ("code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("record", ctypes.c_void_p),
        ("address", ctypes.c_void_p),
        ("parameter_count", wintypes.DWORD),
        ("information", ctypes.c_size_t * 15),
    ]


class ExceptionPointers(ctypes.Structure):
    _fields_ = [
        ("record", ctypes.POINTER(ExceptionRecord)),
        ("context", ctypes.c_void_p),
    ]


class SymbolInfo(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", wintypes.ULONG),
        ("TypeIndex", wintypes.ULONG),
        ("Reserved", ctypes.c_ulonglong * 2),
        ("Index", wintypes.ULONG),
        ("Size", wintypes.ULONG),
        ("ModBase", ctypes.c_ulonglong),
        ("Flags", wintypes.ULONG),
        ("Value", ctypes.c_ulonglong),
        ("Address", ctypes.c_ulonglong),
        ("Register", wintypes.ULONG),
        ("Scope", wintypes.ULONG),
        ("Tag", wintypes.ULONG),
        ("NameLen", wintypes.ULONG),
        ("MaxNameLen", wintypes.ULONG),
        ("Name", ctypes.c_char * 1),
    ]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(ExceptionPointers))
kernel.AddVectoredExceptionHandler.argtypes = [wintypes.ULONG, CALLBACK]
kernel.AddVectoredExceptionHandler.restype = ctypes.c_void_p
kernel.RemoveVectoredExceptionHandler.argtypes = [ctypes.c_void_p]
kernel.RemoveVectoredExceptionHandler.restype = wintypes.ULONG
kernel.RtlCaptureStackBackTrace.argtypes = [
    wintypes.ULONG, wintypes.ULONG, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
]
kernel.RtlCaptureStackBackTrace.restype = wintypes.WORD
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.GetModuleHandleExW.argtypes = [
    wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE),
]
kernel.GetModuleHandleExW.restype = wintypes.BOOL
kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
kernel.GetModuleFileNameW.restype = wintypes.DWORD
dbghelp.SymSetOptions.argtypes = [wintypes.DWORD]
dbghelp.SymSetOptions.restype = wintypes.DWORD
dbghelp.SymInitializeW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.BOOL]
dbghelp.SymInitializeW.restype = wintypes.BOOL
dbghelp.SymFromAddr.argtypes = [
    wintypes.HANDLE, ctypes.c_ulonglong, ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(SymbolInfo),
]
dbghelp.SymFromAddr.restype = wintypes.BOOL
dbghelp.SymRefreshModuleList.argtypes = [wintypes.HANDLE]
dbghelp.SymRefreshModuleList.restype = wintypes.BOOL
dbghelp.SymCleanup.argtypes = [wintypes.HANDLE]
dbghelp.SymCleanup.restype = wintypes.BOOL

PROCESS = kernel.GetCurrentProcess()
# 显式本机空目录，忽略系统符号路径，不使用符号服务器或自动搜索图像。
dbghelp.SymSetOptions(0x2 | 0x200 | 0x1000 | 0x20000 | 0x40000 | 0x80000)
SYMBOLS_READY = not LATE_SYMBOLS and bool(
    dbghelp.SymInitializeW(PROCESS, str(LOCAL_SYMBOLS), True)
)
STACK = (ctypes.c_void_p * MAX_FRAMES)()
MODULE = wintypes.HMODULE()
MODULE_PATH = ctypes.create_unicode_buffer(2048)
SYMBOL_STORAGE = ctypes.create_string_buffer(ctypes.sizeof(SymbolInfo) + 1024)
SYMBOL = ctypes.cast(SYMBOL_STORAGE, ctypes.POINTER(SymbolInfo))
SYMBOL.contents.SizeOfStruct = ctypes.sizeof(SymbolInfo)
SYMBOL.contents.MaxNameLen = 1024
DISPLACEMENT = ctypes.c_ulonglong()
CAPTURED = False


def write(text: str) -> None:
    os.write(LOG_FD, text.encode("utf-8", errors="replace"))


def describe(address: int) -> str:
    module_text = "unknown"
    MODULE.value = None
    if kernel.GetModuleHandleExW(0x6, address, ctypes.byref(MODULE)):
        kernel.GetModuleFileNameW(MODULE, MODULE_PATH, len(MODULE_PATH))
        module_text = MODULE_PATH.value.rsplit("\\", 1)[-1]
        module_text += f"+0x{address - int(MODULE.value or 0):x}"
    symbol_text = ""
    if SYMBOLS_READY and dbghelp.SymFromAddr(
        PROCESS, address, ctypes.byref(DISPLACEMENT), SYMBOL,
    ):
        name = ctypes.string_at(
            ctypes.addressof(SYMBOL_STORAGE) + SymbolInfo.Name.offset,
            SYMBOL.contents.NameLen,
        ).decode("utf-8", errors="replace")
        symbol_text = f" {name}+0x{DISPLACEMENT.value:x}"
    return f"0x{address:016x} {module_text}{symbol_text}"


@CALLBACK
def exception_handler(pointers):
    global CAPTURED, SYMBOLS_READY
    record = pointers.contents.record.contents
    if record.code != PROCESS_HEAP_CORRUPTION or CAPTURED:
        return 0
    CAPTURED = True
    write("\nHEAP CORRUPTION 0xc0000374: capturing one stack; exception continues unchanged\n")
    try:
        # 先收集返回地址，再做本机符号解析；每帧立即写出以保留部分结果。
        count = kernel.RtlCaptureStackBackTrace(0, MAX_FRAMES, STACK, None)
        write(f"frames={count}\n")
        write("exception " + describe(int(record.address or 0)) + "\n")
        for index in range(count):
            write(f"{index:02d} " + describe(int(STACK[index] or 0)) + "\n")
        if LATE_SYMBOLS:
            write("RAW STACK SAVED; attempting local symbols\n")
            SYMBOLS_READY = bool(dbghelp.SymInitializeW(PROCESS, str(LOCAL_SYMBOLS), True))
            write(f"late_symbols_ready={SYMBOLS_READY}\n")
            if SYMBOLS_READY:
                for index in range(count):
                    write(f"{index:02d} " + describe(int(STACK[index] or 0)) + "\n")
        write("END NATIVE STACK\n")
    except Exception as exc:
        write(f"native capture unavailable: {type(exc).__name__}\n")
    return 0


HANDLER = kernel.AddVectoredExceptionHandler(1, exception_handler)
if not HANDLER:
    raise ctypes.WinError(ctypes.get_last_error())
write(f"symbols_ready={SYMBOLS_READY}; symbol_struct_size={ctypes.sizeof(SymbolInfo)}\n")


import pytest


class NativeSymbolsPlugin:
    def pytest_collection_modifyitems(self, config, items):
        if FOCUS_SLICE:
            removed = items[2:]
            items[:] = items[:2]
            config.hook.pytest_deselected(items=removed)

    def pytest_collection_finish(self, session):
        refreshed = SYMBOLS_READY and bool(dbghelp.SymRefreshModuleList(PROCESS))
        write(f"collection={len(session.items)}; modules_refreshed={refreshed}\n")

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        yield
        if FOCUS_SLICE:
            write(f"GC_BEFORE {item.nodeid}\n")
            gc.collect()
            write(f"GC_AFTER {item.nodeid}\n")


if __name__ == "__main__":
    import pytest

    try:
        result = pytest.main([
            "-q", "tests/test_performance_responsive.py",
            "tests/test_feature_typography.py::test_loaded_feature_pages_refresh_fonts_and_text_constraints",
            "tests/test_feature_typography.py::test_performance_large_font_keeps_bounded_scrollable_content",
        ], plugins=[NativeSymbolsPlugin()])
        write(f"pytest_return={result}\n")
    finally:
        kernel.RemoveVectoredExceptionHandler(HANDLER)
        if SYMBOLS_READY:
            dbghelp.SymCleanup(PROCESS)
        os.close(LOG_FD)
    raise SystemExit(result)
