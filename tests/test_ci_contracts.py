import ast
import re
import shlex
from pathlib import Path

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


def test_build_workflow_does_not_run_pytest_during_packaging():
    """打包发布只执行静态检查和产物自检，pytest 由开发者按测试指南在本地执行。"""

    workflow = _read(BUILD_WORKFLOW)

    assert "python -m pytest" not in workflow
    assert "Run fast tests" not in workflow
    assert "Run tests" not in workflow


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
    commands = [shlex.split(line) for line in install_step["run"].splitlines() if line.strip()]
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
