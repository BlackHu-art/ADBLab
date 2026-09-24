import ast
import re
import shlex
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(".github/workflows")
BUILD_WORKFLOW = WORKFLOW_DIR / "Build-exe.yaml"
RETENTION_WORKFLOW = WORKFLOW_DIR / "Auto-Clean.yaml"
PYINSTALLER_SPEC = Path("ADBLab.spec")
ICON_DIR = Path("resources/icons")
FIRST_PARTY_PYTHON_PATHS = (
    Path("adblab"),
    Path("controllers"),
    Path("core"),
    Path("gui"),
    Path("models"),
    Path("services"),
    Path("utils"),
)
RUNTIME_RESOURCE_DATA = (
    ("resources/icons", "resources/icons"),
    ("resources/images/gallery_header.png", "resources/images"),
    ("resources/images/LICENSE.gallery.txt", "licenses/gallery"),
    ("resources/app_settings.json", "resources"),
    ("resources/connected_devices.yaml", "resources"),
    ("resources/chkbugreport-0.5-215.jar", "resources"),
    ("resources/app-icon-helper.jar", "resources"),
    ("resources/app-icon.png", "resources"),
    ("resources/ZFB.jpg", "resources"),
    ("THIRD_PARTY_NOTICES.md", "licenses"),
    ("mobileperf/LICENSE", "licenses/mobileperf"),
    ("mobileperf/extlib/xlsxwriter/LICENSE.txt", "licenses/xlsxwriter"),
)

PINNED_ACTIONS = {
    "actions/checkout": ("fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", "v5"),
    "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6"),
    "actions/cache": ("caa296126883cff596d87d8935842f9db880ef25", "v5"),
    "actions/upload-artifact": ("330a01c490aca151604b8cf639adc76d48f6c5d4", "v5"),
    "actions/download-artifact": ("634f93cb2916e3fdff6788551b99b062d0335ce0", "v5"),
}

USES_PATTERN = re.compile(
    r"^\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>[^\s#]+)\s*#\s*(?P<version>v\d+)\s*$",
    re.MULTILINE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _declared_svg_names() -> set[str]:
    """提取一方生产源码声明的 SVG 文件名，不依赖宿主文件系统的大小写规则。"""

    paths = [Path("main.py")]
    for root in FIRST_PARTY_PYTHON_PATHS:
        paths.extend(root.rglob("*.py"))

    names: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.endswith(".svg")
            ):
                names.add(Path(node.value).name)
    return names


def test_all_actions_are_pinned_to_verified_commit_shas():
    workflows = "\n".join(_read(path) for path in WORKFLOW_DIR.glob("*.yaml"))
    matches = list(USES_PATTERN.finditer(workflows))

    assert matches, "Expected at least one GitHub Action reference"
    for match in matches:
        action = match.group("action")
        assert action in PINNED_ACTIONS, f"Unreviewed action: {action}"
        expected_sha, expected_version = PINNED_ACTIONS[action]
        assert match.group("ref") == expected_sha
        assert re.fullmatch(r"[0-9a-f]{40}", match.group("ref"))
        assert match.group("version") == expected_version


def test_build_uses_read_only_default_permissions_and_scoped_release_write():
    workflow = _read(BUILD_WORKFLOW)

    assert "\npermissions:\n  contents: read\n" in workflow
    assert "  release:\n" in workflow
    assert "    permissions:\n      contents: write\n" in workflow
    assert "write-all" not in workflow
    assert "actions: write" not in workflow


def test_build_workflow_forces_utf8_for_all_python_processes():
    """Windows runner 的 Python 输出不能回退到系统代码页。"""

    workflow = yaml.safe_load(_read(BUILD_WORKFLOW))

    assert workflow["env"]["PYTHONUTF8"] == "1"
    assert workflow["env"]["PYTHONIOENCODING"] == "utf-8"


