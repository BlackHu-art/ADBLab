"""通过后台任务获取临时邮箱及验证码。"""
import time
from datetime import datetime

import requests
from PySide6.QtCore import QObject, QRunnable, Signal

from core.mail.email_service import EmailService, MailConfigurationError


class EmailSignals(QObject):
    log_signal = Signal(str, str)
    email_updated = Signal(str)
    vercode_updated = Signal(str)


class GetRandomEmailTask(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = EmailSignals()

    def timestamp(self):
        return datetime.now().strftime("%H:%M:%S")

    def log(self, level, msg):
        self.signals.log_signal.emit(level, f"[{self.timestamp()}] {msg}")

    def run(self):
        """执行临时邮箱申请、轮询和验证码提取流程。"""
        try:
            # 初始化外部服务客户端后再输出用户可见进度。
            email_service = EmailService()
            self.log("INFO", "🔄 Starting email verification process")

            # 首先申请临时邮箱账号。
            self.log("INFO", "📩 Requesting temporary email account...")
            random_email_data = email_service.get_random_email()

            if not (random_email_data and random_email_data.get("data", {}).get("account")):
                self.log("ERROR", "❌ Failed to get email account: Invalid server response")
                return

            email_account = random_email_data["data"]["account"]
            self.log("SUCCESS", "📧 Temporary email obtained")
            self.signals.email_updated.emit(email_account)

            # 邮件到达时间不可预测，因此使用有上限的轮询避免任务永久占用线程。
            self.log("INFO", "🔍 Checking inbox (max 10 attempts)...")
            for attempt in range(1, 16):
                self.log("DEBUG", f"Attempt #{attempt}: Requesting email list")
                email_list_data = email_service.get_email_list()
                if not email_list_data:
                    time.sleep(0.5)
                    continue
                total_emails = email_list_data.get("data", {}).get("total", 0)
                if total_emails >= 1:
                    if rows := email_list_data.get("data", {}).get("rows", []):
                        email_service.email_id = rows[0].get("id")
                        self.log("SUCCESS", "Email found")
                        break
                time.sleep(1.0)

            else:
                self.log("ERROR", "Email retrieval timeout (16 attempts failed)")
                return

            # 邮件到达后再读取正文并提取验证码。
            self.log("INFO", "🔢 Extracting verification code...")
            verification_code = email_service.get_email_detail()

            if verification_code:
                self.log("SUCCESS", "✅ Verification code retrieved")
                self.signals.vercode_updated.emit(verification_code)
            else:
                self.log("ERROR", "❌ Failed to extract verification code")

        except MailConfigurationError:
            self.log("ERROR", "Temporary mail is not configured or is disabled")
        except requests.exceptions.RequestException as e:
            self.log("ERROR", f"🌐 Network error: {type(e).__name__}")
        except Exception as e:
            self.log("CRITICAL", f"‼️ Temporary-mail failure: {type(e).__name__}")
