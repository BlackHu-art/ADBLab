"""标准账户验收在本机只替换系统边界，绝不创建账号或安装产品。"""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SID = "S-1-5-21-111-222-333-1009"


def module():
    from scripts.windows_installer import standard_user
    return standard_user


@pytest.fixture
def identity(tmp_path, monkeypatch):
    profile = tmp_path / "标准用户"
    profile.mkdir()
    value = {
        "sid": SID, "elevated": False, "groups": ["S-1-5-32-545"],
        "profile_loaded": True, "profile": str(profile),
        "local_appdata": str(profile / "AppData/Local"),
        "appdata": str(profile / "AppData/Roaming"),
        "programs": str(profile / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs"),
        "desktop": str(profile / "Desktop"),
    }
    for name in ("local_appdata", "appdata", "programs", "desktop"):
        Path(value[name]).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", value["local_appdata"])
    monkeypatch.setenv("APPDATA", value["appdata"])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: profile))
    return value


def test_identity_checks_actual_token_and_profile(identity, monkeypatch):
    api = module()
    monkeypatch.setattr(api, "_read_windows_identity", lambda: identity.copy())
    assert api.assert_standard_user(SID)["sid"] == SID


@pytest.mark.parametrize("change", [
    {"sid": "S-1-5-18"}, {"elevated": True},
    {"groups": ["S-1-5-32-544"]}, {"profile_loaded": False},
    {"profile": "relative"}, {"local_appdata": ""},
])
def test_invalid_identity_fails_closed(identity, monkeypatch, change):
    api = module()
    monkeypatch.setattr(api, "_read_windows_identity", lambda: identity | change)
    with pytest.raises((ValueError, OSError)):
        api.assert_standard_user(SID)


def test_expected_sid_and_parent_profile_are_rejected(identity, monkeypatch, tmp_path):
    api = module()
    monkeypatch.setattr(api, "_read_windows_identity", lambda: identity.copy())
    with pytest.raises(ValueError):
        api.assert_standard_user(SID + "0")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with pytest.raises(ValueError):
        api.assert_standard_user(SID)


def test_environment_is_allowlisted_and_uses_loaded_profile(identity, tmp_path):
    api = module()
    parent = {"SystemRoot": "C:\\Windows", "PATH": "trusted-tools",
              "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
              "RUNNER_OS": "Windows", "RUNNER_TEMP": str(tmp_path),
              "SECRET_TOKEN": "do-not-inherit", "PYTHONPATH": "parent", "HOME": "parent"}
    env = api.build_environment(identity, parent)
    assert not ({"SECRET_TOKEN", "PYTHONPATH", "HOME"} & env.keys())
    assert env["USERPROFILE"] == identity["profile"]
    assert env["LOCALAPPDATA"] == identity["local_appdata"]
    assert env["TEMP"] == str(Path(identity["local_appdata"]) / "Temp")


@pytest.fixture
def job(tmp_path, monkeypatch):
    for name, value in {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                        "RUNNER_OS": "Windows", "RUNNER_TEMP": str(tmp_path)}.items():
        monkeypatch.setenv(name, value)
    workspace = tmp_path / "new run space"
    workspace.mkdir()
    values = {"version": "v1.2.3", "expected_sid": SID, "workspace": str(workspace)}
    for key in ("installer", "iscc", "python"):
        target = tmp_path / f"{key}.exe"
        target.write_bytes(b"fixture")
        values[key] = str(target)
    path = workspace / "job.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path, values


def test_job_rejects_unknown_fields_and_unsafe_workspace(job, tmp_path):
    api = module()
    path, values = job
    assert api.load_job(path)["version"] == "v1.2.3"
    path.write_text(json.dumps(values | {"password": "must-not-accept"}), encoding="utf-8")
    with pytest.raises(ValueError):
        api.load_job(path)
    path.write_text(json.dumps(values | {"workspace": str(tmp_path)}), encoding="utf-8")
    with pytest.raises(ValueError):
        api.load_job(path)


def test_bootstrap_propagates_exit_and_does_not_inherit_secrets(job, identity, monkeypatch):
    api = module()
    path, values = job
    monkeypatch.setenv("SECRET_TOKEN", "never-print-this")
    monkeypatch.setattr(api, "_read_windows_identity", lambda: identity.copy())
    seen = []
    def run(command, **kwargs):
        seen.append(command)
        assert "SECRET_TOKEN" not in kwargs["env"]
        assert kwargs["cwd"] == api.ROOT
        assert command[-1] == "--require-standard-user"
        # 总超时由仍存活的外层 wrapper 处理，避免先杀父进程而留下安装器后代。
        assert "timeout" not in kwargs
        assert command[command.index("--workspace") + 1] == str(Path(values["workspace"]) / "run")
        return SimpleNamespace(returncode=37)
    monkeypatch.setattr(api.subprocess, "run", run)
    assert api.main(["--job", str(path)]) == 37
    assert len(seen) == 1
    assert os.environ.get("SECRET_TOKEN") == "never-print-this"


