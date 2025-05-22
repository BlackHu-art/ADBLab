# email_task.py
from PySide6.QtCore import QObject, Signal, QRunnable
import time
from datetime import datetime

import requests

from common.mail.tempEmailService import EmailService


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
        """Execute email verification code retrieval process"""
        try:
            # Initialization phase
            email_service = EmailService()
            self.log("INFO", "🔄 Starting email verification process")

            # 1. Get temporary email account
            self.log("INFO", "📩 Requesting temporary email account...")
            random_email_data = email_service.get_random_email()

            if not (random_email_data and random_email_data.get("data", {}).get("account")):
                self.log("ERROR", "❌ Failed to get email account: Invalid server response")
                return

            email_account = random_email_data["data"]["account"]
            self.log("SUCCESS", f"📧 Temporary email obtained: {email_account}")
            self.signals.email_updated.emit(email_account)

            # 2. Email polling phase
            self.log("INFO", "🔍 Checking inbox (max 10 attempts)...")
            for attempt in range(1, 11):
                self.log("DEBUG", f"Attempt #{attempt}: Requesting email list")
                
                email_list_data = email_service.get_email_list()
                if not email_list_data:
                    self.log("WARNING", f"⚠️ Attempt {attempt}: Email list request failed")
                    continue

                total_emails = email_list_data.get("data", {}).get("total", 0)
                self.log("DEBUG", f"Server response: Found {total_emails} emails")

                if total_emails >= 1:
                    if rows := email_list_data.get("data", {}).get("rows", []):
                        email_service.emailId = rows[0].get("id")
                        self.log("SUCCESS", f"📨 Target email found (ID: {email_service.emailId})")
                        break
                
                # Progress tracking
                remaining = 10 - attempt
                self.log("INFO", 
                    f"⏳ Waiting for email... (Remaining attempts: {remaining})")
                for i in range(10, 0, -1):
                    time.sleep(1)
                    if i % 5 == 0:  # Update countdown every 5 seconds
                        self.log("DEBUG", f"Countdown: {i}s")

            else:
                self.log("ERROR", "⌛ Email retrieval timeout (10 attempts failed)")
                return

            # 3. Verification code extraction
            self.log("INFO", "🔢 Extracting verification code...")
            verification_code = email_service.get_email_detail()
            
            if verification_code:
                self.log("SUCCESS", 
                    f"✅ Verification code retrieved\n{'═'*30}\n║ Code: {verification_code:^24} ║\n{'═'*30}")
                self.signals.vercode_updated.emit(verification_code)
            else:
                self.log("ERROR", "❌ Failed to extract verification code")

        except requests.exceptions.RequestException as e:
            self.log("ERROR", f"🌐 Network error: {e}")
        except Exception as e:
            self.log("CRITICAL", f"‼️ System failure: {str(e)}")
            raise  # Preserve original exception stack