"""固定编译器来源、便携部署和无隐式覆盖的准备边界。"""

import hashlib
import json
from types import SimpleNamespace

import pytest


def _module():
    from scripts import prepare_inno_setup
    return prepare_inno_setup


def test_destination_is_confined_to_build_or_runner_scratch(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    assert module.validate_destination(tmp_path / "build/tools/inno-6.7.3").is_relative_to(tmp_path)
    for target in (tmp_path, tmp_path / "build", tmp_path / "sources/inno-6.7.3"):
        with pytest.raises(ValueError):
            module.validate_destination(target)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))
    assert module.validate_destination(tmp_path / "runner/inno-6.7.3").name == "inno-6.7.3"


def test_portable_command_does_not_register_or_launch_tools(tmp_path):
    module = _module()
    args = module.portable_command(
        tmp_path / "download.exe", tmp_path / "工具 space", tmp_path / "log",
    )
    assert args[0] == str(tmp_path / "download.exe")
    assert {"/PORTABLE=1", "/CURRENTUSER", "/VERYSILENT", "/NORESTART", "/NOICONS"} <= set(args)
    assert "/NOCLOSEAPPLICATIONS" in args and "/NORESTARTAPPLICATIONS" in args
    assert f"/DIR={tmp_path / '工具 space'}" in args


def test_digest_failure_never_verifies_or_executes_download(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    archive = tmp_path / "untrusted.exe"
    archive.write_bytes(b"bad")
    monkeypatch.setattr(module, "verify_signature", lambda _: pytest.fail("untrusted executable"))
    with pytest.raises(ValueError, match="SHA256"):
        module.prepare(tmp_path / "build/inno-6.7.3", archive=archive)


def test_nonempty_unowned_directory_is_not_replaced(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    target = tmp_path / "build/inno-6.7.3"
    target.mkdir(parents=True)
    sentinel = target / "user.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        module.prepare(target)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_prepared_receipt_rejects_changed_or_extra_compiler_files(tmp_path):
    module = _module()
    target = tmp_path / "compiler"
    target.mkdir()
    (target / "ISCC.exe").write_bytes(b"compiler")
    (target / module.RECEIPT).write_text(json.dumps({
        "version": module.INNO_VERSION, "archive_sha256": module.INNO_SHA256,
        "files": {"ISCC.exe": hashlib.sha256(b"compiler").hexdigest()},
    }), encoding="utf-8")
    module.verify_receipt(target)
    (target / "injected.dll").write_bytes(b"extra")
    with pytest.raises(ValueError):
        module.verify_receipt(target)


def test_signature_or_deployment_failure_does_not_publish_receipt(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    archive = tmp_path / "fixture.exe"
    archive.write_bytes(b"fixture")
    monkeypatch.setattr(module, "INNO_SHA256", hashlib.sha256(b"fixture").hexdigest())
    def reject(_):
        raise ValueError("signature rejected")
    monkeypatch.setattr(module, "verify_signature", reject)
    target = tmp_path / "build/inno-6.7.3"
    with pytest.raises(ValueError, match="signature"):
        module.prepare(target, archive=archive)
    assert not (target / module.RECEIPT).exists()


def test_prepare_dry_run_does_not_create_or_download(tmp_path, monkeypatch, capsys):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    target = tmp_path / "build/inno-6.7.3"
    monkeypatch.setattr(module, "prepare", lambda *a, **k: pytest.fail("dry run prepared"))
    assert module.main(["--destination", str(target), "--dry-run"]) == 0
    assert module.INNO_VERSION in capsys.readouterr().out
    assert not target.exists()


def test_signature_shell_does_not_inherit_incompatible_module_search_path(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setenv("PSModulePath", "foreign-powershell-modules")
    def run(command, **kwargs):
        assert not any(key.casefold() == "psmodulepath" for key in kwargs["env"])
        assert kwargs["env"]["ADBLAB_VERIFY_FILE"] == str(tmp_path / "tool.exe")
        assert str(tmp_path / "tool.exe") not in command[-1]
        return SimpleNamespace(returncode=0, stdout="")
    monkeypatch.setattr(module.subprocess, "run", run)
    module.verify_signature(tmp_path / "tool.exe")


@pytest.mark.parametrize("version", ["6.7.3", "6.7.2", "7.0.0"])
def test_compiler_uses_verified_engine_version_instead_of_zero_file_resource(
    tmp_path, monkeypatch, version,
):
    module = _module()
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"verified-fixture")
    monkeypatch.setattr(module, "verify_signature", lambda _: None)
    monkeypatch.setattr(module, "_powershell", lambda *a: "0.0.0.0")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=f"Compiler engine version: Inno Setup {version}\n", stderr="",
    ))
    if version == module.INNO_VERSION:
        module.verify_compiler(compiler)
    else:
        with pytest.raises(ValueError, match="6.7.3"):
            module.verify_compiler(compiler)
