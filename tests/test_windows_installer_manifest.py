"""安装载荷清单与隔离 staging 的行为回归。"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.windows_installer.manifest import (
    parse_manifest,
    stage_payload,
    validate_manifest,
    validate_payload,
)


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    root = tmp_path / "输入目录"
    (root / "_internal" / "tools").mkdir(parents=True)
    (root / "versioned.exe").write_bytes(b"main executable")
    (root / "_internal" / "tools" / "adb.exe").write_bytes(b"ADB executable")
    return root


def test_stage_preserves_source_and_preseeds_alias(payload: Path, tmp_path: Path) -> None:
    before = validate_payload(payload, "versioned.exe")
    staged = tmp_path / "staging"
    manifest = stage_payload(payload, "versioned.exe", staged)
    assert validate_payload(payload, "versioned.exe") == before
    files = validate_manifest(manifest, staged)
    assert "ADBLab.exe" in files and "versioned.exe" not in files
    assert files["_internal/tools/adb.exe"] == files["_internal/tools/adblab-adb.exe"]
    assert manifest.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    "path",
    [
        "../bad",
        "/bad",
        "C:/bad",
        "a\\b",
        "a:stream",
        "a//b",
        "a/./b",
        "a/../b",
        "a.",
        "a ",
        "CON",
        "nul.txt",
        ".adblab-install.ini",
        ".adblab-maintenance.lock",
        ".adblab-files.txt",
        ".adblab-pending-files.txt",
        "unins000.exe",
        "a\tb",
        "a\nb",
    ],
)
def test_manifest_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        parse_manifest(("\ufeff" + "a" * 64 + "\t" + path + "\n").encode("utf-8"))


@pytest.mark.parametrize(
    "body",
    [
        "a" * 63 + "\tx\n",
        "A" * 64 + "\tx\n",
        "z" * 64 + "\tx\n",
        "a" * 64 + " x\n",
        "",
        "a" * 64 + "\tx\n" + "b" * 64 + "\tX\n",
        "a" * 64 + "\tx\n" + "b" * 64 + "\tx/child\n",
    ],
)
def test_manifest_rejects_invalid_format_or_collisions(body: str) -> None:
    with pytest.raises(ValueError):
        parse_manifest(("\ufeff" + body).encode("utf-8"))


def test_manifest_requires_bom() -> None:
    with pytest.raises(ValueError):
        parse_manifest(("a" * 64 + "\tx\n").encode())


@pytest.mark.parametrize(
    "damage", ["missing_entry", "empty_entry", "missing_internal", "reserved", "alias_collision"]
)
def test_bad_payload_rejected_before_staging(payload: Path, tmp_path: Path, damage: str) -> None:
    if damage == "missing_entry":
        (payload / "versioned.exe").unlink()
    elif damage == "empty_entry":
        (payload / "versioned.exe").write_bytes(b"")
    elif damage == "missing_internal":
        (payload / "_internal").rename(payload / "other")
    elif damage == "reserved":
        (payload / ".adblab-install.ini").write_text("forged")
    else:
        (payload / "_internal/tools/adblab-adb.exe").write_bytes(b"different")
    staged = tmp_path / "staging"
    with pytest.raises(ValueError):
        stage_payload(payload, "versioned.exe", staged)
    assert not staged.exists()


def test_manifest_checks_actual_digest(payload: Path, tmp_path: Path) -> None:
    staged = tmp_path / "staging"
    manifest = stage_payload(payload, "versioned.exe", staged)
    (staged / "ADBLab.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="摘要"):
        validate_manifest(manifest, staged)


def test_staging_cannot_overlap_source(payload: Path) -> None:
    with pytest.raises(ValueError):
        stage_payload(payload, "versioned.exe", payload / "staging")


def test_target_directory_must_be_new(payload: Path, tmp_path: Path) -> None:
    target = tmp_path / "staging"
    target.mkdir()
    (target / "keep").write_text("user")
    with pytest.raises(ValueError):
        stage_payload(payload, "versioned.exe", target)
    assert (target / "keep").read_text() == "user"


def test_manifest_unicode_round_trip() -> None:
    digest = hashlib.sha256(b"data").hexdigest()
    assert parse_manifest(f"\ufeff{digest}\t_internal/中文 file.dll\n".encode()) == {
        "_internal/中文 file.dll": digest
    }


def test_payload_rejects_symlink(payload: Path, tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    link = payload / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        import subprocess

        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True
        )
    with pytest.raises(ValueError, match="重解析|链接"):
        validate_payload(payload, "versioned.exe")


def test_windows_alternate_stream_rejected(payload: Path) -> None:
    import sys

    if sys.platform != "win32":
        pytest.skip("NTFS alternate streams require Windows")
    Path(str(payload / "versioned.exe") + ":hidden").write_bytes(b"hidden")
    with pytest.raises(ValueError, match="数据流"):
        validate_payload(payload, "versioned.exe")


def test_native_inno_protocol_probe(tmp_path: Path) -> None:
    """只运行安装前终止的独立协议探针，不安装产品或写入注册表。"""
    from core import windows_installation as protocol

    repository = Path(__file__).resolve().parents[1]
    compiler = repository / "build/tools/inno-6.7.3/ISCC.exe"
    if sys.platform != "win32" or not compiler.is_file():
        pytest.skip("固定 Inno 6.7.3 尚未在构建目录准备，原生协议探针未运行")
    definitions = {
        "InstallAppId": protocol.APP_ID,
        "MainExecutable": protocol.MAIN_EXECUTABLE,
        "InstallMarker": protocol.INSTALL_MARKER,
        "InstallManifest": protocol.INSTALL_MANIFEST,
        "InstallPendingManifest": protocol.INSTALL_PENDING_MANIFEST,
        "InstallPreviousManifest": protocol.INSTALL_PREVIOUS_MANIFEST,
        "InstallLock": protocol.INSTALL_LOCK,
        "InstallSection": protocol.INSTALL_SECTION,
    }
    include = tmp_path / "protocol.iss"
    include.write_text(
        "".join(f'#define {key} "{value}"\n' for key, value in definitions.items()),
        encoding="utf-8",
    )
    report = tmp_path / "result.txt"
    compilation = subprocess.run(
        [
            str(compiler),
            "/Q",
            f"/DProtocolInclude={include}",
            f"/DProbeOutput={report}",
            f"/DProbeRoot={tmp_path / 'scratch'}",
            f"/O{tmp_path}",
            str(repository / "tests/fixtures/windows_installer/protocol_probe.iss"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert compilation.returncode == 0, compilation.stdout + compilation.stderr
    run = subprocess.run(
        [str(tmp_path / "protocol-probe.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 1  # InitializeSetup 返回 False，阻断任何真实安装事件。
    assert report.read_text(encoding="utf-8").strip() == "PASS"
