"""原子文本写入：临时文件 + os.replace，避免中途失败留下半截文件。"""

from __future__ import annotations

import os
import tempfile


def atomic_write_text(path: str, content: str, *, encoding: str = "utf-8") -> None:
    """把文本先写入同目录临时文件，再原子替换到目标路径。

    目标目录不存在时先创建；写入或替换失败时清理临时文件并重新抛出。
    """

    target = os.path.abspath(path)
    directory = os.path.dirname(target) or os.curdir
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        prefix=".adblab_atomic_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as file:
            file.write(content)
        os.replace(temporary_path, target)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


__all__ = ["atomic_write_text"]
