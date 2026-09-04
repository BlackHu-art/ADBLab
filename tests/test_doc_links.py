from pathlib import Path

from scripts import check_doc_links


def test_markdown_files_include_project_entrypoints():
    files = set(check_doc_links.markdown_files())

    assert set(check_doc_links.PROJECT_MARKDOWN) <= files
    assert all(isinstance(path, Path) for path in files)


def test_project_knowledge_links_are_valid():
    assert check_doc_links.main() == 0
