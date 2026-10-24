"""扩展验收必须使用真实标准身份，失败必须阻断后续安装事件。"""

from pathlib import Path

import pytest


def _module():
    from scripts import check_windows_installer_extended
    return check_windows_installer_extended


def _args(tmp_path):
    return ["--installer", str(tmp_path / "setup.exe"), "--version", "v3.3.2",
            "--iscc", str(tmp_path / "ISCC.exe"), "--workspace", str(tmp_path / "work"),
            "--disposable", "--require-standard-user"]


def test_extended_entry_rejects_desktop_before_any_native_operation(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "run_extended", lambda *a, **k: pytest.fail("installed on desktop"))
    assert module.main(_args(tmp_path)) == 1
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("error", [ValueError("wrong identity"), OSError("token access")])
def test_extended_entry_rejects_identity_before_creating_workspace(tmp_path, monkeypatch, error):
    module = _module()
    monkeypatch.setattr(module.basic, "validate_environment", lambda path, disposable: path)
    monkeypatch.setattr(module, "standard_identity", lambda: (_ for _ in ()).throw(error))
    monkeypatch.setattr(module, "run_extended", lambda *a, **k: pytest.fail("ignored identity"))
    assert module.main(_args(tmp_path)) == 1
    assert not (tmp_path / "work").exists()


def test_extended_entry_propagates_phase_failure(tmp_path, monkeypatch, capsys):
    module = _module()
    monkeypatch.setattr(module.basic, "validate_environment", lambda path, disposable: path)
    monkeypatch.setattr(module, "standard_identity", lambda: {"sid": "test-account"})

    def fail(*args, **kwargs):
        raise RuntimeError("phase failed")

    monkeypatch.setattr(module, "run_extended", fail)
    assert module.main(_args(tmp_path)) == 1
    assert "phase failed" in capsys.readouterr().err


def test_default_install_keeps_formal_repair_before_final_uninstall(tmp_path, monkeypatch):
    module = _module()
    events = []
    profile = tmp_path / "profile"
    local = profile / "AppData/Local"
    identity = {"profile": str(profile), "local_appdata": str(local)}
    app = local / "Programs/ADBLab"

    def command(argv, *args, **kwargs):
        assert all(not arg.startswith("/DIR=") for arg in argv)
        assert "/TASKS=desktopicon" in argv
        events.append("formal-setup")
        app.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module.basic, "run_checked", command)
    monkeypatch.setattr(module.basic, "_assert_ready", lambda *a: {"ADBLab.exe"})
    monkeypatch.setattr(module, "check_user_installation",
                        lambda *a: events.append("user-integration"))
    monkeypatch.setattr(module, "product_race", lambda *a, **k: events.append("race"))
    monkeypatch.setattr(module.basic, "_uninstall", lambda *a: events.append("uninstall"))
    module.run_default_installation(Path("setup.exe"), "3.3.2", Path("ISCC.exe"),
                                    tmp_path / "lifecycle", identity)
    assert events == ["formal-setup", "user-integration", "race", "formal-setup",
                      "user-integration", "uninstall"]
    assert (app / "unmanaged-user-file.txt").read_bytes() == b"preserve unknown file\n"


def test_default_install_preserves_failure_evidence_without_uninstall(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.basic, "run_checked", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("setup refused")))
    monkeypatch.setattr(module.basic, "_uninstall", lambda *a: pytest.fail("deleted evidence"))
    with pytest.raises(RuntimeError, match="setup refused"):
        module.run_default_installation(Path("setup.exe"), "3.3.2", Path("ISCC.exe"),
                                        tmp_path / "lifecycle",
                                        {"profile": str(tmp_path / "home"),
                                         "local_appdata": str(tmp_path / "local")})


def test_fault_failure_stops_legacy_and_default_installation(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.basic, "main", lambda args: 0)
    monkeypatch.setattr(module, "run_fault_fixture", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("fault scenario failed")))
    monkeypatch.setattr(module, "run_legacy_upgrade",
                        lambda *a, **k: pytest.fail("continued legacy"))
    monkeypatch.setattr(module, "run_default_installation",
                        lambda *a: pytest.fail("continued setup"))
    with pytest.raises(RuntimeError, match="fault scenario failed"):
        module.run_extended(Path("setup.exe"), "3.3.2", Path("ISCC.exe"), tmp_path / "work", {})


def test_default_install_refuses_existing_location_before_writes(tmp_path, monkeypatch):
    module = _module()
    local = tmp_path / "local"
    app = local / "Programs/ADBLab"
    app.mkdir(parents=True)
    kept = app / "existing.txt"
    kept.write_bytes(b"existing content")
    monkeypatch.setattr(module.basic, "run_checked", lambda *a, **k: pytest.fail("reused app"))
    with pytest.raises(ValueError, match="已存在"):
        module.run_default_installation(Path("setup.exe"), "3.3.2", Path("ISCC.exe"),
                                        tmp_path / "work", {"local_appdata": str(local)})
    assert kept.read_bytes() == b"existing content"
    assert not (tmp_path / "work").exists()
