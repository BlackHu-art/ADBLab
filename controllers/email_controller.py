# 此文件为邮件控制器，暂作为占位，可根据需求扩展
class EmailController:
    def __init__(self, frame):
        self.frame = frame

    def on_send_email(self, event):
        self.frame.log_message("INFO", "Send email functionality is not implemented yet.")
