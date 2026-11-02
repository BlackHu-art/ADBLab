"""验证 macOS 制品检查器拒绝缺包、错误架构和无效签名。"""

import subprocess
from pathlib import Path

import pytest


def _app(tmp_path, machine):
    app = tmp_path / "ADBLab test.app"
    paths = {
        "app": app / "Contents/MacOS/ADBLab test",
        "helper": app / "Contents/Frameworks/runtime-helpers/adblab-adb-bridge/adblab-adb-bridge",
        "adb": app / f"Contents/Frameworks/runtime-tools/macos-{machine}/adb",
        "scrcpy": app / f"Contents/Frameworks/runtime-tools/macos-{machine}/scrcpy",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Mach-O fixture")
    return app, paths


def _macos_tools(monkeypatch, paths, machine, *, wrong_arch=None, unsigned=None, external=None):
    from scripts import check_macos_package as checker

    def run(command, **kwargs):
        target = Path(command[-1])
        label = next((name for name, path in paths.items() if target == path), "bundle")
        if command[0] == "/usr/bin/lipo":
            output = "x86_64 arm64" if label == "adb" else machine
            if label == wrong_arch:
                output = "x86_64" if machine == "arm64" else "arm64"
        elif command[0] == "/usr/bin/otool":
            library = (
                "/opt/homebrew/lib/libSDL3.dylib" if external == label
                else "/usr/lib/libc++.1.dylib"
            )
            output = f"{target}:\n\t{library} (compatibility version 1.0.0)\n"
        else:
            assert command[0] == "/usr/bin/codesign"
            if label == unsigned:
                return subprocess.CompletedProcess(command, 1, "", "invalid signature")
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(checker.subprocess, "run", run)


@pytest.mark.parametrize("machine", ["arm64", "x86_64"])
def test_package_accepts_native_app_with_universal_adb(tmp_path, monkeypatch, machine):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, machine)
    _macos_tools(monkeypatch, paths, machine)
    assert checker.check_package(app, machine) == paths["app"]


@pytest.mark.parametrize("wrong_arch", ["app", "helper", "adb", "scrcpy"])
def test_package_rejects_wrong_architecture(tmp_path, monkeypatch, wrong_arch):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, "arm64")
    _macos_tools(monkeypatch, paths, "arm64", wrong_arch=wrong_arch)
    with pytest.raises(checker.PackageError, match="架构"):
        checker.check_package(app, "arm64")


@pytest.mark.parametrize("unsigned", ["app", "helper", "adb", "scrcpy", "bundle"])
def test_package_rejects_invalid_signature(tmp_path, monkeypatch, unsigned):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, "arm64")
    _macos_tools(monkeypatch, paths, "arm64", unsigned=unsigned)
    with pytest.raises(checker.PackageError, match="codesign"):
        checker.check_package(app, "arm64")


def test_package_rejects_missing_bundled_tool(tmp_path, monkeypatch):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, "arm64")
    paths["adb"].unlink()
    _macos_tools(monkeypatch, paths, "arm64")
    with pytest.raises(checker.PackageError, match="缺失"):
        checker.check_package(app, "arm64")


@pytest.mark.parametrize("external", ["adb", "scrcpy"])
def test_package_rejects_homebrew_dynamic_dependency(tmp_path, monkeypatch, external):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, "arm64")
    _macos_tools(monkeypatch, paths, "arm64", external=external)
    with pytest.raises(checker.PackageError, match="系统库"):
        checker.check_package(app, "arm64")


def test_cli_reports_inspection_failure(tmp_path, monkeypatch, capsys):
    from scripts import check_macos_package as checker

    app, paths = _app(tmp_path, "arm64")
    _macos_tools(monkeypatch, paths, "arm64", unsigned="bundle")
    assert checker.main(["--app", str(app), "--machine", "arm64"]) == 1
    assert "codesign" in capsys.readouterr().err


@pytest.mark.parametrize("error", [OSError("tool missing"), subprocess.TimeoutExpired("lipo", 15)])
def test_package_reports_unavailable_inspection_tool(tmp_path, monkeypatch, error):
    from scripts import check_macos_package as checker

    app, _paths = _app(tmp_path, "arm64")

    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(checker.subprocess, "run", unavailable)
    with pytest.raises(checker.PackageError, match="lipo.*无法完成"):
        checker.check_package(app, "arm64")
