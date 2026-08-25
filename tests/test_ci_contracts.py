import re
from pathlib import Path

WORKFLOW_DIR = Path(".github/workflows")
BUILD_WORKFLOW = WORKFLOW_DIR / "Build-exe.yaml"
RETENTION_WORKFLOW = WORKFLOW_DIR / "Auto-Clean.yaml"
PYINSTALLER_SPEC = Path("ADBLab.spec")

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


def test_all_actions_are_pinned_to_verified_commit_shas():
    workflows = "\n".join(_read(path) for path in (BUILD_WORKFLOW, RETENTION_WORKFLOW))
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
    """打包发布只执行静态检查和产物自检，pytest 留在独立的开发验证流程。"""

    workflow = _read(BUILD_WORKFLOW)

    assert "python -m pytest" not in workflow
    assert "Run fast tests" not in workflow
    assert "Run tests" not in workflow


def test_windows_build_collects_current_scrcpy_bundle():
    """本地 spec 与 CI 必须收集同一个无版本号的 Windows 工具目录。"""

    packaging_configs = (_read(PYINSTALLER_SPEC), _read(BUILD_WORKFLOW))

    for config in packaging_configs:
        assert "scrcpy-win64-v3.3.1" not in config
        assert "scrcpy-win64" in config


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
