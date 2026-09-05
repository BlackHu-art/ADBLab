"""验证中文注释静态门禁的范围、识别和豁免规则。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "check_comment_language.py"
SPEC = importlib.util.spec_from_file_location("check_comment_language", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


def _write_source(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_checker_reports_english_comments_and_docstrings(tmp_path):
    path = _write_source(
        tmp_path,
        '''"""English module documentation."""

# Explain the business rule.
VALUE = 1
''',
    )

    issues = CHECKER.scan_file(path)

    assert {(issue.kind, issue.line) for issue in issues} == {
        ("docstring", 1),
        ("comment", 3),
    }


def test_checker_accepts_chinese_and_explicit_machine_exemptions(tmp_path):
    path = _write_source(
        tmp_path,
        '''#!/usr/bin/env python3
"""说明模块职责，并保留 TaskSupervisor 技术名称。"""

# noqa: F401
# type: ignore[assignment]
# https://example.invalid/spec
# py -3.11 -m pytest -q
# OperationState.SUCCEEDED
VALUE = 1
MESSAGE = "This ordinary runtime string is not a comment."
''',
    )

    assert CHECKER.scan_file(path) == []


def test_checker_reports_common_mojibake_in_comments_and_docstrings(tmp_path):
    path = _write_source(
        tmp_path,
        '''"""说明模块职责。"""

# 锛
# 銆
# 鈥
# �
# ��
def broken():
    """乱码鈥说明。"""
''',
    )

    issues = CHECKER.scan_file(path)

    assert [issue.kind for issue in issues] == [
        "mojibake-comment",
        "mojibake-comment",
        "mojibake-comment",
        "mojibake-comment",
        "mojibake-comment",
        "mojibake-docstring",
    ]


def test_checker_requires_module_documentation(tmp_path):
    path = _write_source(tmp_path, "VALUE = 1\n")

    issues = CHECKER.scan_file(path)

    assert [(issue.kind, issue.line) for issue in issues] == [("module-docstring", 1)]


@pytest.mark.parametrize(
    "relative_path",
    [
        "adblab/sample.py",
        "controllers/sample.py",
        "core/sample.py",
        "gui/sample.py",
        "models/sample.py",
        "services/sample.py",
        "utils/sample.py",
        "main.py",
        "mobileperf/common/sample.py",
        "mobileperf/android/sample.py",
    ],
)
def test_default_scope_detects_first_party_violations(tmp_path, relative_path):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('"""说明模块职责。"""\n# Explain the business rule.\n', encoding="utf-8")

    assert [(issue.path, issue.kind) for issue in CHECKER.scan_paths(tmp_path)] == [
        (Path(relative_path), "comment")
    ]


def test_default_scope_current_sources_are_clean():

    assert CHECKER.scan_paths(ROOT) == []
