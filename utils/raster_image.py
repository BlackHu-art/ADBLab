"""在外部图片进入 Qt 插件前按有限签名固定栅格解码器。"""

from collections.abc import Callable
from typing import Any


def raster_image_reader(path: str, factory: Callable[[str], Any]):
    """拒绝 SVG 等未支持格式；文件被替换时也不允许 Qt 回退到其他插件。

    只读取 16 字节签名，不按扩展名决定格式，保留误扩展名栅格图导入。
    调用方负责处理 OSError，并在工作线程进行后续探测、缩放和解码。
    """
    with open(path, "rb") as source:
        header = source.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        format_name = b"png"
    elif header.startswith(b"\xff\xd8\xff"):
        format_name = b"jpeg"
    elif header.startswith(b"BM"):
        format_name = b"bmp"
    elif header.startswith((b"GIF87a", b"GIF89a")):
        format_name = b"gif"
    elif header.startswith((b"II*\x00", b"MM\x00*")):
        format_name = b"tiff"
    elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        format_name = b"webp"
    else:
        raise OSError("Unsupported raster image")
    reader = factory(path)
    reader.setFormat(format_name)
    reader.setAutoDetectImageFormat(False)
    return reader
