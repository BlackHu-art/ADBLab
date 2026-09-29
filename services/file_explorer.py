"""File Explorer 的纯逻辑层：路径、命令构建和列表解析。

UI 层只负责交互和展示；这里的函数必须保持无 Qt 依赖，方便单测和后续复用。
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime

SHELL_DANGER = re.compile(r'[;&|`$(){}!<>"\'\n\r]')
_VALID_MODE = re.compile(r"^[0-7]{3,4}$")
_MONTH_NUMBERS = {name: month for month, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1,
)}


def modified_sort_key(value: str) -> tuple[int, tuple[int, ...], str]:
    """完整日期、缺年日期、未知格式分组；缺年仅比较月日，不推断当前年份。"""
    value = value.strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}) (\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    month = re.fullmatch(
        r"([A-Za-z]{3})\s+(\d{1,2})(?:\s+(\d{4}|\d{1,2}:\d{2}(?::\d{2})?))?", value,
    )
    group = 0
    if iso:
        parts = tuple(int(part or 0) for part in iso.groups())
    elif month and month[1].lower() in _MONTH_NUMBERS:
        suffix = month[3] or ""
        has_year = suffix.isdigit() and len(suffix) == 4
        group = 0 if has_year else 1
        time_parts = [int(part) for part in suffix.split(":")] if ":" in suffix else []
        time_parts += [0] * (3 - len(time_parts))
        parts = (int(suffix) if has_year else 0, _MONTH_NUMBERS[month[1].lower()],
                 int(month[2]), *time_parts)
    else:
        return 2, (), value.casefold()
    try:
        # 2000 仅用于校验未知年份的月日（允许 2 月 29 日），绝不进入排序键。
        datetime(
            parts[0] if group == 0 else 2000, parts[1], parts[2], parts[3], parts[4], parts[5],
        )
    except ValueError:
        return 2, (), value.casefold()
    return group, parts, value.casefold()


@dataclass(frozen=True)
class TextPreview:
    """保存原始正文与编码策略；未编辑时绕过 Qt 文档的换行归一。"""

    raw: bytes
    text: str
    editable: bool
    truncated: bool
    newline: str
    bom: bool

    def encode(self, text: str, *, modified: bool) -> bytes:
        """仅完整 UTF-8 正文允许保存；编辑后沿用原文首个换行风格和 BOM。"""
        if not self.editable:
            raise ValueError("Incomplete or invalid UTF-8 text cannot be saved")
        if not modified:
            return self.raw
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return (b"\xef\xbb\xbf" if self.bom else b"") + normalized.replace(
            "\n", self.newline,
        ).encode("utf-8")


def decode_text_preview(raw: bytes, byte_limit: int) -> TextPreview:
    """先以原始字节判断截断，解码替代字符仅用于只读展示。"""
    truncated = len(raw) > byte_limit
    visible = raw[:byte_limit]
    valid = True
    try:
        text = visible.decode("utf-8-sig")
    except UnicodeDecodeError:
        valid = False
        text = visible.decode("utf-8-sig", errors="replace")
    newline = re.search(r"\r\n|\r|\n", text)
    return TextPreview(
        raw, text, valid and not truncated, truncated,
        newline.group() if newline else "\n", raw.startswith(b"\xef\xbb\xbf"),
    )


@dataclass(frozen=True)
class FileEntry:
    name: str
    file_type: str
    size_text: str
    modified: str
    size: int
    is_dir: bool
    is_symlink: bool = False


@dataclass(frozen=True)
class DirectoryListing:
    """完整校验后交付的目录快照，名称来自独立原始字段而非展示文本。"""

    entries: tuple[FileEntry, ...]
    symlink_targets: dict[str, str]


DIRECTORY_LIST_PREFIX = b"ADBLAB_LIST_V1\0"
DIRECTORY_LIST_LIMIT = 8 * 1024 * 1024


def directory_list_command(path: str) -> str:
    """以 NUL 分隔名称、stat 元数据及链接目标，不用 ls 展示格式反推身份。"""
    if not path.startswith("/") or any(char in path for char in "\0\r\n"):
        raise ValueError("目录路径无效，请重新选择目录。")
    # 参数直接由 find 传给 shell，空白、箭头和引号均不会重新变成语法。
    script = (
        'for p do printf "%s\\0" "${p##*/}" || exit; '
        'stat -c "%A|%s|%y" -- "$p" || exit; printf "\\0" || exit; '
        'if [ -L "$p" ]; then readlink -- "$p" || exit; fi; '
        'printf "\\0" || exit; done'
    )
    directory = path.rstrip("/") + "/"
    return (
        "printf 'ADBLAB_LIST_V1\\0' && "
        f"find {shell_quote(directory)} -mindepth 1 -maxdepth 1 "
        f"-exec sh -c {shell_quote(script)} sh {{}} +"
    )


def parse_directory_listing(raw: bytes) -> DirectoryListing:
    """整份严格解码后才交付；非法 UTF-8、换行身份及不完整字段均明确失败。"""
    if len(raw) > DIRECTORY_LIST_LIMIT or not raw.startswith(DIRECTORY_LIST_PREFIX):
        raise ValueError("设备目录列表格式不受支持或过大。")
    body = raw[len(DIRECTORY_LIST_PREFIX):]
    if body and not body.endswith(b"\0"):
        raise ValueError("设备目录列表不完整。")
    fields = body.split(b"\0")[:-1]
    if len(fields) % 3:
        raise ValueError("设备目录列表不完整。")
    rows: list[FileEntry] = []
    targets: dict[str, str] = {}
    names: set[str] = set()
    for offset in range(0, len(fields), 3):
        name, metadata, target = (
            field.decode("utf-8", errors="strict") for field in fields[offset:offset + 3]
        )
        if (not name or name in {".", ".."} or name in names
                or any(char in name for char in "/\0\r\n")):
            raise ValueError("目录包含无法安全操作的文件名，请在设备端重命名后刷新。")
        match = re.fullmatch(
            r"([bcdlps-][rwxSsTt-]{9})\|(\d+)\|"
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)? [+-]\d{4}\n",
            metadata,
        )
        if match is None:
            raise ValueError("设备不支持所需的文件元数据格式。")
        mode, size_text, modified = match.groups()
        # 文件尺寸应能以设备 off_t 表示，拒绝超范围数值在 UI 格式化时溢出。
        if len(size_text) > 19 or int(size_text) > (1 << 63) - 1:
            raise ValueError("设备返回的文件尺寸超出支持范围。")
        is_symlink = mode.startswith("l")
        if is_symlink:
            if not target.endswith("\n") or len(target) <= 1:
                raise ValueError("设备返回的链接信息不完整。")
            targets[name] = target[:-1]
        elif target:
            raise ValueError("设备返回的文件类型不一致，请刷新后重试。")
        names.add(name)
        is_dir = mode.startswith("d")
        rows.append(FileEntry(
            name, "Folder" if is_dir else "Link" if is_symlink else extension_label(name),
            "-" if is_dir else format_size(size_text), modified, int(size_text),
            is_dir, is_symlink,
        ))
    rows.sort(key=lambda item: (not (item.is_dir or item.is_symlink), item.name.lower()))
    return DirectoryListing(tuple(rows), targets)


@dataclass(frozen=True)
class PreviewVersion:
    """远端原始文件版本；时间保留设备提供的纳秒文本，避免展示格式丢失精度。"""

    size: int
    inode: int
    modified: str
    changed: str


def parse_preview_version(output: str) -> PreviewVersion | None:
    """只接受细粒度 stat 结果；不支持格式或仅整秒时间的设备不复用预览缓存。

    元数据用于页面会话内的新鲜度检查，不代表文件内容哈希；显式刷新始终失效。
    """
    parts = output.strip().split("|")
    if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    timestamp = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.(\d{9}) [+-]\d{4}"
    modified = re.fullmatch(timestamp, parts[2])
    changed = re.fullmatch(timestamp, parts[3])
    if modified is None or changed is None:
        return None
    if modified.group(1) == changed.group(1) == "000000000":
        return None
    return PreviewVersion(int(parts[0]), int(parts[1]), parts[2], parts[3])


def preview_version_command(path: str) -> str:
    """读取原始字节数、inode 和两个精细时间，不通过 ls 的展示字段判断版本。"""
    return f"stat -c '%s|%i|%y|%z' -- {shell_quote(path)}"


def safe_name(name: str) -> bool:
    """校验单个文件名，阻止路径穿越和 shell 元字符进入命令字符串。"""
    return (
        bool(name)
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and not SHELL_DANGER.search(name)
    )


def device_path(*parts: str) -> str:
    """Android 路径遵循 POSIX 规则，文件名中的冒号不能被宿主解释为盘符。"""
    return posixpath.join(*parts)


def root_command(cmd: str, use_root: bool) -> str:
    if not use_root:
        return cmd
    return f"su -c {shell_quote(cmd)}"


def shell_quote(value: str) -> str:
    """用单引号包裹远端 shell 参数，避免空格、$、双引号等字符被二次解释。"""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def parse_ls_line(line: str) -> dict[str, str] | None:
    """解析 toybox、busybox 或 coreutils 产生的一行 ls -la 输出。"""
    text = line.rstrip("\r\n")
    tokens = list(re.finditer(r"\S+", text))
    parts = [token.group() for token in tokens]
    if len(parts) < 6:
        return None
    perms = parts[0]
    index = 1
    if index < len(parts) and _is_size_token(parts[index]):
        index += 1
    if index + 2 >= len(parts):
        return None
    owner = parts[index]
    group = parts[index + 1]
    index += 2

    size_index = None
    for cursor in range(index, len(parts)):
        if _is_size_token(parts[cursor]):
            size_index = cursor
            break
    if size_index is None or size_index + 1 >= len(parts):
        return None

    # 元数据按字段解析，文件名仍取原始文本，防止连续空白被折叠后指向错误路径。
    modified, name = _split_modified_name(text[tokens[size_index + 1].start() :])
    if not name:
        return None
    return {
        "perms": perms,
        "owner": owner,
        "group": group,
        "size": parts[size_index],
        "modified": modified,
        "name": name,
    }


def extension_label(name: str) -> str:
    return name.rsplit(".", 1)[-1].upper() if "." in name else "File"


def safe_int(value: str | int) -> int:
    try:
        return int(str(value).replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def format_size(value: str | int) -> str:
    if not _is_size_token(str(value)):
        return "-"
    size = float(safe_int(value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _is_size_token(value: str) -> bool:
    return bool(re.fullmatch(r"\d[\d,]*", str(value)))


def _split_modified_name(value: str) -> tuple[str, str]:
    # ls 在时间和名称之间只输出一个分隔符，其后的空白属于文件身份。
    time_or_year = r"(?:\d{1,2}:\d{2}(?::\d{2})?|\d{4})"
    for pattern in (
        rf"([A-Za-z]{{3}}\s+\d{{1,2}}\s+{time_or_year})[ \t](.*)",
        rf"(\d{{4}}-\d{{2}}-\d{{2}}\s+{time_or_year})[ \t](.*)",
        r"([A-Za-z]{3}\s+\d{1,2})[ \t](.*)",
    ):
        match = re.fullmatch(pattern, value)
        if match:
            return " ".join(match[1].split()), match[2]
    return "", ""


def parse_ls_output(output: str) -> tuple[list[FileEntry], dict[str, str]]:
    """解析列表并保留链接身份；ls 的链接权限位不能证明目标是目录。"""
    rows: list[FileEntry] = []
    symlink_targets: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip() or line.startswith("total"):
            continue
        if line.lstrip().startswith(("Permission denied", "ls:")):
            continue
        entry = parse_ls_line(line)
        if not entry:
            continue

        name_part = entry["name"]
        is_symlink = entry["perms"].startswith("l")
        if is_symlink:
            # 展示协议无法区分名称/目标中的分隔串，歧义条目不得用于变更操作。
            if len(re.findall(r"(?= -> )", name_part)) != 1:
                continue
            name, target = name_part.split(" -> ", 1)
            if not target:
                continue
        else:
            name = name_part
        if not name or name in (".", "..") or "/" in name or "\0" in name:
            continue
        if is_symlink:
            symlink_targets[name] = target

        is_dir = entry["perms"].startswith("d")
        rows.append(
            FileEntry(
                name=name,
                file_type="Folder" if is_dir else "Link" if is_symlink else extension_label(name),
                size_text="-" if is_dir else format_size(entry["size"]),
                modified=entry["modified"],
                size=safe_int(entry["size"]),
                is_dir=is_dir,
                is_symlink=is_symlink,
            )
        )

    rows.sort(key=lambda item: (not (item.is_dir or item.is_symlink), item.name.lower()))
    return rows, symlink_targets


def link_target_type_command(path: str) -> str:
    """单次只读查询链接目标类型，路径始终按设备 shell 参数引用。"""
    quoted = shell_quote(path)
    return (
        f"if [ -d {quoted} ]; then printf directory; "
        f"elif [ -f {quoted} ]; then printf file; "
        f"elif [ -L {quoted} ] && [ ! -e {quoted} ]; then printf missing; "
        "else printf unavailable; fi"
    )



def parse_mode(raw_mode: str) -> str | None:
    """解析设备返回的权限模式；无法确认时不伪造默认权限。"""
    mode = (raw_mode or "").strip()
    if not _VALID_MODE.fullmatch(mode):
        return None
    return mode[-3:]


def mode_from_permissions(states: dict[tuple[str, str], bool]) -> str:
    mode_parts: list[str] = []
    for col in ("owner", "group", "other"):
        value = (
            (4 if states.get((col, "r")) else 0)
            + (2 if states.get((col, "w")) else 0)
            + (1 if states.get((col, "x")) else 0)
        )
        mode_parts.append(str(value))
    return "".join(mode_parts)


def ls_command(path: str) -> str:
    return f"ls -la {shell_quote(path)} 2>&1"


def head_command(path: str, byte_limit: int) -> str:
    return f"head -c {int(byte_limit)} {shell_quote(path)}"


def copy_for_root_pull_command(src: str, dst: str) -> str:
    return f"dd if={shell_quote(src)} of={shell_quote(dst)} && chmod 644 {shell_quote(dst)}"


def resolve_text_target_command(path: str) -> str:
    """解析链接的实际普通文件目标；固定标记保护路径首尾空白。"""
    return (
        f"target=$(readlink -f -- {shell_quote(path)}) && "
        '[ -f "$target" ] && [ -w "$target" ] && '
        'printf \'ADBLAB_TARGET:%s:END\' "$target"'
    )


def publish_text_command(target: str, directory: str, uploaded: str) -> str:
    """复制原权限和所有权至同目录新文件，完整写入后原子替换实际目标。"""
    staged = shell_quote(f"{directory}/ready")
    return (
        f"cp -p -- {shell_quote(target)} {staged} && "
        f"cat -- {shell_quote(uploaded)} > {staged} && "
        f"mv -f -- {staged} {shell_quote(target)}"
    )


def prepare_text_directory_command(directory: str) -> str:
    """独占创建目录并留下归属标记，取消导致返回丢失时仍可安全清理。"""
    token = posixpath.basename(directory)
    return (
        f"mkdir -m 700 -- {shell_quote(directory)} && "
        f"printf %s {shell_quote(token)} > {shell_quote(f'{directory}/owner')}"
    )


def cleanup_text_directory_command(directory: str) -> str:
    """只删除本次独占目录的已知文件；拒绝递归扩展清理范围。"""
    token = posixpath.basename(directory)
    return (
        f"if [ ! -e {shell_quote(directory)} ]; then exit 0; fi; "
        f"[ ! -L {shell_quote(directory)} ] && "
        f'[ "$(cat -- {shell_quote(f"{directory}/owner")})" = {shell_quote(token)} ] && '
        f"rm -f -- {shell_quote(f'{directory}/upload')} {shell_quote(f'{directory}/ready')}"
        f" {shell_quote(f'{directory}/owner')}"
        f" && rmdir -- {shell_quote(directory)}"
    )


def mkdir_command(path: str) -> str:
    return f"mkdir -p {shell_quote(path)}"


def touch_command(path: str) -> str:
    return f"touch {shell_quote(path)}"


def move_command(src: str, dst: str) -> str:
    return f"mv {shell_quote(src)} {shell_quote(dst)}"


def rename_command(src: str, dst: str) -> str:
    """拒绝检查时已存在的目标；命令跳过或未完成移动均明确返回失败。"""
    source, target = shell_quote(src), shell_quote(dst)
    # -L 单独覆盖悬空链接；-T 禁止把执行前才出现的目录解释成目标容器。
    # -n 可能在跳过时返回零，因此还须确认源已消失且新路径确实存在。
    # 检查后的设备侧并发改写受 mv 实现约束，不承诺原子无覆盖。
    return (
        f"if [ -e {target} ] || [ -L {target} ]; then "
        "printf '%s\\n' 'Destination already exists; choose a different name.' >&2; exit 1; fi; "
        f"mv -nT -- {source} {target} || exit $?; "
        f"if [ ! -e {source} ] && [ ! -L {source} ] && "
        f"{{ [ -e {target} ] || [ -L {target} ]; }}; then :; else "
        "printf '%s\\n' 'Rename was not completed; refresh and try again.' >&2; exit 1; fi"
    )


def delete_command(path: str) -> str:
    return f"rm -rf {shell_quote(path)}"


def copy_command(src: str, dst: str) -> str:
    return f"cp -R {shell_quote(src)} {shell_quote(dst)}"


def stat_mode_command(path: str) -> str:
    return f"stat -c %a {shell_quote(path)}"


def chmod_command(mode: str, path: str) -> str:
    return f"chmod {mode} {shell_quote(path)}"


def install_apk_command(path: str) -> str:
    return f"pm install -r {shell_quote(path)}"


def script_command(path: str, use_root: bool) -> str:
    if use_root:
        return f"chmod +x {shell_quote(path)} && sh {shell_quote(path)}"
    return f"sh {shell_quote(path)}"


def folder_size_command(path: str) -> str:
    return f"du -sh {shell_quote(path)}"
