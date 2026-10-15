"""按活动包、Android 用户和缩进边界解析权限，不猜测匿名授权状态。"""

import re

_PERMISSION_NAME = re.compile(r"[^\W\d][\w$-]*(?:\.[^\W\d][\w$-]*)+")
_PACKAGE_HEADER = re.compile(r"Package \[[A-Za-z0-9_.]+\] \([^()\r\n]+\):")
_USER_HEADER = re.compile(r"User (0|[1-9][0-9]*):(?: .*)?")
_DECLARED_PERMISSION = re.compile(r"([^:]+): prot=\S.*")
_RUNTIME_PERMISSION = re.compile(r"([^:]+): granted=(true|false)(?:, flags=\[[^\]\r\n]*\])?")
_SHARED_REFERENCE = re.compile(
    r"sharedUser=SharedUserSetting\{([0-9a-fA-F]+) ([A-Za-z0-9_.]+)/([0-9]+)\}",
)
_SHARED_HEADER = re.compile(r"SharedUser \[([A-Za-z0-9_.]+)\] \(([0-9a-fA-F]+)\):")


def is_permission_name(value: object) -> bool:
    """接受分段权限名及 Android 支持的 Unicode、美元符和连字符。

    控制字符与小节分隔仍拒绝；该校验不能替代写入端的 shell 参数引用。
    """
    return isinstance(value, str) and _PERMISSION_NAME.fullmatch(value) is not None


def _output_lines(output: str) -> list[tuple[int, str]]:
    """保留转储层级，不把非协议控制字符当作换行。"""
    # 只认设备转储的 LF/CRLF；其他控制字符不能把污染行拆成有效权限名。
    raw_lines = (line.removesuffix("\r") for line in output.split("\n"))
    return [(len(line) - len(line.lstrip(" ")), line.lstrip(" "))
            for line in raw_lines if line.strip()]


def _active_package_lines(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """只选择一个明确活动包；系统旧副本和多包输出不能提供目标身份。"""
    sections = [index for index, line in enumerate(lines) if line == (0, "Packages:")]
    if sections:
        if len(sections) != 1:
            return []
        start = sections[0] + 1
        end = next((index for index in range(start, len(lines)) if lines[index][0] == 0),
                   len(lines))
        lines = lines[start:end]
    elif not lines or not _PACKAGE_HEADER.fullmatch(lines[0][1]):
        return []

    if not lines or not _PACKAGE_HEADER.fullmatch(lines[0][1]):
        return []
    package_indent = lines[0][0]
    end = next((index for index in range(1, len(lines))
                if lines[index][0] <= package_indent
                and not (lines[index][0] == package_indent
                         and _PACKAGE_HEADER.fullmatch(lines[index][1]))), len(lines))
    lines = lines[:end]
    if sum(indent == package_indent and _PACKAGE_HEADER.fullmatch(text) is not None
           for indent, text in lines) != 1:
        return []
    return lines


def _shared_user_lines(
    lines: list[tuple[int, str]], references: list[str],
) -> list[tuple[int, str]]:
    """共享 UID 必须同时匹配包引用中的对象标识、名称和 appId，不能按位置拼接。"""
    if len(references) != 1 or (reference := _SHARED_REFERENCE.fullmatch(references[0])) is None:
        return []
    identity, name, app_id = reference.groups()
    sections = [index for index, line in enumerate(lines) if line == (0, "Shared users:")]
    if len(sections) != 1:
        return []
    start = sections[0] + 1
    end = next((index for index in range(start, len(lines)) if lines[index][0] == 0), len(lines))
    section = lines[start:end]
    matches = [(index, header) for index, (indent, text) in enumerate(section)
               if indent == 2 and (header := _SHARED_HEADER.fullmatch(text)) is not None
               and header.group(1) == name]
    if len(matches) != 1 or matches[0][1].group(2) != identity:
        return []
    start = matches[0][0]
    end = next((index for index in range(start + 1, len(section)) if section[index][0] <= 2),
               len(section))
    block = section[start:end]
    # Android 6 的 userId 字段和 Android 14 的 appId 字段都表示共享应用身份，非 User N。
    ids = [text for indent, text in block if indent == 4
           and text.startswith(("userId=", "appId="))]
    if len(ids) != 1 or ids[0] not in {f"userId={app_id}", f"appId={app_id}"}:
        return []
    return block


def _parse_sections(
    lines: list[tuple[int, str]], user_id: int,
) -> tuple[list[str], list[str], list[tuple[str, bool]]]:
    """按 AOSP 包及共享用户转储的两空格层级读取小节，不跨越相邻小节。"""

    package_indent = lines[0][0]
    declared: dict[str, None] = {}
    requested: dict[str, None] = {}
    runtime: dict[str, bool] = {}
    conflicting: set[str] = set()
    selected_user = False
    section = ""
    section_indent = -1
    for indent, text in lines[1:]:
        if indent <= section_indent:
            section = ""
        if indent <= package_indent + 2:
            selected_user = False
        if indent == package_indent + 2:
            user = _USER_HEADER.fullmatch(text)
            if user:
                selected_user = user.group(1) == str(user_id)
            elif text in {"declared permissions:", "requested permissions:"}:
                section = text
                section_indent = indent
            continue
        if selected_user and indent == package_indent + 4 and text == "runtime permissions:":
            section = text
            section_indent = indent
            continue
        if not section or indent != section_indent + 2:
            continue

        if section == "requested permissions:":
            if is_permission_name(text):
                requested.setdefault(text, None)
        elif section == "declared permissions:":
            match = _DECLARED_PERMISSION.fullmatch(text)
            if match and is_permission_name(match.group(1)):
                declared.setdefault(match.group(1), None)
        else:
            match = _RUNTIME_PERMISSION.fullmatch(text)
            if not match or not is_permission_name(match.group(1)):
                continue
            name, granted = match.group(1), match.group(2) == "true"
            if name in conflicting:
                continue
            if name in runtime and runtime[name] != granted:
                del runtime[name]
                conflicting.add(name)
            else:
                runtime[name] = granted

    return list(declared), list(requested), list(runtime.items())


def parse_package_permissions(
    output: str, user_id: int,
) -> tuple[list[str], list[str], list[tuple[str, bool]]]:
    """解析单个活动包的声明、请求和指定用户授权，保留转储中的顺序。

    接受完整转储或单个明确 Package 块的截取；未知结构返回空列表。
    共享 UID 仅连接到身份完全匹配的唯一 SharedUser 块。
    运行时权限必须位于指定 User 块，缺失身份时不回退用户 0 或匿名小节。
    相互矛盾的重复授权不作为已知状态返回；非法用户编号属于调用方错误。
    """
    if type(user_id) is not int or user_id < 0:
        raise ValueError("Android 用户编号必须是具体的非负整数")
    lines = _output_lines(output)
    package = _active_package_lines(lines)
    if not package:
        return [], [], []
    declared, requested, runtime = _parse_sections(package, user_id)
    references = [text for indent, text in package
                  if indent == package[0][0] + 2 and text.startswith("sharedUser=")]
    if references:
        shared = _shared_user_lines(lines, references)
        runtime = _parse_sections(shared, user_id)[2] if shared else []
    return declared, requested, runtime
