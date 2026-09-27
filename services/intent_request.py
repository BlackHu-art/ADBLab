"""校验结构化 Intent 快照，并构造经过设备 shell 转义的参数。

本模块不执行 I/O。界面、控制器和模型共享同一校验边界，错误消息不包含用户参数。
"""

from __future__ import annotations

import math
import re
import shlex
from dataclasses import dataclass, replace
from typing import Literal

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:.+", re.ASCII)
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", re.ASCII)
_CLASS = re.compile(r"\.?[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", re.ASCII)
_ACTION = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]*", re.ASCII)
_MIME = re.compile(r"(?:[A-Za-z0-9!#$&^_.+-]+|\*)/(?:[A-Za-z0-9!#$&^_.+-]+|\*)", re.ASCII)
_INTEGER = re.compile(r"[+-]?[0-9]+", re.ASCII)
_FLAGS = re.compile(r"(?:[+-]?[0-9]+|0[xX][0-9a-fA-F]+)", re.ASCII)
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


@dataclass(frozen=True, slots=True)
class IntentExtra:
    """保留单个 extra 的显式类型与输入文本；执行前必须经过请求校验。"""

    key: str
    value_type: Literal["str", "bool", "int", "float"]
    value: str


@dataclass(frozen=True, slots=True)
class IntentRequest:
    """跨 Qt 信号传递的不可变请求；extras 必须使用不可变元组。"""

    kind: Literal["activity", "broadcast"] = "activity"
    component: str = ""
    action: str = ""
    data_uri: str = ""
    mime_type: str = ""
    flags: str = ""
    wait: bool = False
    extras: tuple[IntentExtra, ...] = ()


