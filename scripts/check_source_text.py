"""检查 Git 工作区第一方文本的 UTF-8 与 NUL 完整性，包含生成的 Python 翻译资源。"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = frozenset({".py", ".md", ".ts", ".yaml", ".yml", ".toml", ".spec"})
EXCLUDED_ROOTS = frozenset({
    ".git", ".venv", "venv", "env", "build", "dist", "reference", "runtime-tools",
    ".agents", ".codex", "node_modules",
})


@dataclass(frozen=True)
class TextIssue:
    """只记录文件位置和故障类别，不输出可能包含敏感信息的文本正文。"""

    path: Path
    offset: int
    reason: str


def is_source_text(relative_path: Path) -> bool:
    """明确排除第三方与构建目录；生成 Python 文件仍按源码文本验证。"""
    parts = relative_path.parts
    if not parts or parts[0] in EXCLUDED_ROOTS or "__pycache__" in parts:
        return False
    if parts[:2] == ("mobileperf", "extlib"):
        return False
    return (
        relative_path.suffix.lower() in TEXT_SUFFIXES
        or relative_path.name == "constraints.txt"
        or (relative_path.name.startswith("requirements") and relative_path.suffix == ".txt")
    )


def check_file(path: Path) -> list[TextIssue]:
    """严格读取 UTF-8，允许 BOM；实际 NUL 字节与转义字符串须明确区分。"""
    try:
        content = path.read_bytes()
    except OSError as exc:
        return [TextIssue(path, 0, f"cannot read text ({type(exc).__name__})")]
    issues = []
    null_offset = content.find(b"\0")
    if null_offset >= 0:
        issues.append(TextIssue(path, null_offset, "NUL byte"))
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(TextIssue(path, exc.start, "invalid UTF-8"))
    return issues


def source_paths(root: Path) -> list[Path]:
    """枚举已跟踪及未忽略的新文件；Git 失败向调用方报告，不能退化为通过。"""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    names = set(result.stdout.decode("utf-8").split("\0"))
    return [
        root / name for name in sorted(names)
        if name and is_source_text(Path(name)) and (root / name).is_file()
    ]


def main(argv: list[str] | None = None) -> int:
    """返回 1 表示坏文本、2 表示枚举失败；只读扫描且不尝试自动解码修复。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        paths = source_paths(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        print(f"Cannot enumerate Git source files ({type(exc).__name__})")
        return 2
    issues = [issue for path in paths for issue in check_file(path)]
    for issue in issues:
        print(f"{issue.path.relative_to(root).as_posix()}:{issue.offset}: {issue.reason}")
    if issues:
        print(f"Source text integrity failed: {len(issues)} issue(s)")
        return 1
    print(f"Source text integrity passed: {len(paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
