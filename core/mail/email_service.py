"""提供注重隐私保护的可选临时邮箱服务适配器。"""

from __future__ import annotations

import datetime
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import requests
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from utils.user_data import user_config_path

logger = logging.getLogger("adblab.mail")

_yaml = YAML(typ="safe")
_DEFAULT_TIMEOUT = (5.0, 15.0)
_MAIL_CONFIG_ENV = "ADBLAB_MAIL_CONFIG"
_MAIL_SIGN_ENV = "ADBLAB_MAIL_SIGN"


class MailConfigurationError(RuntimeError):
    """表示可选邮件集成尚未完成安全配置。"""


def mail_config_path() -> Path:
    """返回显式覆盖路径或当前用户的配置路径。"""
    override = os.environ.get(_MAIL_CONFIG_ENV, "").strip()
    return Path(override).expanduser() if override else Path(user_config_path("mail.yaml"))


def _load_mail_config(path: Path | None = None) -> dict[str, Any]:
    """只加载用户范围配置，禁止读取源码目录中的 mail.yaml。"""
    sign_override = os.environ.get(_MAIL_SIGN_ENV, "").strip()
    if sign_override:
        return {"enabled": True, "service": {"sign": sign_override}}

    config_path = path or mail_config_path()
    if not config_path.is_file():
        raise MailConfigurationError(
            "Temporary mail is not configured. Configure it in the per-user settings directory."
        )
    try:
        with config_path.open(encoding="utf-8") as f:
            data = _yaml.load(f) or {}
    except (OSError, TypeError, ValueError, YAMLError) as exc:
        raise MailConfigurationError("Temporary mail configuration could not be loaded.") from exc
    if not isinstance(data, dict):
        raise MailConfigurationError("Temporary mail configuration must be a YAML mapping.")
    if data.get("enabled") is not True:
        raise MailConfigurationError("Temporary mail integration is disabled.")
    service = data.get("service")
    sign = service.get("sign") if isinstance(service, dict) else None
    if not isinstance(sign, str) or not sign.strip():
        raise MailConfigurationError("Temporary mail request signing material is missing.")
    return data


class HttpRequest:
    """封装带强制连接和读取超时的 HTTP 请求边界。"""

    def __init__(
        self,
        base_url: str,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = _DEFAULT_TIMEOUT,
    ):
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def post(self, endpoint: str, *, headers=None, payload=None):
        endpoint = endpoint.lstrip("/")
        url = f"{self.base_url}/{endpoint}"
        try:
            logger.info("Temporary-mail request started: %s", endpoint)
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            logger.info("Temporary-mail request completed: %s", endpoint)
            return data if isinstance(data, dict) else None
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.error(
                "Temporary-mail request failed for %s: %s",
                endpoint,
                type(exc).__name__,
            )
            return None


class EmailService(HttpRequest):
    """使用用户范围配置和脱敏日志的可选临时邮箱服务。"""

    BASE_URL = "https://api.amz123.com/toolbox/v1/temp_email"

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        config_path: Path | None = None,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = _DEFAULT_TIMEOUT,
    ):
        loaded = config if config is not None else _load_mail_config(config_path)
        if not isinstance(loaded, dict) or loaded.get("enabled") is not True:
            raise MailConfigurationError("Temporary mail integration is disabled.")
        service = loaded.get("service")
        sign = service.get("sign") if isinstance(service, dict) else None
        if not isinstance(sign, str) or not sign.strip():
            raise MailConfigurationError("Temporary mail request signing material is missing.")

        super().__init__(self.BASE_URL, session=session, timeout=timeout)
        self._sign = sign.strip()
        self._fingerprint = secrets.token_hex(18)
        self.common_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.amz123.com",
            "referer": "https://www.amz123.com/",
        }
        self.account: str | None = None
        self.email_id: str | None = None

    def _signed_headers(self) -> dict[str, str]:
        return {
            **self.common_headers,
            "app-id": "3",
            "project-id": "toolbox",
            "sign": self._sign,
            "timestamp": str(int(datetime.datetime.now().timestamp())),
        }

    def get_random_email(self):
        for attempt in range(2):
            data = self.post(
                "rand_account",
                headers={**self.common_headers, "fingerprint": self._fingerprint},
                payload={},
            )
            if not data:
                return None
            if data.get("status") == 0:
                account = data.get("data", {}).get("account")
                if isinstance(account, str) and account:
                    self.account = account
                    return data
                logger.error("Temporary-mail response did not include an account.")
                return None
            if data.get("status") == 104 and attempt == 0:
                self.update_fingerprint()
                continue
            logger.error("Temporary-mail service returned a non-success status.")
            return None
        return None

    def update_fingerprint(self):
        """轮换内存中的请求指纹，不持久化也不写入日志。"""
        self._fingerprint = secrets.token_hex(18)

    def get_email_list(self):
        if not self.account:
            return None
        payload = {
            "account": self.account,
            "page": {"sorts": [{"condition": "date", "order": -1}]},
        }
        return self.post("list", headers=self._signed_headers(), payload=payload)

    @staticmethod
    def extract_verification_code(text_body: str):
        keyword_patterns = [
            r"(?:验证码|verification\s*code|code)[^\d]{0,10}(\d{4,6})",
            r"(\d{4,6})[^\d]{0,10}(?:验证码|verification\s*code|code)",
        ]
        for pattern in keyword_patterns:
            match = re.search(pattern, text_body, re.IGNORECASE)
            if match:
                return match.group(1)
        match = re.search(r"\b\d{4,6}\b", text_body)
        return match.group(0) if match else None

    def get_email_detail(self):
        if not self.account or not self.email_id:
            return None
        data = self.post(
            "detail",
            headers=self._signed_headers(),
            payload={"id": self.email_id, "account": self.account},
        )
        if not data or data.get("status") != 0:
            return None
        text_body = data.get("data", {}).get("text_body", "")
        if not isinstance(text_body, str) or not text_body:
            return None
        return self.extract_verification_code(text_body)

    def fetch_and_process_email(self):
        result = self.get_random_email()
        if not result:
            return None
        for attempt in range(6):
            email_list = self.get_email_list()
            rows = email_list.get("data", {}).get("rows", []) if email_list else []
            if rows:
                self.email_id = rows[0].get("id")
                break
            if attempt < 5:
                time.sleep(10)
        if not self.email_id:
            return None
        return self.get_email_detail()
