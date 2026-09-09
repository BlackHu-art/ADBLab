"""按已缓存的 ADB 执行能力选择短查询预算，不发起能力探测。"""

from core.exec import adb_runtime, resolve_adb_program


def query_timeout(
    device_id: str, fast: float, native: float = 15.0, *, adb_path: str | None = None,
) -> float:
    """就绪直连保留紧预算，其他路径容纳原生启动；调用方仍须限制剩余总预算。

    此处只读当前能力，不保证实际执行后端；能力变化后的准入由执行器负责，
    不能据此重放失败请求，也不能延长调用方已经建立的截止时间。
    """
    runtime = adb_runtime()
    if runtime is not None and runtime.can_shell_fast(
        resolve_adb_program() if adb_path is None else adb_path, device_id,
    ):
        return fast
    return max(fast, native)
