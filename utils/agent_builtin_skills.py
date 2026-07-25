"""项目内置技能集合。"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .agent_skill_gateway import AgentSkillGateway, SkillError


def _skill_system_ping(_payload):
    return {"message": "pong"}


def _skill_file_exists(payload):
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise SkillError("INVALID_INPUT", "path is required")
    return {"exists": os.path.exists(path)}


def _skill_file_sha256(payload):
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise SkillError("INVALID_INPUT", "path is required")
    target = Path(path)
    if not target.exists():
        raise SkillError("INVALID_INPUT", "path does not exist")
    if not target.is_file():
        raise SkillError("INVALID_INPUT", "path is not a regular file")
    # 内置技能只返回文本摘要，避免泄露文件内容。
    import hashlib

    sha = hashlib.sha256()
    with target.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            sha.update(chunk)
    return {"sha256": sha.hexdigest(), "path": str(target)}


def create_default_gateway() -> AgentSkillGateway:
    """创建并返回默认技能网关实例。"""
    gateway = AgentSkillGateway()
    for name, skill in _default_skills().items():
        gateway.register(name, skill)
    return gateway


def _default_skills() -> dict[str, Callable[..., dict]]:
    return {
        "system.ping": _skill_system_ping,
        "file.exists": _skill_file_exists,
        "file.sha256": _skill_file_sha256,
    }
