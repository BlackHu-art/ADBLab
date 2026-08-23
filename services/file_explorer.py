"""File Explorer 的纯逻辑层：路径、命令构建和列表解析。

UI 层只负责交互和展示；这里的函数必须保持无 Qt 依赖，方便单测和后续复用。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

SHELL_DANGER = re.compile(r'[;&|`$(){}!<>"\'\n\r]')
_VALID_MODE = re.compile(r"^[0-7]{3,4}$")


@dataclass(frozen=True)
class FileEntry:
    name: str
    file_type: str
    size_text: str
    modified: str
    size: int
    is_dir: bool


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
    text = line.strip()
    parts = text.split()
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

    modified, name = _split_modified_name(" ".join(parts[size_index + 1 :]))
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
    """解析 adb shell `ls -la` 输出，并保持文件夹优先、名称升序。"""
    rows: list[FileEntry] = []
    symlink_targets: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip() or line.startswith("total"):
            continue
        if "Permission denied" in line or line.startswith("ls:"):
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

        is_dir = entry["perms"].startswith(("d", "l"))
        rows.append(
            FileEntry(
                name=name,
                file_type="Folder" if is_dir else extension_label(name),
                size_text="-" if is_dir else format_size(entry["size"]),
                modified=entry["modified"],
                size=safe_int(entry["size"]),
                is_dir=is_dir,
            )
        )

    rows.sort(key=lambda item: (not item.is_dir, item.name.lower()))
    return rows, symlink_targets



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


def cat_command(path: str) -> str:
    return f"cat {shell_quote(path)}"


def head_command(path: str, byte_limit: int) -> str:
    return f"head -c {int(byte_limit)} {shell_quote(path)}"


def copy_for_root_pull_command(src: str, dst: str) -> str:
    return f"dd if={shell_quote(src)} of={shell_quote(dst)} && chmod 644 {shell_quote(dst)}"


def save_text_command(base64_content: str, dst: str) -> str:
    return f"printf %s {shell_quote(base64_content)} | base64 -d > {shell_quote(dst)}"


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
