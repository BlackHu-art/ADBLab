"""保存采样开始时的白名单环境快照；元数据失败不改变采集本身的结果。

本模块不接触 Qt 或设备身份。查询由采集子进程提供，文件读取由结果发现线程调用；
每份附件使用随机运行标识命名，避免同秒结果目录被再次使用时覆盖上一轮快照。
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_METADATA_BYTES = 64 * 1024
METADATA_SCHEMA_VERSION = 1
_RUN_ID = re.compile(r"[a-f0-9]{32}")
_PROCESS = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.]*(?::[A-Za-z0-9_.]+)?")
_PROPERTIES = {
    "brand": "ro.product.brand", "model": "ro.product.model",
    "android_version": "ro.build.version.release", "api_level": "ro.build.version.sdk",
    "abis": "ro.product.cpu.abilist",
}
_MONKEY_INTS = {
    "throttle_ms", "seed", "pct_touch", "pct_motion", "pct_trackball", "pct_nav",
    "pct_majornav", "pct_syskeys", "pct_appswitch", "pct_anyevent", "pct_flip", "pct_pinchzoom",
}
_MONKEY_BOOLS = {"ignore_crashes", "ignore_timeouts", "ignore_security", "kill_after_error"}


@dataclass(frozen=True)
class MetadataRead:
    """只交付通过白名单及归属验证的附件路径和版本；异常正文不进入界面。"""

    path: str = ""
    app_version: str = ""
    status: str = "missing"


def metadata_filename(run_id: str) -> str:
    """使用与设备无关的随机标识限定本次产物，拒绝路径片段。"""
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("invalid metadata run identifier")
    return f"performance_metadata_{run_id}.json"


def _text(value: object, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if (not text or text.lower() in {"null", "unknown"} or len(text) > limit
            or any(ord(char) < 32 for char in text)):
        return None
    return text


def _process(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 500 or ".." in value
            or _PROCESS.fullmatch(value) is None):
        raise ValueError("invalid metadata target")
    return value


def _version(raw: str) -> tuple[str | None, int | None]:
    codes = re.findall(r"^\s*versionCode=(\d+)\b", raw, re.MULTILINE)
    names = re.findall(r"^\s*versionName=([^\r\n]*)", raw, re.MULTILINE)
    code = int(codes[0]) if len(codes) == 1 and len(codes[0]) <= 20 else None
    name = _text(names[0]) if len(names) == 1 else None
    return name, code


def _missing(document: dict[str, Any]) -> list[str]:
    missing = [f"device.{key}" for key, value in document["device"].items() if not value]
    for target in document["targets"]:
        for key in ("version_name", "version_code"):
            if target[key] is None:
                missing.append(f"targets.{target['process']}.{key}")
    return missing


def capture_metadata(
    *, query: Callable[[str], str], run_id: str, target_processes: Sequence[str],
    sampling: Mapping[str, object], collector_version: str, captured_at: float | None = None,
) -> dict[str, Any]:
    """先复制参数再顺序查询；缺失或失败只留下未知字段，不保存原始输出及错误。

    调用方负责查询总预算和取消。本函数不重试，也不创建线程；同一包的多个目标进程
    共用一次版本查询，进程集合保持开始时的顺序并去重。
    """
    metadata_filename(run_id)
    processes = tuple(dict.fromkeys(_process(value) for value in target_processes))
    if not processes or len(processes) > 128:
        raise ValueError("invalid metadata target count")
    frozen_sampling = copy.deepcopy(dict(sampling))
    started = time.time() if captured_at is None else captured_at

    def read(command: str) -> str:
        try:
            value = query(command)
            return value if isinstance(value, str) else ""
        except (OSError, ValueError, RuntimeError):
            return ""

    raw_properties = {key: _text(read(f"getprop {prop}")) for key, prop in _PROPERTIES.items()}
    raw_api = raw_properties["api_level"]
    api = int(raw_api) if raw_api and re.fullmatch(r"[0-9]{1,4}", raw_api) else None
    abis = [item.strip() for item in (raw_properties["abis"] or "").split(",") if item.strip()]
    device = {**raw_properties, "api_level": api, "abis": abis}
    versions = {}
    targets = []
    for process in processes:
        package = process.split(":", 1)[0]
        if package not in versions:
            versions[package] = _version(read(f"dumpsys package {package}"))
        name, code = versions[package]
        targets.append({"process": process, "package": package,
                        "version_name": name, "version_code": code})
    document = {
        "schema_version": METADATA_SCHEMA_VERSION, "run_id": run_id,
        "captured_at": started,
        "collector": {"name": "ADBLab MobilePerf", "version": collector_version},
        "device": device, "targets": targets, "sampling": frozen_sampling,
    }
    missing = _missing(document)
    document.update(status="partial" if missing else "complete", missing_fields=missing)
    _validate(document)
    return document


def _keys(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid metadata fields")
    return value


def _validate(document: object) -> dict[str, Any]:
    data = _keys(document, {"schema_version", "run_id", "captured_at", "collector", "device",
                            "targets", "sampling", "status", "missing_fields"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported metadata schema")
    metadata_filename(data["run_id"])
    stamp = data["captured_at"]
    if (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0):
        raise ValueError("invalid capture time")
    collector = _keys(data["collector"], {"name", "version"})
    if collector["name"] != "ADBLab MobilePerf" or _text(collector["version"]) is None:
        raise ValueError("invalid collector")
    device = _keys(data["device"], set(_PROPERTIES))
    for key in ("brand", "model", "android_version"):
        if device[key] is not None and _text(device[key]) != device[key]:
            raise ValueError("invalid device description")
    api = device["api_level"]
    if api is not None and (type(api) is not int or not 1 <= api <= 9999):
        raise ValueError("invalid API level")
    if (not isinstance(device["abis"], list) or len(device["abis"]) > 16
            or any(not isinstance(abi, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,50}", abi) is None
                   for abi in device["abis"])):
        raise ValueError("invalid ABI list")
    targets = data["targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 128:
        raise ValueError("invalid metadata targets")
    for target in targets:
        target = _keys(target, {"process", "package", "version_name", "version_code"})
        if _process(target["process"]).split(":", 1)[0] != target["package"]:
            raise ValueError("invalid target package")
        name, code = target["version_name"], target["version_code"]
        if name is not None and _text(name) != name:
            raise ValueError("invalid version name")
        if code is not None and (type(code) is not int or not 0 <= code < 10**20):
            raise ValueError("invalid version code")
    if len({target["process"] for target in targets}) != len(targets):
        raise ValueError("duplicate targets")
    sampling = data["sampling"]
    required = {"frequency_seconds", "timeout_seconds", "dumpheap_seconds", "monkey_enabled"}
    if (not isinstance(sampling, dict) or not required <= set(sampling)
            or set(sampling) - required - {"monkey_config"}):
        raise ValueError("invalid sampling fields")
    for key in required - {"monkey_enabled"}:
        if type(sampling[key]) not in (int, float) or not math.isfinite(sampling[key]):
            raise ValueError("invalid sampling number")
        if sampling[key] < (1 if key == "frequency_seconds" else 0):
            raise ValueError("invalid sampling interval")
    if type(sampling["monkey_enabled"]) is not bool:
        raise ValueError("invalid monkey state")
    if "monkey_config" in sampling:
        monkey = _keys(sampling["monkey_config"], _MONKEY_INTS | _MONKEY_BOOLS)
        if (any(type(monkey[key]) is not int or monkey[key] < 0 for key in _MONKEY_INTS)
                or any(type(monkey[key]) is not bool for key in _MONKEY_BOOLS)):
            raise ValueError("invalid monkey configuration")
    missing = _missing(data)
    expected_status = "partial" if missing else "complete"
    if data["missing_fields"] != missing or data["status"] != expected_status:
        raise ValueError("inconsistent metadata status")
    return data


def write_metadata(directory: str | Path, document: dict[str, Any]) -> str:
    """在同目录原子发布已验证快照；写入失败保留原文件并删除临时文件。"""
    data = _validate(document)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("metadata too large")
    target = Path(directory).absolute() / metadata_filename(data["run_id"])
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".metadata_", dir=target.parent, delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = ""
    finally:
        if temporary:
            os.unlink(temporary)
    return str(target)


def read_metadata(path: str | Path, *, expected_run_id: str, finished_at_ns: int | None = None):
    """后台有限读取并核对运行归属；不可读取、未来格式和晚到文件均不交付附件。"""
    path = Path(path)
    try:
        with path.open("rb") as stream:
            modified = os.fstat(stream.fileno()).st_mtime_ns
            if finished_at_ns is not None and modified > finished_at_ns:
                return MetadataRead(status="mismatch")
            raw = stream.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            return MetadataRead(status="invalid")
        data = json.loads(raw)
        if (isinstance(data, dict) and type(data.get("schema_version")) is int
                and data["schema_version"] != METADATA_SCHEMA_VERSION):
            return MetadataRead(status="unsupported")
        data = _validate(data)
        if data["run_id"] != expected_run_id:
            return MetadataRead(status="mismatch")
    except FileNotFoundError:
        return MetadataRead()
    except OSError:
        return MetadataRead(status="unavailable")
    except (ValueError, TypeError, OverflowError, RecursionError):
        return MetadataRead(status="invalid")
    versions = []
    for target in data["targets"]:
        name, code = target["version_name"], target["version_code"]
        if name is None or code is None:
            version = "—"
        else:
            version = f"{name} ({code})"
        versions.append(f"{target['process']}: {version}" if len(data["targets"]) > 1 else version)
    app_version = "; ".join(versions)
    if all(target["version_name"] is None or target["version_code"] is None
           for target in data["targets"]):
        app_version = ""
    # 历史索引已有 200 字符契约；较长多目标信息保留在附件中，不截断为误导性的版本。
    if len(app_version) > 200:
        app_version = ""
    return MetadataRead(str(path.absolute()), app_version, data["status"])
