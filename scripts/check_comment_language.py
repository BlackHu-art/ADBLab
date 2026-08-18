#!/usr/bin/env python3
"""检查受控 Python 代码中的注释和文档字符串语言。"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# 只纳入已经完成人工治理的目录，后续按批次扩展，避免历史债务阻断现有开发。
MANAGED_PATHS = (
    Path("adblab"),
    Path("controllers"),
    Path("core"),
    Path("gui"),
    Path("models"),
    Path("utils"),
    Path("main.py"),
    Path("mobileperf/common"),
    Path("mobileperf/android"),
)

EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".idea",
        ".pytest_cache",
        "__pycache__",
        "build",
        "dist",
        "extlib",
        "generated",
        "logs",
        "resources",
        "scrcpy-win64-v3.3.1",
    }
)

_HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")
_MOJIBAKE_MARKERS = ("\ufffd", "锛", "銆", "鈥", "��")
_URL_PATTERN = re.compile(r"(?:https?|file)://\S+$", re.IGNORECASE)
_DIRECTIVE_PATTERN = re.compile(
    r"(?:noqa\b|type:\s*ignore\b|pylint:|ruff:|fmt:|pragma:|nosec\b|" r"coverage:|mypy:|pyright:)",
    re.IGNORECASE,
)
_ENCODING_PATTERN = re.compile(r"coding[:=]\s*[-\w.]+")
_LICENSE_PATTERN = re.compile(
    r"(?:SPDX-License-Identifier:|Copyright\b|Licensed under\b|MIT License\b)",
    re.IGNORECASE,
)
_COMMAND_PATTERN = re.compile(
    r"(?:[$>]\s*)?(?:py(?:thon)?|pytest|ruff|black|git|adb|scrcpy|pip|" r"powershell)(?:\s|$)",
    re.IGNORECASE,
)
_TECHNICAL_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/<>{}\[\]()+*=,'\"-]*")


@dataclass(frozen=True, order=True)
class LanguageIssue:
    """描述一处不符合中文注释规范的问题。"""

    path: Path
    line: int
    kind: str
    text: str


def _is_exempt(text: str) -> bool:
    """判断文本是否属于无需翻译的机器指令、许可证或技术标识。"""
    value = text.strip()
    if not value:
        return True
    if value.startswith("!/"):
        return True
    if _ENCODING_PATTERN.search(value):
        return True
    if _DIRECTIVE_PATTERN.search(value):
        return True
    if _LICENSE_PATTERN.search(value):
        return True
    if _URL_PATTERN.fullmatch(value):
        return True
    if _COMMAND_PATTERN.match(value):
        return True
    return bool(_TECHNICAL_TOKEN_PATTERN.fullmatch(value))


def _contains_mojibake(text: str) -> bool:
    """判断文本是否包含明确的替换符或常见 UTF-8 误解码片段。"""
    return any(marker in text for marker in _MOJIBAKE_MARKERS)


def _requires_chinese(text: str) -> bool:
    """判断自然语言说明是否缺少中文内容。"""
    value = text.strip()
    if not value or _HAN_PATTERN.search(value) or _is_exempt(value):
        return False
    return bool(_LATIN_WORD_PATTERN.search(value))


def _iter_python_files(root: Path, paths: Sequence[Path]) -> Iterator[Path]:
    """按明确的受控范围枚举 Python 文件，并跳过第三方和生成目录。"""
    seen: set[Path] = set()
    for configured_path in paths:
        candidate = configured_path
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.exists():
            continue
        files = (candidate,) if candidate.is_file() else candidate.rglob("*.py")
        for file_path in files:
            resolved = file_path.resolve()
            if resolved in seen:
                continue
            try:
                relative = resolved.relative_to(root.resolve())
            except ValueError:
                relative = resolved
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            seen.add(resolved)
            yield resolved


def _docstring_nodes(tree: ast.AST) -> Iterator[tuple[ast.AST, str]]:
    """遍历模块、类和函数节点中的真实文档字符串。"""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        value = ast.get_docstring(node, clean=False)
        if value is not None:
            yield node, value


def scan_file(file_path: Path, *, display_path: Path | None = None) -> list[LanguageIssue]:
    """检查单个 Python 文件，不把普通字符串误判为注释。"""
    shown_path = display_path or file_path
    try:
        source = tokenize.open(file_path).read()
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [LanguageIssue(shown_path, 1, "read-error", type(exc).__name__)]

    issues: list[LanguageIssue] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            text = token.string[1:].strip()
            if _contains_mojibake(text):
                issues.append(LanguageIssue(shown_path, token.start[0], "mojibake-comment", text))
            elif _requires_chinese(text):
                issues.append(LanguageIssue(shown_path, token.start[0], "comment", text))
    except (IndentationError, tokenize.TokenError) as exc:
        issues.append(LanguageIssue(shown_path, 1, "tokenize-error", str(exc)))
        return issues

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        issues.append(
            LanguageIssue(
                shown_path,
                exc.lineno or 1,
                "syntax-error",
                exc.msg,
            )
        )
        return issues

    if ast.get_docstring(tree, clean=False) is None:
        issues.append(LanguageIssue(shown_path, 1, "module-docstring", "缺少中文模块说明"))
    for node, text in _docstring_nodes(tree):
        if _contains_mojibake(text):
            issues.append(
                LanguageIssue(
                    shown_path,
                    getattr(node, "lineno", 1),
                    "mojibake-docstring",
                    text.strip().splitlines()[0],
                )
            )
        elif _requires_chinese(text):
            issues.append(
                LanguageIssue(
                    shown_path,
                    getattr(node, "lineno", 1),
                    "docstring",
                    text.strip().splitlines()[0],
                )
            )
    return issues


def scan_paths(
    root: Path,
    paths: Sequence[Path] = MANAGED_PATHS,
) -> list[LanguageIssue]:
    """检查受控路径并返回稳定排序的问题列表。"""
    root = root.resolve()
    issues: list[LanguageIssue] = []
    for file_path in _iter_python_files(root, paths):
        try:
            display_path = file_path.relative_to(root)
        except ValueError:
            display_path = file_path
        issues.extend(scan_file(file_path, display_path=display_path))
    return sorted(issues)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="相对于仓库根目录的检查路径；省略时使用当前受控范围。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="仓库根目录。",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """运行检查并以非零状态报告不合规内容。"""
    args = _build_parser().parse_args(argv)
    paths = tuple(args.paths) or MANAGED_PATHS
    issues = scan_paths(args.root, paths)
    for issue in issues:
        print(f"{issue.path}:{issue.line}: {issue.kind}: {issue.text}")
    if issues:
        print(f"发现 {len(issues)} 处注释语言问题。")
        return 1
    print("受控范围内的注释和文档字符串符合中文规范。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