def test_build_workflow_does_not_run_pytest_during_packaging():
    """打包发布只执行静态检查和产物自检，pytest 由开发者按测试指南在本地执行。"""

    workflow = _read(BUILD_WORKFLOW)

    assert "python -m pytest" not in workflow
    assert "Run fast tests" not in workflow
    assert "Run tests" not in workflow


def test_manual_build_defaults_to_build_only_and_main_push_still_triggers():
    """手动重建同版本默认不发布，main 推送继续进入自动构建发布流程。"""
    workflow = yaml.safe_load(_read(BUILD_WORKFLOW))
    events = workflow.get("on", workflow.get(True))
    manual = events["workflow_dispatch"]
    assert isinstance(manual, dict), "Manual builds need an explicit publish input"
    publish = manual["inputs"]["publish"]
    assert publish["type"] == "boolean"
    assert publish["default"] is False
    assert events["push"]["branches"] == ["main"]


@pytest.mark.parametrize("event,ref,requested,expected", [
    ("workflow_dispatch", "refs/heads/main", "false", "false"),
    ("workflow_dispatch", "refs/heads/dev", "false", "false"),
    ("workflow_dispatch", "refs/heads/dev", "", "false"),
    ("workflow_dispatch", "refs/heads/main", "true", "true"),
    ("workflow_dispatch", "refs/heads/dev", "true", None),
    ("workflow_dispatch", "refs/tags/v3.2.18", "true", None),
    ("push", "refs/heads/main", "", "true"),
    ("push", "refs/heads/main", "false", "true"),
])
def test_version_job_computes_publish_mode_and_rejects_non_main(
    monkeypatch, tmp_path, event, ref, requested, expected,
):
    """实际执行模式选择代码，非 main 发布必须失败，不能静默降级为构建。"""
    job = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["version"]
    assert job["outputs"].get("publish") == "${{ steps.version.outputs.publish }}"
    step = next(step for step in job["steps"] if step.get("id") == "version")
    assert "if" not in step
    assert step["env"]["REQUESTED_PUBLISH"] == "${{ inputs.publish }}"
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("REQUESTED_PUBLISH", requested)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    if expected == "true":
        from utils.app_metadata import APP_RELEASE_TAG

        notes = tmp_path / ".github" / "release-notes" / f"{APP_RELEASE_TAG}.md"
        notes.parent.mkdir(parents=True)
        notes.write_text(
            f"# ADBLab {APP_RELEASE_TAG}\n\n有效发布说明。\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    if expected is None:
        with pytest.raises(SystemExit) as failure:
            exec(code, {})
        assert failure.value.code not in (None, 0)
        assert "main" in str(failure.value)
        assert not output.exists() or "publish=true" not in _read(output)
    else:
        exec(code, {})
        outputs = dict(line.split("=", 1) for line in _read(output).splitlines())
        assert outputs["publish"] == expected
        assert outputs["version"].startswith("v")


@pytest.mark.parametrize(
    ("event", "ref", "requested", "note_kind", "allowed"),
    [
        ("workflow_dispatch", "refs/heads/main", "false", "missing", True),
        ("push", "refs/heads/main", "", "missing", False),
        ("push", "refs/heads/main", "", "invalid-utf8", False),
        ("push", "refs/heads/main", "", "blank", False),
        ("push", "refs/heads/main", "", "wrong-title", False),
        ("push", "refs/heads/main", "", "title-only", False),
        ("push", "refs/heads/main", "", "valid", True),
    ],
    ids=[
        "build-only-without-notes", "publish-missing", "publish-invalid-utf8",
        "publish-blank", "publish-wrong-title", "publish-title-only", "publish-chinese",
    ],
)
def test_version_job_requires_nonempty_release_notes_only_for_publishing(
    monkeypatch, tmp_path, event, ref, requested, note_kind, allowed,
):
    """发布前校验版本标题和正文；普通构建不读取或要求该文件。"""

    from utils.app_metadata import APP_RELEASE_TAG

    job = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["version"]
    step = next(step for step in job["steps"] if step.get("id") == "version")
    output = tmp_path / "github_output"
    note_text = {
        "blank": "   \n",
        "wrong-title": "# ADBLab v0.0.0\n\n旧版本说明。\n",
        "title-only": f"# ADBLab {APP_RELEASE_TAG}\n",
        "valid": f"# ADBLab {APP_RELEASE_TAG}\n\n修复发布说明。\n",
    }.get(note_kind)
    note_path = tmp_path / ".github" / "release-notes" / f"{APP_RELEASE_TAG}.md"
    if note_text is not None:
        note_path.parent.mkdir(parents=True)
        note_path.write_text(note_text, encoding="utf-8")
    elif note_kind == "invalid-utf8":
        note_path.parent.mkdir(parents=True)
        note_path.write_bytes(b"\xff\xfe")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("REQUESTED_PUBLISH", requested)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]

    if allowed:
        exec(code, {})
        outputs = dict(line.split("=", 1) for line in _read(output).splitlines())
        assert outputs["publish"] == ("true" if event == "push" else "false")
    else:
        with pytest.raises(SystemExit) as failure:
            exec(code, {})
        assert "release notes" in str(failure.value).lower()


