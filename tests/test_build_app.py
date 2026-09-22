"""运行构建描述以验证共享清单、平台边界与无构建预览。"""

import ast
import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def x64_host(monkeypatch):
    monkeypatch.setattr("utils.tool_manifest.host_platform.machine", lambda: "x86_64")


def _spec_analysis(monkeypatch, platform):
    from PyInstaller.utils import hooks

    analysis_options = {}

    def analysis(*args, **kwargs):
        analysis_options.update(kwargs)
        return SimpleNamespace(
            pure=(), zipped_data=(), scripts=(), binaries=(), zipfiles=(), datas=(),
        )

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(hooks, "collect_submodules", lambda package: [f"{package}.included"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    runpy.run_path(str(ROOT / "ADBLab.spec"), init_globals={
        "SPECPATH": str(ROOT), "Analysis": analysis,
        "PYZ": lambda *a, **k: None, "EXE": lambda *a, **k: None,
        "COLLECT": lambda *a, **k: None,
    })
    return analysis_options


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_spec_and_cli_consume_the_same_resources_and_hidden_imports(monkeypatch, platform):
    from scripts import build_app, packaging_manifest

    command = build_app.build_command(name="example", platform=platform)
    options = _spec_analysis(monkeypatch, platform)
    separator = ";" if platform == "win32" else ":"
    cli_data = [command[index + 1] for index, item in enumerate(command) if item == "--add-data"]
    cli_packages = [
        command[index + 1] for index, item in enumerate(command) if item == "--collect-submodules"
    ]
    expected_data = packaging_manifest.resource_datas(platform)
    assert options["datas"] == expected_data
    assert cli_data == [f"{ROOT / source}{separator}{target}" for source, target in expected_data]
    assert cli_packages == ["mobileperf", "qfluentwidgets"]
    assert options["hiddenimports"] == ["mobileperf.included", "qfluentwidgets.included"]
    assert (("runtime-tools/windows-x86_64", "runtime-tools/windows-x86_64")
            in expected_data) is (platform == "win32")
    assert ("build/runtime-helpers", "runtime-helpers") in expected_data


def test_manifest_change_reaches_both_real_consumers(monkeypatch):
    from scripts import build_app, packaging_manifest

    monkeypatch.setattr(
        packaging_manifest, "COMMON_DATA",
        (*packaging_manifest.COMMON_DATA, ("extra/file.bin", "extra")),
    )
    monkeypatch.setattr(
        packaging_manifest, "SUBMODULE_PACKAGES",
        (*packaging_manifest.SUBMODULE_PACKAGES, "extra_package"),
    )
    command = build_app.build_command(name="example", platform="win32")
    options = _spec_analysis(monkeypatch, "win32")
    assert f"{ROOT / 'extra/file.bin'};extra" in command
    assert ("extra/file.bin", "extra") in options["datas"]
    assert "extra_package" in command
    assert "extra_package.included" in options["hiddenimports"]


def test_spec_finds_manifest_outside_repository_working_directory(tmp_path):
    code = r'''
import json, runpy, sys, types, subprocess
hooks = types.ModuleType("PyInstaller.utils.hooks")
hooks.collect_submodules = lambda package: [package + ".included"]
sys.modules["PyInstaller.utils.hooks"] = hooks
subprocess.run = lambda *args, **kwargs: None
captured = {}
def analysis(*args, **kwargs):
    captured.update(kwargs)
    return types.SimpleNamespace(
        pure=(), zipped_data=(), scripts=(), binaries=(), zipfiles=(), datas=(),
    )
runpy.run_path(sys.argv[1], init_globals={
    "SPECPATH": sys.argv[2], "Analysis": analysis,
    "PYZ": lambda *a, **k: None, "EXE": lambda *a, **k: None, "COLLECT": lambda *a, **k: None,
})
print(json.dumps(captured["hiddenimports"]))
'''
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT / "ADBLab.spec"), str(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["mobileperf.included", "qfluentwidgets.included"]


@pytest.mark.parametrize("failed_stage,code", [(None, 0), ("tools", 5), ("helper", 7), ("app", 9)])
def test_build_cli_stops_on_helper_failure_and_preserves_build_exit_code(
    monkeypatch, failed_stage, code,
):
    from scripts import build_app

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        stage = ("tools", "helper", "app")[len(calls) - 1]
        return SimpleNamespace(returncode=code if stage == failed_stage else 0)

    monkeypatch.setattr(build_app.subprocess, "run", run)
    result = build_app.main(["--name", "example", "--onefile", "--windowed", "--icon", "icon.ico"])
    assert result == code
    assert len(calls) == {"tools": 1, "helper": 2, "app": 3, None: 3}[failed_stage]
    assert Path(calls[0][0][-1]).name == "prepare_runtime_tools.py"
    if len(calls) > 1:
        assert Path(calls[1][0][-1]).name == "build_scrcpy_adb_bridge.py"
    if len(calls) > 2:
        command = calls[2][0]
        assert command[:3] == [sys.executable, "-m", "PyInstaller"]
        assert "--onefile" in command and "--windowed" in command
        assert command[-1] == str(ROOT / "main.py")
        assert calls[2][1]["cwd"] == ROOT


def test_build_dry_run_does_not_import_qt_or_invoke_packager(tmp_path):
    code = r'''
import importlib.abc, runpy, subprocess, sys
class BlockBuildImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PySide6", "PyInstaller"}:
            raise AssertionError("dry-run imported " + fullname)
sys.meta_path.insert(0, BlockBuildImports())
def no_subprocess(*args, **kwargs):
    raise AssertionError("dry-run attempted to build")
subprocess.run = no_subprocess
sys.argv = [sys.argv[1], "--dry-run", "--name", "dry run"]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT / "scripts/build_app.py")],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    commands = json.loads(result.stdout)
    assert len(commands) == 3
    assert commands[2][:3] == [sys.executable, "-m", "PyInstaller"]
    assert commands[2][commands[2].index("--name") + 1] == "dry run"
    assert not (tmp_path / "build").exists()


def test_cli_makespec_does_not_overwrite_controlled_spec_and_keeps_sources_resolvable(
    monkeypatch, tmp_path,
):
    from PyInstaller.__main__ import generate_parser
    from PyInstaller.building import makespec

    from scripts import build_app

    monkeypatch.setattr(build_app, "ROOT", tmp_path)
    # PyInstaller 在导入时缓存 cwd，必须显式隔离其默认目录，避免失败回归污染源码。
    monkeypatch.setattr(makespec, "DEFAULT_SPECPATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    original_spec = (ROOT / "ADBLab.spec").read_bytes()
    controlled = tmp_path / "ADBLab.spec"
    controlled.write_text("# controlled spec\n", encoding="utf-8")
    command = build_app.build_command(name="ADBLab", icon="icon.ico")
    arguments = vars(generate_parser().parse_args(command[3:]))
    filenames = arguments.pop("filenames")
    generated = Path(makespec.main(filenames, **arguments))

    assert controlled.read_text(encoding="utf-8") == "# controlled spec\n"
    assert (ROOT / "ADBLab.spec").read_bytes() == original_spec
    assert generated == tmp_path / "build/app-spec/ADBLab.spec"
    tree = ast.parse(generated.read_text(encoding="utf-8"))
    analysis = next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Analysis"
    )
    datas = ast.literal_eval(next(
        option.value for option in analysis.keywords if option.arg == "datas"
    ))
    assert datas
    assert all(Path(source).is_absolute() for source, _destination in datas)
    entry = Path(ast.literal_eval(analysis.args[0])[0])
    assert entry.resolve() == tmp_path / "main.py"
    assert Path(command[command.index("--icon") + 1]) == tmp_path / "icon.ico"
