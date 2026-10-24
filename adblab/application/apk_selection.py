"""定义同步 APK 选择契约，业务调用方无需依赖文件框实现。"""

from typing import Protocol


class ApkFilePicker(Protocol):
    """保留路径原文、顺序和重复项；异常向调用方传播，不伪装为取消。"""

    def select_one(self) -> str | None:
        """同步返回单个文件路径；用户取消时返回 None，不校验文件。"""
        ...

    def select_many(self) -> tuple[str, ...]:
        """同步返回文件路径序列；用户取消时返回空元组，不校验文件。"""
        ...