def test_duplicate_version_guard_applies_only_to_publishing():
    """已发布版本仍可重新构建，发布模式则在构建前拒绝重复 tag。"""
    workflow = yaml.safe_load(_read(BUILD_WORKFLOW))
    steps = workflow["jobs"]["version"]["steps"]
    version_index = next(index for index, step in enumerate(steps)
                         if step.get("id") == "version")
    guards = [(index, step) for index, step in enumerate(steps)
              if "git ls-remote" in step.get("run", "")]
    assert len(guards) == 1
    index, guard = guards[0]
    assert version_index < index
    assert guard.get("if") == "steps.version.outputs.publish == 'true'"
    assert workflow["jobs"]["build"]["needs"] == "version"


def test_release_requires_publish_mode_and_successful_builds():
    """下载、创建发布和保留期清理仅在明确发布且四平台构建成功后执行。"""
    release = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["release"]
    assert set(release["needs"]) == {"version", "build"}
    assert release["if"] == (
        "needs.version.outputs.publish == 'true' && needs.build.result == 'success'"
    )
    download = next(step for step in release["steps"]
                    if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download.get("continue-on-error", False) is False
    assert download["with"]["path"] == "release_artifacts"


def test_build_uploads_only_the_exact_archive_for_each_platform():
    """上传路径不能包含同目录中残留的主程序、app、内部工具或额外档案。"""
    job = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]
    upload = next(step for step in job["steps"]
                  if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == "${{ matrix.artifact }}"
    assert upload["with"]["if-no-files-found"] == "error"
    template = upload["with"]["path"]
    assert "*" not in template and "?" not in template
    expected = {
        "ADBLab-win-x64": "dist/ADBLab-win-x64-v9.8.7.zip",
        "ADBLab-macos-x64": "dist/ADBLab-macos-x64-v9.8.7.zip",
        "ADBLab-macos-arm64": "dist/ADBLab-macos-arm64-v9.8.7.zip",
        "ADBLab-linux-x64": "dist/ADBLab-linux-x64-v9.8.7.tar.gz",
    }
    for row in job["strategy"]["matrix"]["include"]:
        resolved = template.replace("${{ needs.version.outputs.version }}", "v9.8.7")
        for key, value in row.items():
            resolved = resolved.replace("${{ matrix." + key + " }}", value)
        assert resolved == expected[row["artifact"]]


@pytest.mark.parametrize("platform,executable,archive", [
    ("Windows", "dist/$name/$name.exe", "Compress-Archive"),
    ("macOS", "$executable", "ditto -c"),
    ("Linux", "dist/$name", "tar -C dist"),
])
def test_frozen_checks_use_waiting_validator_before_compression(platform, executable, archive):
    """三平台统一等待产物检查进程，超时或非零退出必须阻止压缩与上传。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    checks = [(index, step) for index, step in enumerate(steps)
              if "scripts/check_build_artifacts.py frozen" in step.get("run", "")
              and step.get("if") == f"runner.os == '{platform}'"]
    assert len(checks) == 1, f"{platform} must use the bounded frozen artifact validator"
    index, step = checks[0]
    build_index = next(index for index, step in enumerate(steps)
                       if "scripts/build_app.py" in step.get("run", ""))
    archive_index = next(index for index, step in enumerate(steps)
                         if archive in step.get("run", ""))
    assert build_index < index < archive_index
    assert step["shell"] == "bash"
    assert "set -euo pipefail" in step["run"]
    command = next(shlex.split(line) for line in step["run"].splitlines()
                   if "scripts/check_build_artifacts.py frozen" in line)
    assert command == [
        "python", "scripts/check_build_artifacts.py", "frozen", "--executable", executable,
        "--timeout", "60",
    ]
    assert "--self-check packaging" not in step["run"]


def test_release_validates_all_four_archives_before_creating_release():
    """下载成功也须验证四包文件名、版本和归档内容，失败时不得创建 Release。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["release"]["steps"]
    create = next(step for step in steps if "gh release create" in step.get("run", ""))
    command = create["run"]
    check = 'python3 scripts/check_build_artifacts.py release --directory release_artifacts '
    check += '--version "$TAG"'
    assert "set -euo pipefail" in command
    assert check in command
    assert command.index(check) < command.index("gh release create")


def test_release_uses_the_validated_versioned_notes_file():
    """创建 Release 必须附带 version job 校验过的同版本说明文件。"""

    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["release"]["steps"]
    create = next(step for step in steps if "gh release create" in step.get("run", ""))
    command = create["run"]

    assert 'NOTES_FILE=".github/release-notes/$TAG.md"' in command
    assert 'if [ ! -s "$NOTES_FILE" ]; then' in command
    assert '--notes-file "$NOTES_FILE"' in command
    assert command.index('if [ ! -s "$NOTES_FILE" ]; then') < command.index("gh release create")


def test_linux_build_installs_egl_before_qt_self_check():
    """Linux 构建必须先补齐 Qt 导入所需的 EGL，且安装步骤只作用于 Linux。"""

    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    egl_steps = [
        (index, step) for index, step in enumerate(steps)
        if "libegl1" in step.get("run", "")
    ]
    assert len(egl_steps) == 1, "Linux build is missing its EGL system dependency"
    install_index, install_step = egl_steps[0]
    assert install_step.get("if") == "runner.os == 'Linux'"
    assert install_step.get("shell") == "bash"
    commands = [
        shlex.split(line)
        for line in install_step["run"].replace("\\\n", " ").splitlines()
        if line.strip()
    ]
    assert ["sudo", "apt-get", "update"] in commands
    assert any(
        command[:3] == ["sudo", "apt-get", "install"]
        and "-y" in command and "libegl1" in command
        for command in commands
    )
    qt_import_index = next(
        index for index, step in enumerate(steps)
        if "python main.py --self-check packaging" in step.get("run", "")
    )
    assert install_index < qt_import_index


def test_build_matrix_uses_native_python_and_preserves_platform_package_modes():
    """产物名称与宿主、Python 架构必须一致，Windows/Linux 继续沿用既有打包模式。"""
    job = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]
    rows = job["strategy"]["matrix"]["include"]
    expected = {
        "ADBLab-win-x64": ("windows-latest", "x64", "AMD64", "--onedir", "--windowed"),
        "ADBLab-macos-x64": ("macos-15-intel", "x64", "x86_64", "--onefile", "--windowed"),
        "ADBLab-macos-arm64": ("macos-15", "arm64", "arm64", "--onefile", "--windowed"),
        "ADBLab-linux-x64": ("ubuntu-latest", "x64", "x86_64", "--onefile", ""),
    }
    assert {row["artifact"] for row in rows} == set(expected)
    for row in rows:
        assert tuple(row.get(key) for key in (
            "os", "python_architecture", "machine", "package_mode", "windowed",
        )) == expected[row["artifact"]]
    setup = next(step for step in job["steps"]
                 if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["with"]["architecture"] == "${{ matrix.python_architecture }}"


@pytest.mark.parametrize("actual,expected", [
    ("x86_64", "x86_64"), ("arm64", "arm64"), ("AMD64", "AMD64"),
    ("arm64", "x86_64"), ("x86_64", "arm64"),
])
def test_build_checks_python_machine_before_installing_or_building(monkeypatch, actual, expected):
    """runner 或 Python 架构漂移必须在使用缓存和开始构建之前失败。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    checks = [(index, step) for index, step in enumerate(steps)
              if "platform.machine()" in step.get("run", "")]
    assert len(checks) == 1, "Build must verify the selected Python architecture"
    index, step = checks[0]
    assert "if" not in step
    assert step["env"]["EXPECTED_MACHINE"] == "${{ matrix.machine }}"
    setup_index = next(index for index, step in enumerate(steps)
                       if step.get("uses", "").startswith("actions/setup-python@"))
    cache_index = next(index for index, step in enumerate(steps)
                       if step.get("uses", "").startswith("actions/cache@"))
    assert setup_index < index < cache_index
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    monkeypatch.setattr("platform.machine", lambda: actual)
    monkeypatch.setenv("EXPECTED_MACHINE", expected)
    if actual == expected:
        exec(code, {})
    else:
        with pytest.raises(SystemExit) as failure:
            exec(code, {})
        assert failure.value.code != 0


def test_pip_cache_restore_is_isolated_by_runner_architecture():
    """Apple Silicon 不得命中 Intel 缓存，包括宽松恢复前缀。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    cache = next(step for step in steps if step.get("uses", "").startswith("actions/cache@"))
    assert "${{ runner.arch }}" in cache["with"]["key"]
    prefixes = cache["with"]["restore-keys"].splitlines()
    assert prefixes
    assert all("${{ runner.arch }}" in prefix for prefix in prefixes)


def test_macos_checks_helper_and_app_architecture_before_archiving():
    """helper 与最终主程序都须核对实际 Mach-O 架构，再运行冻结产物自检。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    commands = [step.get("run", "") for step in steps]
    helper_build = next(index for index, command in enumerate(commands)
                        if command == "python scripts/build_scrcpy_adb_bridge.py")
    app_build = next(index for index, command in enumerate(commands)
                     if "python scripts/build_app.py" in command)
    archive = next(index for index, command in enumerate(commands) if "ditto -c" in command)
    checks = [(index, step) for index, step in enumerate(steps)
              if "lipo -archs" in step.get("run", "")]
    assert len(checks) == 2, "macOS helper and main executable both need architecture checks"
    (helper_index, helper), (app_index, app) = checks
    assert helper_build < helper_index < app_build < app_index < archive
    for _index, step in checks:
        assert step["if"] == "runner.os == 'macOS'"
        assert step["shell"] == "bash"
        assert "set -euo pipefail" in step["run"]
        assert 'file "$executable"' in step["run"]
        assert 'test "$(lipo -archs "$executable")" = "${{ matrix.machine }}"' in step["run"]
    assert "build/runtime-helpers/adblab-adb-bridge/adblab-adb-bridge" in helper["run"]
    assert 'name="${{ matrix.artifact }}-${{ needs.version.outputs.version }}"' in app["run"]
    assert 'dist/$name.app/Contents/MacOS/$name' in app["run"]
    assert ('python scripts/check_build_artifacts.py frozen --executable "$executable" '
            '--timeout 60') in app["run"]


@pytest.mark.parametrize("frozen", [False, True], ids=["source", "frozen"])
def test_linux_runs_bounded_xcb_gui_probe_before_archiving(frozen):
    """源码与产物各自启动真实 xcb 探针，系统依赖就绪且卡住时限时失败。"""
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    install_index, install = next((index, step) for index, step in enumerate(steps)
                                 if "apt-get install" in step.get("run", ""))
    assert install["if"] == "runner.os == 'Linux'"
    for package in (
        "libegl1", "libudev1", "libsm6", "libice6", "libx11-xcb1", "libxcb-cursor0",
        "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0", "libxcb-render0",
        "libxcb-render-util0", "libxcb-shape0", "libxcb-shm0", "libxcb-sync1",
        "libxcb-util1", "libxcb-xfixes0", "libxcb-xkb1", "libxkbcommon0",
        "libxkbcommon-x11-0", "xvfb", "xauth",
    ):
        assert package in shlex.split(install["run"].replace("\\\n", " "))
    dependency_index, dependencies = next(
        (index, step) for index, step in enumerate(steps)
        if step["name"] == "Verify Linux Qt plugin dependencies"
    )
    assert dependencies["if"] == "runner.os == 'Linux'"
    assert "QLibraryInfo" in dependencies["run"]
    assert 'ldd "$plugin"' in dependencies["run"]
    assert "not found" in dependencies["run"]
    assert "exit 1" in dependencies["run"]
    probes = [(index, step) for index, step in enumerate(steps)
              if "--self-check gui" in step.get("run", "")]
    assert len(probes) == 2, "Source and frozen Linux builds need separate GUI probes"
    index, probe = probes[int(frozen)]
    assert probe["if"] == "runner.os == 'Linux'"
    assert probe["env"]["QT_QPA_PLATFORM"] == "xcb"
    assert probe["env"]["QT_DEBUG_PLUGINS"] == "1"
    command = next(shlex.split(line) for line in probe["run"].splitlines()
                   if "--self-check gui" in line)
    executable = ["dist/$name"] if frozen else ["python", "main.py"]
    assert command == ["timeout", "15s", "xvfb-run", "-a", *executable, "--self-check", "gui"]
    build_index = next(index for index, step in enumerate(steps)
                       if "python scripts/build_app.py" in step.get("run", ""))
    archive_index = next(index for index, step in enumerate(steps)
                         if "tar -C dist" in step.get("run", ""))
    assert install_index < dependency_index < index < archive_index
    assert (index > build_index) is frozen
    assert "--self-check packaging" not in probe["run"]


def test_windows_build_collects_current_scrcpy_bundle(monkeypatch):
    """本地 spec 与 CI 必须收集同一个无版本号的 Windows 工具目录。"""
    from scripts.packaging_manifest import resource_datas

    monkeypatch.setattr("utils.tool_manifest.host_platform.machine", lambda: "x86_64")
    assert (
        "runtime-tools/windows-x86_64", "runtime-tools/windows-x86_64",
    ) in resource_datas("win32")
    for platform in ("win32", "darwin", "linux"):
        assert all("scrcpy-win64-v" not in source for source, _ in resource_datas(platform))


def test_packaging_uses_explicit_resource_allowlist_and_keeps_licenses(monkeypatch):
    """本地 spec 与 CI 不得重新整目录打包文档、截图或 MobilePerf 源码。"""
    from scripts.packaging_manifest import SUBMODULE_PACKAGES, resource_datas

    monkeypatch.setattr("utils.tool_manifest.host_platform.machine", lambda: "x86_64")
    common = {
        *RUNTIME_RESOURCE_DATA, ("icon.ico", "."), ("build/runtime-helpers", "runtime-helpers"),
    }
    for platform in ("win32", "darwin", "linux"):
        tools = {
            "win32": {("runtime-tools/windows-x86_64", "runtime-tools/windows-x86_64")},
            "linux": {("runtime-tools/linux-x86_64", "runtime-tools/linux-x86_64")},
            "darwin": set(),
        }
        expected = common | tools[platform]
        assert set(resource_datas(platform)) == expected
        assert len(resource_datas(platform)) == len(expected)
    for source, _destination in RUNTIME_RESOURCE_DATA:
        assert Path(source).exists(), f"Missing packaging source: {source}"
    assert SUBMODULE_PACKAGES == ("mobileperf", "qfluentwidgets")


def test_declared_svg_icons_exist_with_exact_case():
    """即使在 Windows 上，也按目录记录的精确大小写校验所有图标声明。"""

    available = {path.name for path in ICON_DIR.iterdir() if path.is_file()}
    declared = _declared_svg_names()

    assert declared
    assert sorted(declared - available) == []


def test_same_version_remains_immutable_and_old_tags_are_pruned_to_five():
    workflow = _read(BUILD_WORKFLOW)

    # 同版本发布仍不可变：存在 Release/tag 即失败。
    assert 'gh release view "$TAG"' in workflow
    assert 'git ls-remote --exit-code --tags origin "refs/tags/$TAG"' in workflow
    assert workflow.count("published versions are immutable.") == 2
    assert 'gh release create "$TAG"' in workflow
    assert "gh run delete" not in workflow
    assert "--cleanup-tag" not in workflow
    # 版本 tag 保留策略：发布完成后自动删除最旧的 tag，仅保留最新 5 个。
    assert "name: Retain latest 5 version tags" in workflow
    assert "KEEP=5" in workflow
    assert 'gh release delete "$TAG"' in workflow
    assert 'git push origin --delete "refs/tags/$TAG"' in workflow


def test_build_prunes_tags_but_not_workflow_runs_or_artifacts():
    workflow = _read(BUILD_WORKFLOW)

    # 工作流运行与制品仍无自动清理（Auto-Clean 保持手动只读审计）。
    assert "Prune old workflow runs" not in workflow
    assert "Prune old releases" not in workflow
    assert "Deleting run" not in workflow
    assert "Deleting release" not in workflow
    # tag 保留只删除超出最新 5 个的旧版本 tag 及其 Release。
    assert "Retain latest 5 version tags" in workflow
    assert "${#TAGS[@]} - KEEP" in workflow


def test_retention_workflow_is_manual_and_read_only():
    workflow = _read(RETENTION_WORKFLOW)

    assert workflow.startswith("name: Retention Audit\n")
    assert "\n  workflow_dispatch:\n" in workflow
    assert "\n  schedule:" not in workflow
    assert "\n  workflow_call:" not in workflow
    assert "\npermissions:\n  actions: read\n  contents: read\n" in workflow
    assert "write-all" not in workflow
    assert ": write" not in workflow


def test_retention_workflow_only_reports_candidates():
    workflow = _read(RETENTION_WORKFLOW)

    assert "gh run list" in workflow
    assert "gh release list" in workflow
    assert "audit only" in workflow
    for forbidden in (
        "gh run delete",
        "gh release delete",
        "delete-workflow-runs",
        "delete-older-releases",
        "delete_tags:",
        "--cleanup-tag",
    ):
        assert forbidden not in workflow


def test_build_workflow_delegates_resources_to_shared_cli_and_keys_constraints():
    workflow = yaml.safe_load(_read(BUILD_WORKFLOW))
    job = workflow["jobs"]["build"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python scripts/build_app.py" in commands
    assert "--add-data" not in commands
    assert "--collect-submodules" not in commands
    assert all("datas" not in row for row in job["strategy"]["matrix"]["include"])
    cache = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/cache@"))
    assert "constraints.txt" in cache["with"]["key"]


def test_source_integrity_guard_runs_before_build_and_other_local_hooks():
    steps = yaml.safe_load(_read(BUILD_WORKFLOW))["jobs"]["build"]["steps"]
    commands = [step.get("run", "") for step in steps]
    guard = commands.index("python scripts/check_source_text.py")
    assert guard < next(index for index, command in enumerate(commands) if "PyInstaller" in command
                        or "scripts/build_app.py" in command)
    config = yaml.safe_load(_read(Path(".pre-commit-config.yaml")))
    hooks = config["repos"][0]["hooks"]
    assert hooks[0]["id"] == "source-text"
    assert hooks[0]["entry"].endswith("scripts/check_source_text.py")
    assert hooks[0]["pass_filenames"] is False
    assert [hook["id"] for hook in hooks[1:]] == ["ruff-check", "comment-language", "doc-links"]
