"""File Explorer 的纯逻辑层：路径、命令构建和列表解析。

UI 层只负责交互和展示；这里的函数必须保持无 Qt 依赖，方便单测和后续复用。
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass

SHELL_DANGER = re.compile(r'[;&|`$(){}!<>"\'\n\r]')
_VALID_MODE = re.compile(r"^[0-7]{3,4}$")


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
    return os.path.join(*parts).replace("\\", "/")


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
    if not value:
        return "", ""
    month_parts = value.split(maxsplit=3)
    if (
        len(month_parts) >= 4
        and _looks_month(month_parts[0])
        and month_parts[1].isdigit()
        and _looks_time_or_year(month_parts[2])
    ):
        return " ".join(month_parts[:3]), month_parts[3]

    iso_parts = value.split(maxsplit=2)
    if len(iso_parts) >= 3 and _looks_iso_date(iso_parts[0]) and _looks_time_or_year(iso_parts[1]):
        return " ".join(iso_parts[:2]), iso_parts[2]

    short_parts = value.split(maxsplit=2)
    if len(short_parts) >= 3:
        return " ".join(short_parts[:2]), short_parts[2]
    if len(short_parts) == 2:
        return short_parts[0], short_parts[1]
    return "", value


def _looks_month(value: str) -> bool:
    return value.lower()[:3] in {
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    }


def _looks_time_or_year(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?|\d{4}", value))


def _looks_iso_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


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
        if is_symlink and "->" in name_part:
            name, target = name_part.split("->", 1)
            name = name.strip()
            symlink_targets[name] = target.strip()
        else:
            name = name_part
        if not name or name in (".", ".."):
            continue

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
