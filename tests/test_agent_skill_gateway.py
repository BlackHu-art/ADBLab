"""Tests for the PoC skill gateway."""

from __future__ import annotations

from pathlib import Path
import tempfile

from utils.agent_builtin_skills import create_default_gateway
from utils.agent_skill_gateway import AgentSkillGateway, SkillError


def test_gateway_register_and_run_success() -> None:
    gateway = AgentSkillGateway()

    def handler(payload):
        return {"ok": True, "value": payload["value"] * 2}

    gateway.register("double", handler)
    result = gateway.run_skill("double", {"value": 3}, {"request_id": "r1"})

    assert result["ok"] is True
    assert result["name"] == "double"
    assert result["request_id"] == "r1"
    assert result["result"]["value"] == 6


def test_gateway_skill_not_found() -> None:
    gateway = AgentSkillGateway()
    result = gateway.run_skill("missing", {})

    assert result["ok"] is False
    assert result["error"]["code"] == "SKILL_NOT_FOUND"


def test_gateway_invalid_output() -> None:
    gateway = AgentSkillGateway()
    gateway.register("invalid", lambda _: "not-dict")
    result = gateway.run_skill("invalid", {})

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_OUTPUT"


def test_gateway_exception_to_exec_fail() -> None:
    def handler(_):
        raise SkillError("UPPER", "boom")

    gateway = AgentSkillGateway()
    gateway.register("explode", handler)
    result = gateway.run_skill("explode", {})

    assert result["ok"] is False
    assert result["error"]["code"] == "UPPER"


def test_gateway_timeout() -> None:
    def handler(_):
        import time

        time.sleep(0.05)
        return {"ok": True}

    gateway = AgentSkillGateway()
    gateway.register("delay", handler)
    result = gateway.run_skill("delay", {}, {"timeout_ms": 5, "request_id": "t1"})

    assert result["ok"] is False
    assert result["error"]["code"] == "TIMEOUT"


def test_default_skills_ping_exists_sha256() -> None:
    gateway = create_default_gateway()
    ping = gateway.run_skill("system.ping", {})
    assert ping["ok"] is True
    assert ping["result"]["message"] == "pong"

    exists = gateway.run_skill("file.exists", {"path": __file__})
    assert exists["ok"] is True
    assert exists["result"]["exists"] is True

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"abc")
        tmp.flush()
        temp_path = Path(tmp.name)
    try:
        hashed = gateway.run_skill("file.sha256", {"path": str(temp_path)})
        assert hashed["ok"] is True
        assert hashed["result"]["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    finally:
        temp_path.unlink()
