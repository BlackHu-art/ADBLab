from pathlib import Path

import pytest

from scripts import check_doc_links


def test_markdown_files_include_project_entrypoints():
    files = set(check_doc_links.markdown_files())

    assert set(check_doc_links.PROJECT_MARKDOWN) <= files
    assert all(isinstance(path, Path) for path in files)
    assert check_doc_links.ROOT / "AGENTS.md" in files


def test_project_knowledge_links_are_valid():
    assert check_doc_links.main() == 0


@pytest.mark.parametrize(
    ("metadata", "filename", "error_key"),
    [
        ("status: obsolete\nlast_verified: 2026-09-05", "PAGE.md", "status"),
        ("status: current\nlast_verified: 2026-02-30", "PAGE.md", "last_verified"),
        ("status: current\nlast_verified: 20260905", "PAGE.md", "last_verified"),
        ("status: current\nlast_verified:", "PAGE.md", "last_verified"),
        ("status: current\nlast_verified: 2026-09-05", "RISKS_AND_DEBT.md", "owner"),
        (
            "status: current\nlast_verified: 2026-09-05\nowner:",
            "RISKS_AND_DEBT.md",
            "owner",
        ),
    ],
)
def test_knowledge_metadata_rejects_invalid_values(
    tmp_path, monkeypatch, metadata, filename, error_key
):
    monkeypatch.setattr(check_doc_links, "ROOT", tmp_path)
    path = tmp_path / "docs" / "project-knowledge" / filename
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{metadata}\n---\n\n# 页面\n", encoding="utf-8")

    errors = check_doc_links.check_file(path)

    assert len(errors) == 1
    assert error_key in errors[0]


@pytest.mark.parametrize("status", ["current", "under-review"])
def test_knowledge_metadata_accepts_documented_states(tmp_path, monkeypatch, status):
    monkeypatch.setattr(check_doc_links, "ROOT", tmp_path)
    path = tmp_path / "docs" / "project-knowledge" / "RISKS_AND_DEBT.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nstatus: {status}\nlast_verified: 2024-02-29\nowner: 待确认\n---\n\n# 风险\n",
        encoding="utf-8",
    )

    assert check_doc_links.check_file(path) == []
