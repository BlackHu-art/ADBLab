"""用合成损坏文本验证 UTF-8/NUL 门禁，不读取真实设备或用户数据。"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("content", [b"valid\x00text", b"not utf8: \xff", b"\xff\xfea\x00"])
def test_checker_rejects_nul_and_undecodable_bytes(tmp_path, content):
    from scripts import check_source_text

    path = tmp_path / "broken.py"
    path.write_bytes(content)
    issues = check_source_text.check_file(path)
    assert issues
    assert all(issue.path == path for issue in issues)


@pytest.mark.parametrize("content", [
    "中文 = 1\r\n".encode(), b"\xef\xbb\xbfvalue = 1\n", b'data = b"\\x00\\xff"\n',
])
def test_checker_accepts_utf8_bom_and_generated_byte_literals(tmp_path, content):
    from scripts import check_source_text

    path = tmp_path / "translations_rc.py"
    path.write_bytes(content)
    assert check_source_text.check_file(path) == []


@pytest.mark.parametrize("name", [
    "main.py", "docs/guide.md", "resources/i18n/app.ts", ".github/workflows/Tests.yaml",
    "config.yml", "pyproject.toml", "ADBLab.spec", "requirements-dev.txt", "constraints.txt",
    "gui/generated/translations_rc.py", "mobileperf/android/adb_execution.py",
])
def test_first_party_text_scope_includes_build_inputs_and_generated_python(name):
    from scripts import check_source_text

    assert check_source_text.is_source_text(Path(name))


@pytest.mark.parametrize("name", [
    "mobileperf/extlib/vendor.py", "scrcpy-win64/README.md", "reference/source.py",
    ".venv/Lib/site-packages/module.py", "build/ADBLab.spec", "dist/main.py",
    "resources/app-icon-helper.jar", "resources/images/image.png", "resources/icon.svg",
])
def test_first_party_text_scope_excludes_vendor_generated_build_and_binary_files(name):
    from scripts import check_source_text

    assert not check_source_text.is_source_text(Path(name))


def test_cli_checks_untracked_sources_and_ignores_vendor_and_ignored_artifacts(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_bytes(b"\xff")
    (tmp_path / "README.md").write_bytes(b"valid\x00invalid")
    generated = tmp_path / "gui/generated/translations_rc.py"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"invalid\xff")
    vendor = tmp_path / "mobileperf/extlib/vendor.py"
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"\xff")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_source_text.py"), "--root", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 1
    assert "README.md" in result.stdout
    assert "translations_rc.py" in result.stdout
    assert "vendor.py" not in result.stdout
    assert "ignored.py" not in result.stdout


def test_cli_fails_closed_when_git_file_inventory_is_unavailable(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_source_text.py"), "--root", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 2
    assert "Git" in result.stdout
