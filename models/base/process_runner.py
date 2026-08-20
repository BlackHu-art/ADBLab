"""兼容垫片：长进程执行入口已迁至 ``core.exec``（ADR-0005 Step B）。

新代码请直接 ``from core.exec import ProcessRunner, CREATE_NEW_CONSOLE``；
本模块仅为存量导入保留 re-export，行为与历史版本一致。
"""

from core.exec import CF, CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, ProcessRunner  # noqa: F401

__all__ = ["CREATE_NEW_CONSOLE", "CREATE_NO_WINDOW", "CF", "ProcessRunner"]
