"""安装器后处理必须保持 ZIP 输入，失败不能发布旧的安装 EXE。"""

from pathlib import Path
from types import SimpleNamespace

import pytest


def _payload(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "versioned.exe").write_bytes(b"program")
    (source / "_internal/tools").mkdir(parents=True)
    (source / "_internal/tools/adb.exe").write_bytes(b"adb")
    return source


def _module():
    from scripts import build_windows_installer
    return build_windows_installer


def test_dry_run_has_no_filesystem_or_process_side_effects(tmp_path, monkeypatch, capsys):
    module = _module()
    source = _payload(tmp_path)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("executed"))
    assert module.main([
        "--source-dir", str(source), "--entry-name", "versioned.exe",
        "--output-dir", str(tmp_path / "output"), "--dry-run",
    ]) == 0
    assert "-setup.exe" in capsys.readouterr().out
    assert before == sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))


def test_build_preserves_original_payload_and_injects_fixed_protocol(tmp_path, monkeypatch):
    module = _module()
    source = _payload(tmp_path)
    original = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"compiler")
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    def compile_installer(command, **kwargs):
        stage = Path(next(arg.removeprefix("/DAppSourceDir=") for arg in command
                          if arg.startswith("/DAppSourceDir=")))
        include = Path(next(arg.removeprefix("/DProtocolInclude=") for arg in command
                            if arg.startswith("/DProtocolInclude=")))
        assert (stage / "ADBLab.exe").read_bytes() == b"program"
        assert (stage / "_internal/tools/adblab-adb.exe").read_bytes() == b"adb"
        assert "1C0CD5FE-33F4-4BB0-964D-F2EC6A79F062" in include.read_text(encoding="utf-8-sig")
        out = Path(next(arg[2:] for arg in command if arg.startswith("/O")))
        name = next(arg[2:] for arg in command if arg.startswith("/F"))
        (out / f"{name}.exe").write_bytes(b"MZfixture")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", compile_installer)
    monkeypatch.setattr(module, "check_installer_file", lambda _: None)
    output = module.build(source, "versioned.exe", tmp_path / "output", compiler)
    assert output.name.endswith("-setup.exe")
    assert original == {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("returncode,creates_output", [(5, True), (0, False)])
def test_compiler_failure_or_missing_output_is_not_success(
    tmp_path, monkeypatch, returncode, creates_output,
):
    module = _module()
    source = _payload(tmp_path)
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"compiler")
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    def compile_installer(command, **kwargs):
        if creates_output:
            out = Path(next(arg[2:] for arg in command if arg.startswith("/O")))
            name = next(arg[2:] for arg in command if arg.startswith("/F"))
            (out / f"{name}.exe").write_bytes(b"partial")
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(module.subprocess, "run", compile_installer)
    output = tmp_path / "output"
    with pytest.raises((ValueError, RuntimeError)):
        module.build(source, "versioned.exe", output, compiler)
    assert not list(output.glob("*.exe"))


def test_invalid_input_fails_before_compiler_or_staging(tmp_path, monkeypatch):
    module = _module()
    source = _payload(tmp_path)
    monkeypatch.setattr(module, "verify_compiler", lambda _: pytest.fail("verified too early"))
    with pytest.raises(ValueError):
        module.build(source, "missing.exe", tmp_path / "output", tmp_path / "ISCC.exe")
    assert not (tmp_path / "output").exists()


def test_compiler_timeout_keeps_previous_installer(tmp_path, monkeypatch):
    module = _module()
    source = _payload(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    previous = output / module.output_name()
    previous.write_bytes(b"previous valid installer")
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    def timeout(*args, **kwargs):
        raise module.subprocess.TimeoutExpired("ISCC", 900)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    assert module.main([
        "--source-dir", str(source), "--entry-name", "versioned.exe", "--output-dir", str(output),
    ]) == 1
    assert previous.read_bytes() == b"previous valid installer"
    assert list(output.iterdir()) == [previous]


def test_invalid_pe_is_clean_cli_failure(tmp_path, monkeypatch, capsys):
    module = _module()
    source = _payload(tmp_path)
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    def compile_installer(command, **kwargs):
        out = Path(next(arg[2:] for arg in command if arg.startswith("/O")))
        (out / module.output_name()).write_bytes(b"MZnot-a-pe")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", compile_installer)
    assert module.main([
        "--source-dir", str(source), "--entry-name", "versioned.exe",
        "--output-dir", str(tmp_path / "output"),
    ]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_failed_publish_copy_cleans_private_temporary_and_preserves_old_output(
    tmp_path, monkeypatch,
):
    module = _module()
    source = _payload(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output = output_dir / module.output_name()
    output.write_bytes(b"previous valid installer")
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    monkeypatch.setattr(module, "check_installer_file", lambda _: None)
    def compile_installer(command, **kwargs):
        out = Path(next(arg[2:] for arg in command if arg.startswith("/O")))
        (out / module.output_name()).write_bytes(b"new installer")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", compile_installer)
    original_open = Path.open
    def fail_candidate_read(path, mode="r", *args, **kwargs):
        if path.name == module.output_name() and mode == "rb" and path.parent != output_dir:
            raise OSError("copy interrupted")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_candidate_read)
    with pytest.raises(OSError, match="copy interrupted"):
        module.build(source, "versioned.exe", output_dir, tmp_path / "ISCC.exe")
    assert output.read_bytes() == b"previous valid installer"
    assert list(output_dir.iterdir()) == [output]
