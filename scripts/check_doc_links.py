"""校验项目知识文档的相对链接与 frontmatter 必填字段。

用法：
    .venv/Scripts/python.exe scripts/check_doc_links.py

规则：
- 扫描 docs/**/*.md、根 README/AGENTS、第三方说明和 MobilePerf 移植说明；
- 现状文档的 status、核实日期及风险账本 owner 必须符合知识库约定；
- 正文中的相对 Markdown 链接（不含 http/https/mailto 与纯锚点）必须能解析到已存在文件；
- frontmatter 中 related 列出的路径按同一规则解析（支持流式与块式 YAML 列表）。

退出码：0 表示全部通过，1 表示存在错误。
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PROJECT_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "mobileperf" / "readme.md",
)

LINK_RE = re.compile(r"\]\(([^()]+)\)")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
REQUIRED_KEYS = ("status", "last_verified")


def parse_frontmatter(text: str) -> dict | None:
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
    rel_display = path.relative_to(ROOT).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{rel_display}: 无法读取文件 -> {exc}")
        return errors
    frontmatter = parse_frontmatter(text)

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
            if "status" in frontmatter and frontmatter["status"] not in (
                "current", "under-review"
            ):
                errors.append(f"{rel_display}: status 必须为 current 或 under-review")
            if "last_verified" in frontmatter:
                verified = frontmatter["last_verified"]
                try:
                    if not isinstance(verified, str) or not re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}", verified
                    ):
                        raise ValueError("核实日期格式无效")
                    date.fromisoformat(verified)
                except ValueError:
                    errors.append(f"{rel_display}: last_verified 必须为有效的 YYYY-MM-DD 日期")
            if path.name == "RISKS_AND_DEBT.md":
                owner = frontmatter.get("owner")
                if not isinstance(owner, str) or not owner.strip():
                    errors.append(f"{rel_display}: 风险账本必须提供非空 owner，可填待确认")

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


def markdown_files() -> list[Path]:
    """返回需要持续校验的项目知识文档。"""

    return sorted({*DOCS.rglob("*.md"), *PROJECT_MARKDOWN})


def main() -> int:
    if not DOCS.exists():
        print(f"docs 目录不存在: {DOCS}", file=sys.stderr)
        return 1
    files = markdown_files()
    missing = [path for path in PROJECT_MARKDOWN if not path.is_file()]
    if missing:
        for path in missing:
            print(f"项目知识入口不存在: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    if not files:
        print("项目中没有可校验的 Markdown 文件", file=sys.stderr)
        return 1
    all_errors: list[str] = []
    for path in files:
        all_errors.extend(check_file(path))
    if all_errors:
        print(f"{len(all_errors)} 个问题：")
        for error in all_errors:
            print(f"  - {error}")
        return 1
    print(f"OK: {len(files)} 个项目知识文档的链接与 frontmatter 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
