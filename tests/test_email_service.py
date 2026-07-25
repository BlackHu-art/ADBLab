import logging
from pathlib import Path

import pytest

from core.mail.email_service import EmailService, MailConfigurationError, _load_mail_config
from core.mail.email_task import GetRandomEmailTask


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self._responses.pop(0))


def _config(sign="test-sign"):
    return {"enabled": True, "service": {"sign": sign}}


def test_mail_config_requires_user_scoped_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("ADBLAB_MAIL_SIGN", raising=False)
    monkeypatch.setenv("ADBLAB_MAIL_CONFIG", str(tmp_path / "missing.yaml"))

    with pytest.raises(MailConfigurationError):
        _load_mail_config()


def test_email_service_applies_timeout_and_redacts_runtime_values(caplog):
    account = "anonymous@example.invalid"
    email_id = "message-id"
    code = "654321"
    body = f"verification code {code}"
    sign = "test-sign-material"
    session = _FakeSession(
        [
            {"status": 0, "data": {"account": account}},
            {"status": 0, "data": {"total": 1, "rows": [{"id": email_id}]}},
            {"status": 0, "data": {"text_body": body}},
        ]
    )
    service = EmailService(config=_config(sign), session=session, timeout=(1.0, 2.0))

    with caplog.at_level(logging.INFO):
        random_result = service.get_random_email()
        list_result = service.get_email_list()
        service.email_id = list_result["data"]["rows"][0]["id"]
        extracted = service.get_email_detail()

    assert random_result["data"]["account"] == account
    assert extracted == code
    assert all(call[1]["timeout"] == (1.0, 2.0) for call in session.calls)
    logged = caplog.text
    for sensitive in (account, email_id, code, body, sign, service._fingerprint):
        assert sensitive not in logged


def test_email_task_emits_values_without_putting_them_in_logs(monkeypatch):
    account = "anonymous@example.invalid"
    code = "123456"

    class FakeEmailService:
        def __init__(self):
            self.email_id = None

        def get_random_email(self):
            return {"status": 0, "data": {"account": account}}

        def get_email_list(self):
            return {"data": {"total": 1, "rows": [{"id": "message-id"}]}}

        def get_email_detail(self):
            return code

    monkeypatch.setattr("core.mail.email_task.EmailService", FakeEmailService)
    task = GetRandomEmailTask()
    logs = []
    accounts = []
    codes = []
    task.signals.log_signal.connect(lambda level, message: logs.append((level, message)))
    task.signals.email_updated.connect(accounts.append)
    task.signals.vercode_updated.connect(codes.append)

    task.run()

    assert accounts == [account]
    assert codes == [code]
    rendered_logs = "\n".join(message for _, message in logs)
    assert account not in rendered_logs
    assert code not in rendered_logs
    assert "message-id" not in rendered_logs


def test_mail_config_is_loaded_from_explicit_user_path(tmp_path):
    config_path = Path(tmp_path, "mail.yaml")
    config_path.write_text(
        "enabled: true\nservice:\n  sign: test-sign\n",
        encoding="utf-8",
    )

    loaded = _load_mail_config(config_path)

    assert loaded["enabled"] is True
    assert loaded["service"]["sign"] == "test-sign"
