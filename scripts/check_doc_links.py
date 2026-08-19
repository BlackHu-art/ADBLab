"""校验 docs/ 下 Markdown 文档的相对链接与 frontmatter 必填字段。

用法：
    py -3.11 scripts/check_doc_links.py

规则：
- 扫描 docs/**/*.md；
- project-knowledge/ 下的文档必须有 frontmatter，且包含 status 与 last_verified 字段；
- 正文中的相对 Markdown 链接（不含 http/https/mailto 与纯锚点）必须能解析到已存在文件；
- frontmatter 中 related 列出的路径按同一规则解析（支持流式与块式 YAML 列表）。

退出码：0 表示全部通过，1 表示存在错误。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

LINK_RE = re.compile(r"\]\(([^()]+)\)")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
REQUIRED_KEYS = ("status", "last_verified")


def parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter 为 {key: value|list}；无 frontmatter 返回 None。"""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields: dict = {}
    current_key = None
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_key:
                fields.setdefault(current_key, []).append(stripped[2:].strip().strip("'\""))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                fields[key] = value.strip("'\"")
                current_key = None
            else:
                fields[key] = []
                current_key = key
    return fields


def related_paths(frontmatter: dict | None) -> list[str]:
    if not frontmatter:
        return []
    raw = frontmatter.get("related", "")
    if isinstance(raw, list):
        return [str(part) for part in raw]
    raw = raw.strip().strip("[]")
    return [part.strip().strip("'\"") for part in raw.split(",") if part.strip()]


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    rel_display = path.relative_to(ROOT).as_posix()

    if "project-knowledge" in path.parts:
        if frontmatter is None:
            errors.append(
                f"{rel_display}: 缺少 frontmatter"
                "（project-knowledge 文档必须包含 status 与 last_verified）"
            )
        else:
            for key in REQUIRED_KEYS:
                if key not in frontmatter:
                    errors.append(f"{rel_display}: frontmatter 缺少 {key}")

    def resolve(target: str) -> Path:
        target_path = target.split("#", 1)[0]
        return (path.parent / target_path).resolve()

    body = FRONTMATTER_RE.sub("", text)
    for target in LINK_RE.findall(body):
        if target.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
            continue
        if not resolve(target).exists():
            errors.append(f"{rel_display}: 链接目标不存在 -> {target}")

    for target in related_paths(frontmatter):
        if not resolve(target).exists():
            errors.append(f"{rel_display}: related 目标不存在 -> {target}")
    return errors


def main() -> int:
    if not DOCS.exists():
        print(f"docs 目录不存在: {DOCS}", file=sys.stderr)
        return 1
    files = sorted(DOCS.rglob("*.md"))
    if not files:
        print("docs 下没有 Markdown 文件", file=sys.stderr)
        return 1
    all_errors: list[str] = []
    for path in files:
        all_errors.extend(check_file(path))
    if all_errors:
        print(f"{len(all_errors)} 个问题：")
        for error in all_errors:
            print(f"  - {error}")
        return 1
    print(f"OK: {len(files)} 个 Markdown 文档的链接与 frontmatter 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