def test_wrong_sid_never_launches_product(job, identity, monkeypatch):
    api = module()
    path, _ = job
    monkeypatch.setattr(api, "_read_windows_identity", lambda: identity | {"sid": SID + "0"})
    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: pytest.fail("product started"))
    assert api.main(["--job", str(path)]) == 1


def test_exact_user_registration_and_shortcut_targets(identity, tmp_path, monkeypatch):
    api = module()
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(api, "assert_standard_user", lambda sid=None: identity)
    calls = []
    def registration(hive, view, sid=None):
        calls.append((hive, view, sid))
        return None if hive == "HKLM" else {"path": str(app), "version": "1.2.3"}
    monkeypatch.setattr(api, "_read_registration", registration)
    monkeypatch.setattr(api, "_read_shortcut", lambda path: {
        "target": str(app / "ADBLab.exe"), "working_directory": str(app)})
    api.assert_current_user_installation(app, "1.2.3", identity)
    assert ("HKU", 64, SID) in calls
    assert {("HKLM", 64, None), ("HKLM", 32, None)} <= set(calls)


@pytest.mark.parametrize("bad", ["hklm", "hku", "version", "target", "working_directory"])
def test_wrong_registration_or_shortcut_is_failure(identity, tmp_path, monkeypatch, bad):
    api = module()
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(api, "assert_standard_user", lambda sid=None: identity)
    def registration(hive, view, sid=None):
        if hive == "HKLM":
            return {} if bad == "hklm" else None
        return {"path": str(tmp_path if bad == "hku" and hive == "HKU" else app),
                "version": "wrong" if bad == "version" else "1.2.3"}
    monkeypatch.setattr(api, "_read_registration", registration)
    shortcut = {"target": str(app / "ADBLab.exe"), "working_directory": str(app)}
    if bad in shortcut:
        shortcut[bad] = str(tmp_path / "other")
    monkeypatch.setattr(api, "_read_shortcut", lambda path: shortcut)
    with pytest.raises(ValueError):
        api.assert_current_user_installation(app, "1.2.3", identity)


def test_shortcut_reader_uses_literal_file_args_and_validates_json(tmp_path, monkeypatch):
    api = module()
    link = tmp_path / "中文 & literal.lnk"
    link.write_bytes(b"fixture")
    def run(command, **kwargs):
        assert "-Command" not in command
        assert Path(command[0]).name == "pwsh.exe"
        assert command[-2:] == ["-LiteralPath", str(link)]
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "target": "C:\\app.exe", "working_directory": "C:\\app"}))
    monkeypatch.setattr(api.subprocess, "run", run)
    assert api._read_shortcut(link)["target"]
    monkeypatch.setattr(api.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="{}"))
    with pytest.raises(ValueError):
        api._read_shortcut(link)


