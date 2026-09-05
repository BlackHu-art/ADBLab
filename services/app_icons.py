"""通过临时设备端 helper 读取真实 Drawable；不安装应用，也不猜测 APK 内部路径。"""

from __future__ import annotations

import base64
import binascii
import logging
import shlex
import struct
import uuid
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

from core.exec import CommandRunner
from utils.adb_values import normalize_android_package
from utils.resource_path import resource_path

MAX_BATCH_SIZE = 12
ICON_SIZE = 96
MAX_PNG_BYTES = 256 * 1024
_MAX_ENCODED_BYTES = 4 * ((MAX_PNG_BYTES + 2) // 3)
_MAX_OUTPUT_BYTES = MAX_BATCH_SIZE * (_MAX_ENCODED_BYTES + 270)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ERRORS = {
    "NOT_FOUND": "当前用户未安装此应用",
    "CONTEXT_UNAVAILABLE": "设备不支持读取应用图标",
    "RENDER_FAILED": "应用图标渲染失败",
    "TOO_LARGE": "应用图标超过大小限制",
    "USER_CHANGED": "设备用户已切换，请刷新应用列表",
}


def _decode_png(encoded: str) -> bytes:
    """在交给 GUI 解码前检查固定画布、块校验及有界解压，拒绝伪 PNG 和解压炸弹。"""
    if len(encoded) > _MAX_ENCODED_BYTES:
        raise ValueError("图标过大")
    png = base64.b64decode(encoded, validate=True)
    if len(png) > MAX_PNG_BYTES or not png.startswith(_PNG_SIGNATURE):
        raise ValueError("图标格式无效")
    offset = len(_PNG_SIGNATURE)
    compressed = bytearray()
    channels = 0
    seen_data = False
    ended_data = False
    while offset + 12 <= len(png):
        size = struct.unpack_from(">I", png, offset)[0]
        end = offset + 12 + size
        if end > len(png):
            raise ValueError("图标块不完整")
        kind = png[offset + 4 : offset + 8]
        data = png[offset + 8 : end - 4]
        checksum = struct.unpack_from(">I", png, end - 4)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != checksum:
            raise ValueError("图标校验失败")
        if offset == len(_PNG_SIGNATURE) and kind != b"IHDR":
            raise ValueError("缺少图标头")
        if kind == b"IHDR":
            if channels or size != 13:
                raise ValueError("图标头无效")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if (
                (width, height) != (ICON_SIZE, ICON_SIZE)
                or depth != 8
                or not channels
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                raise ValueError("图标画布无效")
        elif kind == b"IDAT":
            if ended_data:
                raise ValueError("图标数据顺序无效")
            seen_data = True
            compressed.extend(data)
        elif kind == b"IEND":
            if size or end != len(png) or not seen_data:
                raise ValueError("图标结尾无效")
            row_size = ICON_SIZE * channels + 1
            expected = ICON_SIZE * row_size
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(compressed, expected + 1)
            if (
                len(pixels) != expected
                or not decoder.eof
                or decoder.unused_data
                or decoder.unconsumed_tail
                or any(pixels[index] > 4 for index in range(0, expected, row_size))
            ):
                raise ValueError("图标像素无效")
            return png
        else:
            if not kind.isalpha() or not kind[0] & 0x20:
                raise ValueError("不支持的图标块")
            ended_data = seen_data
        offset = end
    raise ValueError("图标不完整")


def _parse_output(output: str, packages: Sequence[str]) -> dict[str, tuple[bytes, str]]:
    """只接受本批包名的一次结果；协议损坏不会退化为任意设备输出展示。"""
    failure = {package: (b"", "设备图标响应无效") for package in packages}
    if len(output) > _MAX_OUTPUT_BYTES or not output.isascii():
        return failure
    results: dict[str, tuple[bytes, str]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            return failure
        kind, package, payload = parts
        if package not in failure or package in results or kind not in {"ICON", "ERROR"}:
            return failure
        if kind == "ERROR":
            results[package] = (b"", _ERRORS.get(payload, "应用图标读取失败"))
        else:
            try:
                results[package] = (_decode_png(payload), "")
            except (ValueError, binascii.Error, zlib.error, struct.error):
                results[package] = (b"", "应用图标数据无效")
    return {package: results.get(package, failure[package]) for package in packages}


def load_app_icons(
    device_id: str,
    packages: Sequence[str],
    cancelled: Callable[[], bool],
    emit: Callable[[str, bytes, str], None],
) -> None:
    """在 worker 中读取最多 12 个图标，逐包回报结果；取消不再投递，但仍清理远端文件。

    每条命令都有超时，取消在命令边界生效。清理使用本次生成的精确路径；未确认清理成功
    时返回失败并写无标识日志，不将原始设备错误、本机路径或设备标识带入界面。
    """
    requested = list(dict.fromkeys(packages))
    if not requested or cancelled():
        return
    results: dict[str, tuple[bytes, str]] = {}
    safe = []
    for package in requested:
        try:
            # Android 框架自身使用单段包名 android，其余包名沿用既有动态值校验。
            if package != "android" and normalize_android_package(package) != package:
                raise ValueError("包名含多余空白")
        except ValueError:
            results[package] = (b"", "包名格式无效")
        else:
            safe.append(package)
    if len(requested) > MAX_BATCH_SIZE:
        results = {package: (b"", "每批最多读取 12 个图标") for package in requested}
        safe = []
    if not device_id or len(device_id) > 1024 or any(
        char.isspace() or ord(char) < 32 for char in device_id
    ):
        results = {package: (b"", "设备目标无效") for package in requested}
        safe = []
    if safe and not cancelled():
        results.update(_load_batch(device_id, safe, cancelled))
    for package in requested:
        if cancelled():
            return
        png, error = results.get(package, (b"", "应用图标读取失败"))
        emit(package, png, error)


def _load_batch(
    device_id: str, packages: list[str], cancelled: Callable[[], bool]
) -> dict[str, tuple[bytes, str]]:
    failure = {package: (b"", "应用图标读取失败") for package in packages}
    helper = Path(resource_path("resources/app-icon-helper.jar"))
    if not helper.is_file():
        return {package: (b"", "应用图标组件缺失") for package in packages}
    remote = f"/data/local/tmp/adblab-icons-{uuid.uuid4().hex}.jar"
    target = shlex.quote(remote)
    adb = ["adb", "-s", device_id]
    results = failure
    try:
        pushed = CommandRunner.run([*adb, "push", str(helper), remote], timeout=8)
        if not pushed.success:
            results = {package: (b"", "应用图标组件传输失败") for package in packages}
        elif not cancelled():
            arguments = " ".join(shlex.quote(package) for package in packages)
            # 设备端先把动态代码改为只读，再截断 stdout，避免主机捕获无界输出。
            script = (
                f"{{ chmod 400 {target} && CLASSPATH={target} "
                f"app_process / com.adblab.icons.Main {arguments}; }} "
                f"2>/dev/null | head -c {_MAX_OUTPUT_BYTES + 1}"
            )
            result = CommandRunner.run([*adb, "shell", script], timeout=20)
            if result.success and not cancelled():
                results = _parse_output(result.output, packages)
    except Exception:
        # 外部执行边界的异常只传播固定错误；finally 仍处理可能已部分传输的文件。
        results = failure
    finally:
        try:
            removed = CommandRunner.run([*adb, "shell", f"rm -f -- {target}"], timeout=5)
            cleaned = removed.success
        except Exception:
            cleaned = False
        if not cleaned:
            logging.getLogger(__name__).warning("应用图标临时文件清理失败")
            results = {package: (b"", "应用图标临时文件清理失败") for package in packages}
    return results
