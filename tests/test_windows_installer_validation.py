"""真实安装验收必须显式隔离，退出码不能替代文件和注册状态。"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module():
    from scripts import check_windows_installer
    return check_windows_installer


def test_normal_desktop_cannot_run_product_install_smoke(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="一次性"):
        module.validate_environment(tmp_path, disposable=True)


def test_requires_explicit_disposable_and_runner_temp(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("RUNNER_OS", "Windows")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(ValueError):
        module.validate_environment(tmp_path / "work", disposable=False)
    with pytest.raises(ValueError):
        module.validate_environment(tmp_path, disposable=True)
    with pytest.raises(ValueError):
        module.validate_environment(tmp_path.parent / "unrelated", disposable=True)
    assert module.validate_environment(tmp_path / "work", disposable=True) == tmp_path / "work"


def test_existing_workspace_is_never_reused_or_cleaned(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("RUNNER_OS", "Windows")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    workspace = tmp_path / "work"
    workspace.mkdir()
    sentinel = workspace / "data.txt"
    sentinel.write_bytes(b"keep")
    with pytest.raises(ValueError):
        module.validate_environment(workspace, disposable=True)
    assert sentinel.read_bytes() == b"keep"


def test_run_checked_requires_expected_code_and_limits_wait(tmp_path, monkeypatch):
    module = _module()
    def run(command, **kwargs):
        assert kwargs["timeout"] == 180
        assert kwargs["stdin"] == module.subprocess.DEVNULL
        return SimpleNamespace(returncode=3010)
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="3010"):
        module.run_checked(["fixture.exe"], tmp_path / "log", env=os.environ.copy())


def test_uninstall_zero_with_payload_or_registration_left_is_failure(tmp_path, monkeypatch):
    module = _module()
    app = tmp_path / "app"
    app.mkdir()
    (app / "ADBLab.exe").write_bytes(b"left")
    monkeypatch.setattr(module, "registered_installations", lambda: [])
    with pytest.raises(RuntimeError):
        module.assert_uninstalled(app, {"ADBLab.exe"})
    (app / "ADBLab.exe").unlink()
    monkeypatch.setattr(module, "registered_installations", lambda: [{"path": str(app)}])
    with pytest.raises(RuntimeError):
        module.assert_uninstalled(app, {"ADBLab.exe"})


def test_dry_local_cli_failure_does_not_execute_installer(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "run_checked", lambda *a, **k: pytest.fail("installed on desktop"))
    assert module.main([
        "--installer", str(tmp_path / "setup.exe"), "--version", "v1.2.3",
        "--workspace", str(tmp_path / "work"), "--disposable",
    ]) == 1
    assert not (tmp_path / "work").exists()


def test_existing_installation_prevents_any_workspace_write(tmp_path, monkeypatch):
    module = _module()
    from scripts import check_build_artifacts
    monkeypatch.setattr(check_build_artifacts, "check_installer_file", lambda _: None)
    monkeypatch.setattr(module, "registered_installations", lambda: [{"path": "user app"}])
    monkeypatch.setattr(module, "run_checked", lambda *a, **k: pytest.fail("executed"))
    with pytest.raises(ValueError, match="已有产品"):
        module.smoke(tmp_path / "fixture.exe", "1.2.3", tmp_path / "work")
    assert not (tmp_path / "work").exists()


def test_timeout_is_not_successful_maintenance_rejection(tmp_path, monkeypatch):
    module = _module()
    def timeout(*args, **kwargs):
        raise module.subprocess.TimeoutExpired("fixture", 180)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(module.subprocess.TimeoutExpired):
        module.run_checked(["fixture.exe"], tmp_path / "log", env={}, reject=True)


def test_uninstall_success_code_with_shortcut_left_still_fails(tmp_path, monkeypatch):
    module = _module()
    app = tmp_path / "app"
    app.mkdir()
    link = tmp_path / "left.lnk"
    link.write_bytes(b"shortcut")
    monkeypatch.setattr(module, "run_checked", lambda *a, **k: None)
    monkeypatch.setattr(module, "registered_installations", lambda: [])
    monkeypatch.setattr(module, "_shortcuts", lambda: [link])
    clock = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    ))
    with pytest.raises(RuntimeError, match="快捷方式残留"):
        module._uninstall(app, tmp_path, "test", {}, set())
    assert 20 <= clock[0] < 21


@pytest.mark.parametrize("remaining", ["lock", "registration", "shortcut", "payload"])
def test_uninstall_waits_for_complete_second_phase(tmp_path, monkeypatch, remaining):
    """marker 与外层卸载器已消失时，仍须等待最后的锁、登记、快捷方式或载荷清理。"""
    module = _module()
    app = tmp_path / "app"
    app.mkdir()
    paths = {"lock": app / ".adblab-maintenance.lock", "shortcut": tmp_path / "app.lnk",
             "payload": app / "ADBLab.exe"}
    if remaining in paths:
        paths[remaining].write_bytes(b"pending second phase")
    entries = [{"path": str(app)}] if remaining == "registration" else []
    monkeypatch.setattr(module, "run_checked", lambda *a, **k: None)
    monkeypatch.setattr(module, "registered_installations", lambda: entries)
    monkeypatch.setattr(module, "_shortcuts", lambda: [paths["shortcut"]])
    clock = [0.0]

    def finish_second_phase(seconds):
        clock[0] += seconds
        if remaining in paths:
            paths[remaining].unlink()
        entries.clear()

    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=finish_second_phase,
    ))
    module._uninstall(app, tmp_path, "test", {}, {"ADBLab.exe"})
    assert clock[0] > 0
    assert not entries and not any(path.exists() for path in paths.values())


def test_uninstall_does_not_retry_registry_access_errors(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "run_checked", lambda *a, **k: None)

    def inaccessible():
        raise PermissionError("registry access denied")

    monkeypatch.setattr(module, "registered_installations", inaccessible)
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: 0.0, sleep=lambda seconds: pytest.fail("retried access failure"),
    ))
    with pytest.raises(PermissionError, match="registry access"):
        module._uninstall(tmp_path / "app", tmp_path, "test", {}, set())


def test_static_bad_package_is_clean_cli_failure(tmp_path, monkeypatch, capsys):
    module = _module()
    monkeypatch.setattr(module, "validate_environment", lambda *a: tmp_path / "work")
    broken = tmp_path / "broken.exe"
    broken.write_bytes(b"MZ")
    assert module.main([
        "--installer", str(broken), "--version", "v1.2.3",
        "--workspace", str(tmp_path / "work"), "--disposable",
    ]) == 1
    assert "FAIL" in capsys.readouterr().err
    assert not (tmp_path / "work").exists()


def test_sentinels_cover_real_shell_data_and_home_exports(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_known_folder", lambda folder: tmp_path / "shell-local")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "redirected"))
    sentinels = module._data_sentinels()
    assert {path.parent for path in sentinels} == {
        tmp_path / "shell-local/ADBLab", tmp_path / "home/ADBLab",
    }
    assert all(path.read_bytes() == value for path, value in sentinels.items())
    with pytest.raises(ValueError, match="哨兵"):
        module._data_sentinels()
    assert all(path.read_bytes() == value for path, value in sentinels.items())


def test_sentinels_preserve_directories_from_prior_packaging_probe(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_known_folder", lambda folder: tmp_path / "shell-local")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    settings = tmp_path / "shell-local/ADBLab/config/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b'{"preexisting": true}')
    export = tmp_path / "home/ADBLab/previous.txt"
    export.parent.mkdir(parents=True)
    export.write_bytes(b"previous export")
    sentinels = module._data_sentinels()
    assert all(path.read_bytes() == value for path, value in sentinels.items())
    assert settings.read_bytes() == b'{"preexisting": true}'
    assert export.read_bytes() == b"previous export"


def test_cli_runs_upgrade_before_product_and_failure_stops_product(tmp_path, monkeypatch):
    module = _module()
    from scripts import check_build_artifacts
    from tests.fixtures.windows_installer import upgrade_smoke
    monkeypatch.setattr(module, "validate_environment", lambda *a: tmp_path / "work")
    monkeypatch.setattr(check_build_artifacts, "check_installer_file", lambda _: None)
    events = []
    def upgrade(iscc, workspace, *, disposable):
        assert disposable is True
        assert workspace == tmp_path / "work/upgrade-fixture"
        assert iscc == tmp_path / "compiler.exe"
        events.append("upgrade")
    def smoke(installer, version, workspace):
        assert version == "1.2.3"
        assert workspace == tmp_path / "work/product-smoke"
        events.append("product")
    monkeypatch.setattr(upgrade_smoke, "run_upgrade_fixture", upgrade)
    monkeypatch.setattr(module, "smoke", smoke)
    args = ["--installer", str(tmp_path / "fixture.exe"), "--version", "v1.2.3",
            "--workspace", str(tmp_path / "work"), "--disposable",
            "--iscc", str(tmp_path / "compiler.exe")]
    assert module.main(args) == 0
    assert events == ["upgrade", "product"]
    events.clear()
    def fail(*args, **kwargs):
        events.append("upgrade")
        raise RuntimeError("upgrade validation failed")
    monkeypatch.setattr(upgrade_smoke, "run_upgrade_fixture", fail)
    assert module.main(args) == 1
    assert events == ["upgrade"]
