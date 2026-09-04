"""主窗口内嵌功能页及其会话生命周期基础设施。"""

from __future__ import annotations

from .about import AboutPanel
from .base import FeatureSessionKey, FeatureSessionRegistry

__all__ = ["AboutPanel", "FeatureSessionKey", "FeatureSessionRegistry"]
