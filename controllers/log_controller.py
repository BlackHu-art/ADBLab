# 日志控制器，用于处理日志清空和关闭事件
class LogController:
    def __init__(self, frame):
        self.frame = frame

    def on_clear_log(self, event):
        # 清空日志输出控件
        self.frame.text_output.ClearAll()

    def on_close(self, event):
        # 可在此添加关闭前的清理工作
        event.Skip()