def test_powershell_parent_rejects_local_desktop_before_any_account_operation(tmp_path):
    import shutil
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("需要 PowerShell 执行只读入口拒绝检查")
    script = Path(__file__).resolve().parents[1] / "scripts/run_windows_installer_standard_user.ps1"
    assert script.is_file()
    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(script),
                             "-Installer", "absent", "-Version", "v1", "-Iscc", "absent",
                             "-Python", "absent", "-Workspace", str(tmp_path / "never-created"),
                             "-Disposable"], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "一次性" in result.stderr
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("child_code,cleanup_fails", [
    (0, False), (37, False), (0, True), (-1, False), (0, 2),
])
def test_powershell_lifecycle_propagates_child_and_cleanup_failure(
    tmp_path, child_code, cleanup_fails,
):
    import shutil
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("需要 PowerShell 执行替身生命周期测试")
    script = Path(__file__).resolve().parents[1] / "scripts/run_windows_installer_standard_user.ps1"
    assert script.is_file()
    fixture = tmp_path / "lifecycle.ps1"
    # 每个系统修改边界均由替身接管；即使漏调顺序也绝不运行真实账号命令。
    fixture.write_text(r'''
param($Source, $Workspace, [int]$ChildCode, [int]$CleanupFails)
$ErrorActionPreference = 'Stop'
$savedWorkspace = $Workspace
. $Source
$Workspace = $savedWorkspace
function Assert-ParentContext { param($Installer,$Version,$Iscc,$Python,$Workspace,$Disposable)
    return @{installer='fixture.exe'; version='v1'; iscc='fixture.exe';
             python='fixture.exe';workspace=$Workspace}
}
function New-LocalUser { param($Name,$Password,$Description,$ErrorAction)
    if ($Password -isnot [Security.SecureString]) { throw '密码类型错误' }
    $script:CreatedValidationName = $Name
    return [pscustomobject]@{Name=$Name; SID='S-1-5-21-111-222-333-1009'}
}
function Add-LocalGroupMember { param($SID,$Member,$ErrorAction) }
function Get-LocalGroupMember { param($SID,$ErrorAction) return @() }
function Set-ValidationWorkspaceAccess { param($Workspace,$Sid) }
function Start-ValidationProcess { param($Job,$Credential)
    if ($Credential -isnot [Management.Automation.PSCredential]) { throw '凭证类型错误' }
    if ($ChildCode -eq -1) { throw 'hidden-test-password' }
    @('unrelated-private-detail', 'START fixture phase', 'PASS fixture accepted') |
        Set-Content -LiteralPath (Join-Path $Job.workspace 'stdout.log') -Encoding utf8
    return $ChildCode
}
function Get-LocalUser { param($SID,$ErrorAction)
    if ($CleanupFails -eq 2) {
        return [pscustomobject]@{Name=$script:CreatedValidationName; SID='S-1-5-21-1-2-3-9999'}
    }
    return [pscustomobject]@{Name=$script:CreatedValidationName; SID=$SID}
}
function Remove-LocalUser { param($SID,$ErrorAction)
    if ($SID -ne 'S-1-5-21-111-222-333-1009') { throw '删除目标不正确' }
    Set-Content -LiteralPath (Join-Path $Workspace 'removed-account.txt') -Value $SID
    if ($CleanupFails) { throw 'simulated cleanup error' }
}
$arguments = @{Installer='x';Version='v1';Iscc='x';Python='x';Workspace=$Workspace;Disposable=$true}
exit (Invoke-StandardUserValidation @arguments)
''', encoding="utf-8")
    workspace = tmp_path / "owned workspace"
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(fixture),
                             "-Source", str(script), "-Workspace", str(workspace),
                             "-ChildCode", str(child_code),
                             "-CleanupFails", str(int(cleanup_fails))],
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    expected = 1 if cleanup_fails or child_code == -1 else child_code
    assert result.returncode == expected, result.stderr
    assert "hidden-test-password" not in result.stdout + result.stderr
    assert "unrelated-private-detail" not in result.stdout + result.stderr
    assert ("| PASS fixture accepted" in result.stdout) == (child_code == 0)
    removed = workspace / "removed-account.txt"
    if cleanup_fails == 2:
        assert not removed.exists()
    else:
        assert removed.read_text(encoding="utf-8-sig").strip() == SID
    job_data = json.loads((workspace / "job.json").read_text(encoding="utf-8-sig"))
    assert set(job_data) == {"installer", "version", "iscc", "python", "workspace", "expected_sid"}


def test_powershell_launch_environment_and_timeout_use_owned_process_tree(tmp_path):
    import shutil
    executable = shutil.which("pwsh")
    if executable is None or os.name != "nt":
        pytest.skip("Windows PowerShell 凭证启动边界替身测试")
    source = Path(__file__).resolve().parents[1] / "scripts/run_windows_installer_standard_user.ps1"
    # 先确认可替换进程工厂存在，缺少注入边界时不运行任何带凭证的真实启动。
    assert "function New-ValidationProcess" in source.read_text(encoding="utf-8")
    fixture = tmp_path / "timeout.ps1"
    fixture.write_text(r'''
param($Source, $Directory)
$ErrorActionPreference = 'Stop'
. $Source
function New-ValidationProcess {
    $fake = [pscustomobject]@{
        StartInfo=$null; HasExited=$false; ExitCode=0; Killed=$false;
        StandardOutput=[pscustomobject]@{BaseStream=[IO.MemoryStream]::new()};
        StandardError=[pscustomobject]@{BaseStream=[IO.MemoryStream]::new()}
    }
    $fake | Add-Member ScriptMethod Start {
        if ($this.StartInfo.Environment.ContainsKey('SECRET_TOKEN')) { throw '环境泄漏' }
        if (-not $this.StartInfo.LoadUserProfile) { throw '未加载 profile' }
        if ($this.StartInfo.UseShellExecute) { throw '使用了 shell' }
        if (-not $this.StartInfo.ArgumentList.Contains('--job')) { throw '参数丢失' }
        return $true
    }
    $fake | Add-Member ScriptMethod WaitForExit { param($timeout) return $this.HasExited }
    $fake | Add-Member ScriptMethod Kill { param($tree)
        if (-not $tree) { throw '没有停止整个进程树' }
        $this.Killed=$true; $this.HasExited=$true
    }
    $fake | Add-Member ScriptMethod Dispose {}
    $script:FakeProcess=$fake
    return $fake
}
$env:SECRET_TOKEN='must-not-inherit'
$secret = ConvertTo-SecureString 'test-only-not-real' -AsPlainText -Force
$credential = [Management.Automation.PSCredential]::new('fake-account', $secret)
try {
    $job = @{python='fixture.exe';workspace=$Directory}
    Start-ValidationProcess -Job $job -Credential $credential
    throw '未传播超时'
} catch {
    if (-not $script:FakeProcess.Killed) { throw '未停止本次进程树' }
}
''', encoding="utf-8")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(fixture),
                             "-Source", str(source), "-Directory", str(tmp_path)],
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
