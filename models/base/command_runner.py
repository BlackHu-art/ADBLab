"""兼容垫片：短命令执行入口已迁至 ``core.exec``（ADR-0005 Step A）。

新代码请直接 ``from core.exec import CommandRunner, CommandResult, CF``；
本模块仅为存量导入保留 re-export，行为与历史版本一致。
"""

from core.exec import CF, CommandResult, CommandRunner  # noqa: F401

__all__ = ["CF", "CommandResult", "CommandRunner"]