def _text(value: str, label: str, *, strip: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError(f"{label}不能包含控制字符")
    return value.strip() if strip else value


def validate_uri(uri: str) -> str:
    """要求显式 URI scheme 和非空内容，保留自定义 scheme；拒绝控制字符与内部空白。"""

    uri = _text(uri, "URI")
    if not _SCHEME.fullmatch(uri) or any(char.isspace() for char in uri):
        raise ValueError("URI 必须包含合法 scheme，且内容非空、空格已编码")
    return uri


def _normalize_flags(flags: str) -> str:
    flags = _text(flags, "Flags")
    if not flags:
        return ""
    if not _FLAGS.fullmatch(flags):
        raise ValueError("Flags 必须是十进制整数或 0x 十六进制整数")
    number = int(flags, 16 if flags.lower().startswith("0x") else 10)
    if not -(2**31) <= number <= 2**32 - 1:
        raise ValueError("Flags 必须在 32 位整数范围内")
    # am 使用 Java 有符号整数解析；最高位仍按同一 32 位掩码传递。
    return str(number - 2**32 if number >= 2**31 else number)


def _normalize_extra(extra: IntentExtra) -> IntentExtra:
    if not isinstance(extra, IntentExtra):
        raise ValueError("extras 必须包含结构化类型与值")
    # Bundle 按原字符串匹配键名，首尾空格不能在校验过程中被改写。
    key = _text(extra.key, "Extra 名称", strip=False)
    if not key.strip():
        raise ValueError("Extra 名称不能为空")
    value = _text(extra.value, "Extra 值", strip=extra.value_type != "str")
    if extra.value_type == "bool":
        value = value.lower()
        if value not in ("true", "false"):
            raise ValueError("布尔 Extra 必须是 true 或 false")
    elif extra.value_type == "int":
        if not _INTEGER.fullmatch(value) or not -(2**31) <= int(value) < 2**31:
            raise ValueError("整数 Extra 必须是 32 位十进制整数")
        value = str(int(value))
    elif extra.value_type == "float":
        if not _FLOAT.fullmatch(value):
            raise ValueError("小数 Extra 必须是有限数字")
        number = float(value)
        if not math.isfinite(number) or abs(number) > 3.4028234663852886e38:
            raise ValueError("小数 Extra 超出 Android float 范围")
        value = str(number)
    elif extra.value_type != "str":
        raise ValueError("Extra 类型必须是 str、bool、int 或 float")
    return replace(extra, key=key, value=value)


def validate_intent_request(request: IntentRequest) -> IntentRequest:
    """返回规范化请求；无效或当前不支持的字段组合抛出 ValueError，不默默丢弃参数。"""

    if not isinstance(request, IntentRequest) or request.kind not in ("activity", "broadcast"):
        raise ValueError("Intent 请求类型无效")
    component = _text(request.component, "组件")
    action = _text(request.action, "Action")
    data_uri = _text(request.data_uri, "URI")
    mime_type = _text(request.mime_type, "MIME")
    flags = _normalize_flags(request.flags)
    if component:
        parts = component.split("/")
        if (
            len(parts) != 2 or len(parts[0]) > 255
            or not _PACKAGE.fullmatch(parts[0]) or not _CLASS.fullmatch(parts[1])
        ):
            raise ValueError("组件必须使用包名/Activity 类名格式")
    if action and not _ACTION.fullmatch(action):
        raise ValueError("Action 格式无效")
    if data_uri:
        data_uri = validate_uri(data_uri)
    if mime_type and not _MIME.fullmatch(mime_type):
        raise ValueError("MIME 必须使用类型/子类型格式")
    if not isinstance(request.wait, bool):
        raise ValueError("等待启动结果必须是布尔值")
    if not isinstance(request.extras, tuple):
        raise ValueError("extras 必须是不可变元组")
    extras = tuple(_normalize_extra(extra) for extra in request.extras)
    if len({extra.key for extra in extras}) != len(extras):
        raise ValueError("Extra 名称不能重复")
    if request.kind == "broadcast":
        if not action:
            raise ValueError("广播 Action 不能为空")
        if component or data_uri or mime_type or flags or request.wait:
            raise ValueError("广播仅支持 Action 和 extras")
    else:
        if not (component or action or data_uri):
            raise ValueError("请填写组件、Action 或 URI")
        if extras:
            raise ValueError("Activity 暂不支持 extras")
        if data_uri and not (component or action):
            action = "android.intent.action.VIEW"
    return replace(request, component=component, action=action, data_uri=data_uri,
                   mime_type=mime_type, flags=flags, extras=extras)


def intent_extras_dict(request: IntentRequest) -> dict[str, str | bool | int | float]:
    """把已校验的 extra 快照转换为兼容模型入口所需的 Python 类型。"""

    result: dict[str, str | bool | int | float] = {}
    for extra in validate_intent_request(request).extras:
        value = extra.value
        if extra.value_type == "bool":
            result[extra.key] = value == "true"
        elif extra.value_type == "int":
            result[extra.key] = int(value)
        elif extra.value_type == "float":
            result[extra.key] = float(value)
        else:
            result[extra.key] = value
    return result


def broadcast_request(action: str, extras: dict | None = None) -> IntentRequest:
    """保留旧广播入口的四种值类型，并拒绝隐式字符串化不受支持的对象。"""

    if extras is not None and not isinstance(extras, dict):
        raise ValueError("extras 必须是名称与值字典")
    typed = []
    value_types: dict[type, Literal["str", "bool", "int", "float"]] = {
        str: "str", bool: "bool", int: "int", float: "float",
    }
    for key, value in (extras or {}).items():
        value_type = value_types.get(type(value))
        if value_type is None:
            raise ValueError("Extra 值仅支持字符串、布尔、整数与小数")
        typed.append(IntentExtra(key, value_type, str(value)))
    return validate_intent_request(IntentRequest(
        kind="broadcast", action=action, extras=tuple(typed),
    ))


def intent_arguments(request: IntentRequest) -> list[str]:
    """逐个转义动态值；调用方只能追加固定命令词，不能追加自由参数文本。"""

    request = validate_intent_request(request)
    arguments = ["am", "broadcast" if request.kind == "broadcast" else "start"]
    for option, value in (
        ("-n", request.component), ("-a", request.action), ("-d", request.data_uri),
        ("-t", request.mime_type), ("-f", request.flags),
    ):
        if value:
            arguments.extend((option, shlex.quote(value)))
    if request.wait:
        arguments.append("-W")
    options = {"str": "--es", "bool": "--ez", "int": "--ei", "float": "--ef"}
    for extra in request.extras:
        arguments.extend((
            options[extra.value_type], shlex.quote(extra.key), shlex.quote(extra.value),
        ))
    return arguments
