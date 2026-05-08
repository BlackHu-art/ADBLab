from collections.abc import Callable


class BatchOperationTracker:
    """统一管理批量设备操作的计数与汇总回调"""

    def __init__(self, total: int, op_name: str, on_summary: Callable[[str, bool, str], None]):
        self.total = total
        self.finished = 0
        self.success = 0
        self.op_name = op_name
        self._on_summary = on_summary

    def record(self, success: bool) -> str:
        """记录一次操作结果，返回进度字符串。全部完成时自动触发汇总回调。"""
        self.finished += 1
        if success:
            self.success += 1
        progress = f"({self.finished}/{self.total})"

        if self.finished == self.total:
            failed = self.total - self.success
            summary = (
                f"🎯 {self.op_name} completed; "
                f"✅ Success: {self.success}; "
                f"❌ Failed: {failed}"
            )
            self._on_summary(self.op_name, True, summary)
        return progress
