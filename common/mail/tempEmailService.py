#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
 @author      :  Frankie
 @description :  
 @time        :    10:18
"""
import datetime
import random
import string
import re
import time

import requests
from common.logger.logTool import logger
from common.yamlTool import YamlTool


class HttpRequest:
    """通用 HTTP 请求封装类"""

    def __init__(self, base_url):
        self.session = requests.Session()
        self.base_url = base_url

    def post(self, endpoint, headers=None, payload=None):
        """
        发送 POST 请求
        :param endpoint: 接口路径
        :param headers: 请求头
        :param payload: 请求体数据
        :return: 响应 JSON 数据或 None
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            logger.info(f"Sending POST request to {url} with payload: {payload}")
            response = self.session.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Response: {response.json()}")
            return response.json()
        except requests.RequestException as e:
            logger.error(f"HTTP POST request failed: {e}")
            return None


class EmailService(HttpRequest):
    """服务类，继承 HttpRequest 封装 AMZ123 接口请求"""

    BASE_URL = "https://api.amz123.com/toolbox/v1/temp_email"

    def __init__(self):
        super().__init__(self.BASE_URL)
        self.common_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.amz123.com",
            "referer": "https://www.amz123.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
            # "fingerprint": "4794d495216cb6f6f1c31bc4fcbfc770"
        }
        self.account = None
        self.emailId = None

    def get_random_email(self):
        """
        获取随机邮箱账号
        """
        url = f"{self.BASE_URL}/rand_account"
        retry = False

        while True:
            try:
                headers = {
                    **self.common_headers,
                    "fingerprint": str(
                        YamlTool("common/mail/mail.yaml").get_nested_value("userRegisterInfoPro", "fingerprint"))
                }

                logger.info(f"Requesting random email from {url}")
                response = self.session.post(url, headers=headers, json={})
                response.raise_for_status()

                data = response.json()
                logger.info(f"Response: {data}")

                # 判断响应结果，按需处理
                if data.get("status") == 0:  # 假设 0 表示成功
                    account = data.get("data", {}).get("account")
                    if account:
                        logger.info(f"Random Email Account: {account}")
                        self.account = account
                        YamlTool("common/mail/mail.yaml").update_nested_value("userRegisterInfoPro", "account",
                                                                              self.account)
                    else:
                        logger.error("Account not found in response data")
                    return data
                elif data.get("status") == 104 and not retry:  # 请求频繁，请稍后重试
                    logger.warning(f"Status 104: {data.get('info', 'Unknown error')}. Retrying...")
                    self.update_fingerprint()
                    retry = True
                else:
                    logger.error(f"API Error: {data.get('info', 'Unknown error')}")
                    return None

            except requests.RequestException as e:
                logger.error(f"Failed to get random email: {e}")
                return None

    def update_fingerprint(self):
        """
        随机生成 fingerprint 并更新
        """
        # 生成一个固定长度的 fingerprint（与原始示例一致，长度为36）
        new_fingerprint = ''.join(random.choices(string.ascii_lowercase + string.digits, k=36))

        # 更新 YAML 中的 fingerprint 值
        YamlTool("common/mail/mail.yaml").update_nested_value("userRegisterInfoPro", "fingerprint", new_fingerprint)
        logger.info(f"Fingerprint updated to: {new_fingerprint}")

    def get_email_list(self):
        """获取邮箱列表"""
        url = f"{self.BASE_URL}/list"
        headers = {
            **self.common_headers,
            "app-id": "3",
            "project-id": "toolbox",
            "sign": "41a562316ccfe7f9e0e8ff7ed5f574e8",
            "timestamp": str(int(datetime.datetime.now().timestamp())),
        }
        data = {
            "account": self.account,
            "page": {"sorts": [{"condition": "date", "order": -1}]}
        }
        try:
            logger.info(f"Requesting email list for account: {self.account}")
            response = self.session.post(url, headers=headers, json=data)
            response.raise_for_status()
            logger.info(f"Response: {response.json()}")
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get email list: {e}")
            return None

    def extract_verification_code(self, text_body):
        """
        从邮件正文中提取四位数字验证码，优先匹配“验证码”或“code”等上下文关键词周围的数字。
        """
        # 优先匹配关键词前后有数字的情况
        keyword_patterns = [
            r"(?:验证码|verification\s*code|code)[^\d]{0,10}(\d{4,6})",  # 中文验证码、英文 verification code
            r"(\d{4,6})[^\d]{0,10}(?:验证码|verification\s*code|code)",  # 数字在前的情况
        ]

        for pattern in keyword_patterns:
            match = re.search(pattern, text_body, re.IGNORECASE)
            if match:
                return match.group(1)

        # 如果没有关键词相关匹配，退而求其次抓第一个 4~6 位纯数字
        match = re.search(r"\b\d{4,6}\b", text_body)
        if match:
            return match.group(0)

        return None


    def get_email_detail(self,):
        """
        获取邮箱详情，并提取验证码
        :return: 提取到的验证码字符串，如果失败返回 None
        """
        url = f"{self.BASE_URL}/detail"
        payload = {"id": self.emailId, "account": self.account}
        try:
            logger.info(f"Requesting email details for ID: {self.emailId}, Account: {self.account}")
            response = self.session.post(url, headers=self.common_headers, json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info(f"Response received successfully.")

            # 校验响应状态
            if data.get("status") != 0:
                logger.error(f"Error in response: {data.get('info')}")
                return None

            # 提取 text_body 并解析验证码
            text_body = data.get("data", {}).get("text_body", "")
            if text_body:
                logger.info(f"Text Body:\n{text_body}")
                code = self.extract_verification_code(text_body)
                if code:
                    logger.info(f"Verification Code Extracted: {code}")
                    YamlTool("common/mail/mail.yaml").update_nested_value("userRegisterInfoPro", "verifyCode", code)
                    return code
                else:
                    logger.warning("No verification code found in the email body.")
                    return None
            else:
                logger.warning("No text body found in the email data.")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to get email details: {e}")
            return None

    def fetch_and_process_email(self):
        """
        执行以下步骤：
        1. 调用 get_random_email 获取随机邮箱账号。
        2. 循环调用 get_email_list，最多6次，每次间隔10秒，直到响应数据中的 "total": 1。
        3. 解析响应数据获取邮件ID。
        4. 使用获取到的邮件ID调用 get_email_detail。
        """
        # Step 1: 获取随机邮箱账号
        result = self.get_random_email()
        if not result or result.get("status") != 0:
            logger.error("Failed to get random email account.")
            return

        # Step 2: 循环调用 get_email_list
        for attempt in range(6):
            email_list = self.get_email_list()
            if email_list and email_list.get("data", {}).get("total") == 1:
                rows = email_list.get("data", {}).get("rows", [])
                if rows:
                    self.emailId = rows[0].get("id")
                    logger.info(f"Found email with ID: {self.emailId}")
                    break
            logger.info(f"Attempt {attempt + 1}: No emails found yet. Retrying in 10 seconds...")
            time.sleep(10)

        if not self.emailId:
            logger.error("Failed to find any emails after 6 attempts.")
            return

        # Step 3: 获取邮件验证码
        detail = self.get_email_detail()
        if detail:
            logger.info(f"Email detail fetched successfully: {detail}")
        else:
            logger.error("Failed to fetch email detail.")


if __name__ == "__main__":
    email_service = EmailService()
    email_service.fetch_and_process_email()
