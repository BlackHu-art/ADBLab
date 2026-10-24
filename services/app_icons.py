"""通过临时设备端 helper 读取真实 Drawable；不安装应用，也不猜测 APK 内部路径。"""

from __future__ import annotations

import base64
import binascii
import re
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence

from services.app_metadata import _decode_record
from services.apps.helper import HelperResult as HelperResult
from services.apps.helper import run_app_helper as run_app_helper
from utils.adb_values import normalize_android_package

MAX_BATCH_SIZE = 12
ICON_SIZE = 96
MAX_PNG_BYTES = 256 * 1024
_MAX_ENCODED_BYTES = 4 * ((MAX_PNG_BYTES + 2) // 3)
_MAX_OUTPUT_BYTES = MAX_BATCH_SIZE * (_MAX_ENCODED_BYTES + 270)
_MAX_ICON_METADATA_OUTPUT_BYTES = MAX_BATCH_SIZE * (
    _MAX_ENCODED_BYTES + 4 * ((16 * 1024 + 2) // 3) + 280
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ERRORS = {
    "NOT_FOUND": "当前用户未安装此应用",
    "CONTEXT_UNAVAILABLE": "设备不支持读取应用图标",
    "RENDER_FAILED": "应用图标渲染失败",
    "TOO_LARGE": "应用图标超过大小限制",
    "USER_CHANGED": "设备用户已切换，请刷新应用列表",
    "IDENTITY_CHANGED": "应用或设备配置已变化，请刷新应用列表",
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


def _parse_output(
    output: str, packages: Sequence[str], expected_fingerprints: Mapping[str, str] | None = None,
    expected_user_id: int | None = None,
) -> dict[str, tuple[bytes, str]]:
    """只接受本批包名的一次结果；协议损坏不会退化为任意设备输出展示。"""
    failure = {package: (b"", "设备图标响应无效") for package in packages}
    verified = bool(expected_fingerprints) or expected_user_id is not None
    limit = _MAX_ICON_METADATA_OUTPUT_BYTES if verified else _MAX_OUTPUT_BYTES
    if len(output) > limit or not output.isascii():
        return failure
    results: dict[str, tuple[bytes, str]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) not in {3, 4}:
            return failure
        kind, package = parts[:2]
        if package not in failure or package in results:
            return failure
        if kind == "ERROR":
            if len(parts) != 3:
                return failure
            diagnostic = re.fullmatch(
                r"RENDER_FAILED:(METADATA|LOAD|DRAW|ENCODE):"
                r"(SECURITY|ARGUMENT|STATE|RESOURCE|MEMORY|OTHER)", parts[2],
            )
            # 只透传固定阶段和类别，不能让设备异常正文或堆栈进入界面。
            error = _ERRORS.get(parts[2], "应用图标读取失败")
            if diagnostic:
                error = ("应用图标渲染失败 "
                         f"[{diagnostic[1]}/{diagnostic[2]}]")
            results[package] = (b"", error)
        else:
            if verified:
                if kind != "ICON_META" or len(parts) != 4:
                    return failure
            elif kind != "ICON" or len(parts) != 3:
                return failure
            try:
                if verified:
                    metadata = _decode_record(package, parts[2])
                    if expected_user_id is not None and metadata.user_id != expected_user_id:
                        results[package] = (b"", _ERRORS["USER_CHANGED"])
                        continue
                    expected = (expected_fingerprints or {}).get(package)
                    if expected and metadata.fingerprint != expected:
                        results[package] = (b"", _ERRORS["IDENTITY_CHANGED"])
                        continue
                results[package] = (_decode_png(parts[-1]), "")
            except (ValueError, UnicodeError, binascii.Error, RecursionError,
                    zlib.error, struct.error):
                results[package] = (b"", "应用图标数据无效")
    return {package: results.get(package, failure[package]) for package in packages}


def load_app_icons(
    device_id: str,
    packages: Sequence[str],
    cancelled: Callable[[], bool],
    emit: Callable[[str, bytes, str], None],
    *,
    expected_fingerprints: Mapping[str, str] | None = None,
    expected_user_id: int | None = None,
) -> None:
    """在 worker 中读取最多 12 个图标，逐包回报结果；取消不再投递，但仍清理远端文件。

    传输与渲染支持执行中取消，清理不继承取消。清理使用本次生成的精确路径；未确认清理成功
    时返回失败并写无标识日志，不将原始设备错误、本机路径或设备标识带入界面。
    有预期指纹时，只有同次渲染元数据身份与预期一致才交付 PNG，避免跨调用用户或版本竞态。
    """
    requested = list(dict.fromkeys(packages))
    if not requested or cancelled():
        return
    results: dict[str, tuple[bytes, str]] = {}
    if expected_user_id is not None and (
        type(expected_user_id) is not int or not 0 <= expected_user_id < 2**31
    ):
        for package in requested:
            if cancelled():
                return
            emit(package, b"", "应用用户身份无效，请刷新应用列表")
        return
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
    fingerprints = {}
    for package in safe[:]:
        value = (expected_fingerprints or {}).get(package)
        if value is None or value == "":
            continue
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            fingerprints[package] = value
        else:
            # 非空身份代表调用方要求校验；非法值不能静默降级为无身份图标。
            results[package] = (b"", "应用缓存身份无效，请刷新应用列表")
            safe.remove(package)
    if safe and not cancelled():
        results.update(_load_batch(
            device_id, safe, cancelled, fingerprints or None, expected_user_id,
        ))
    for package in requested:
        if cancelled():
            return
        png, error = results.get(package, (b"", "应用图标读取失败"))
        emit(package, png, error)


def _load_batch(
    device_id: str, packages: list[str], cancelled: Callable[[], bool],
    expected_fingerprints: Mapping[str, str] | None = None,
    expected_user_id: int | None = None,
) -> dict[str, tuple[bytes, str]]:
    verified = bool(expected_fingerprints) or expected_user_id is not None
    limit = _MAX_ICON_METADATA_OUTPUT_BYTES if verified else _MAX_OUTPUT_BYTES
    result = run_app_helper(device_id, packages, cancelled, output_limit=limit,
                            icon_metadata=verified)
    if result.error:
        errors = {
            "MISSING": "应用图标组件缺失",
            "DEPLOY_FAILED": "应用图标组件传输失败",
            "CLEANUP_FAILED": "应用图标临时文件清理失败",
        }
        error = errors.get(result.error, "应用图标读取失败")
        return {package: (b"", error) for package in packages}
    return _parse_output(result.output, packages, expected_fingerprints, expected_user_id)
