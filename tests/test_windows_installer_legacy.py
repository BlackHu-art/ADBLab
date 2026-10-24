"""官方旧 ZIP 只能在固定摘要校验后用于一次性安装实验，不能冒充历史 setup。"""

import hashlib
import io
import json
import shutil
import stat
import urllib.error
import zipfile
from pathlib import Path

import pytest


def _module():
    from tests.fixtures.windows_installer import legacy_upgrade
    return legacy_upgrade


def _archive(path, extra=()):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ADBLab-win-x64-v3.3.2.exe", b"old application")
        archive.writestr("_internal/adb.exe", b"old adb")
        archive.writestr("_internal/retired.dll", b"retired old dependency")
        for name, value in extra:
            if isinstance(name, str):
                member = zipfile.ZipInfo(name)
                # ZipInfo 在 Windows 上会自动规范化反斜杠；保留原始恶意成员名供校验。
                member.filename = member.orig_filename = name
            else:
                member = name
            archive.writestr(member, value)


def test_legacy_origin_is_exact_official_release_not_latest():
    module = _module()
    assert module.LEGACY_VERSION == "3.3.2"
    assert module.LEGACY_TAG_SHA == "e0c0d0487ee350c2ba8e3389a84ec998b616de33"
    assert module.LEGACY_ASSET_ID == 653828320
    assert module.LEGACY_SIZE == 157937553
    assert module.LEGACY_SHA256 == (
        "10f7322a6d9189b36dba50097d9d9f4e6c51fbbc7426af989d7c55a56765e8bc"
    )
    assert module.LEGACY_URL == (
        "https://github.com/BlackHu-art/ADBLab/releases/download/v3.3.2/"
        "ADBLab-win-x64-v3.3.2.zip"
    )


def test_legacy_wrapper_version_and_output_match_pinned_payload():
    module = _module()
    template = Path(module.__file__).with_name("legacy_fixture.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{module.LEGACY_VERSION}"' in template
    assert f"AppVersion={module.LEGACY_VERSION}\n" in template
    assert f"AppVerName=ADBLab {module.LEGACY_VERSION} legacy ZIP test wrapper\n" in template
    assert f"OutputBaseFilename={Path(module.LEGACY_INSTALLER).stem}\n" in template
    assert "#ifdef AppVersion" in template
    assert "#error The legacy fixture version cannot be overridden" in template


def test_missing_pinned_release_stops_without_fallback_or_output(tmp_path, monkeypatch):
    module = _module()
    requested = []

    def missing(url, *, timeout):
        requested.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", missing)
    target = tmp_path / "old.zip"
    with pytest.raises(urllib.error.HTTPError) as error:
        module._download_archive(target)
    assert error.value.code == 404
    assert requested == [module.LEGACY_URL]
    assert not target.exists()


@pytest.mark.parametrize("body,size,digest", [
    (b"correct", 7, hashlib.sha256(b"correct").hexdigest()),
    (b"truncated", 20, hashlib.sha256(b"truncated").hexdigest()),
    (b"oversized", 3, hashlib.sha256(b"oversized").hexdigest()),
    (b"tampered", 8, hashlib.sha256(b"expected").hexdigest()),
])
def test_download_rejects_size_or_digest_before_any_extraction(
    tmp_path, monkeypatch, body, size, digest,
):
    module = _module()
    requested = []

    def download(url, *, timeout):
        requested.append(url)
        assert timeout == 60
        return io.BytesIO(body)

    monkeypatch.setattr(module.urllib.request, "urlopen", download)
    monkeypatch.setattr(module, "LEGACY_SIZE", size)
    monkeypatch.setattr(module, "LEGACY_SHA256", digest)
    target = tmp_path / "old.zip"
    if body == b"correct":
        module._download_archive(target)
        assert target.read_bytes() == body
    else:
        with pytest.raises(ValueError, match="大小|摘要"):
            module._download_archive(target)
    assert requested == [module.LEGACY_URL]


@pytest.mark.parametrize("names", [
    ["../escape"], ["_internal/ads:stream"], ["_internal/back\\slash"],
    ["_internal/trailing."], ["_internal/CON.txt"],
    ["_internal/ADB.exe"], ["_internal/retired.dll/child"],
    ["Extra/value", "extra/other"], ["duplicate", "duplicate"],
])
def test_unsafe_zip_names_rejected_before_extraction(tmp_path, monkeypatch, names):
    module = _module()
    archive = tmp_path / "old.zip"
    with pytest.warns(UserWarning) if names == ["duplicate", "duplicate"] else _no_warning():
        _archive(archive, [(name, b"payload") for name in names])
    monkeypatch.setattr(module, "safe_extract_zip", lambda *a: pytest.fail("unsafe extraction"))
    with pytest.raises(ValueError):
        module._extract_archive(archive, tmp_path / "source")
    assert not (tmp_path / "source").exists()


def _no_warning():
    from contextlib import nullcontext
    return nullcontext()


@pytest.mark.parametrize("attributes", [((stat.S_IFLNK | 0o777) << 16), 0x400])
def test_zip_link_or_reparse_metadata_rejected(tmp_path, monkeypatch, attributes):
    module = _module()
    archive = tmp_path / "old.zip"
    member = zipfile.ZipInfo("_internal/link")
    member.external_attr = attributes
    _archive(archive, [(member, b"target")])
    monkeypatch.setattr(module, "safe_extract_zip", lambda *a: pytest.fail("link extracted"))
    with pytest.raises(ValueError, match="链接|重解析"):
        module._extract_archive(archive, tmp_path / "source")


def test_safe_extraction_uses_shared_guard_and_validates_payload(tmp_path, monkeypatch):
    module = _module()
    archive = tmp_path / "old.zip"
    _archive(archive)
    calls = []
    extract = module.safe_extract_zip

    def guarded(zipped, destination):
        calls.append(destination)
        extract(zipped, destination)

    monkeypatch.setattr(module, "safe_extract_zip", guarded)
    source = tmp_path / "source"
    module._extract_archive(archive, source)
    assert calls == [source]
    assert (source / module.LEGACY_ENTRY).read_bytes() == b"old application"


def test_prepare_refuses_existing_workspace_without_modifying_it(tmp_path, monkeypatch):
    module = _module()
    sentinel = tmp_path / "existing.txt"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(module, "verify_compiler", lambda *a: pytest.fail("reused workspace"))
    with pytest.raises(ValueError, match="全新"):
        module.prepare_legacy_installer(tmp_path / "iscc.exe", tmp_path)
    assert sentinel.read_bytes() == b"keep"


def test_prepare_stages_same_bytes_and_only_compiles_test_template(tmp_path, monkeypatch):
    module = _module()
    from core import windows_installation as protocol
    from scripts.windows_installer.manifest import validate_manifest

    source_zip = tmp_path / "official.zip"
    _archive(source_zip)
    original = source_zip.read_bytes()
    monkeypatch.setattr(module, "verify_compiler", lambda _: None)
    monkeypatch.setattr(module, "check_installer_file", lambda _: None)
    monkeypatch.setattr(
        module, "_download_archive", lambda target: shutil.copyfile(source_zip, target),
    )
    commands = []
    workspace = tmp_path / "compile"

    def run(command, log, **kwargs):
        commands.append(command)
        assert Path(command[-1]).name == "legacy_fixture.iss"
        assert not any(value.startswith("/DAppVersion") for value in command)
        assert kwargs["timeout"] == 900
        (workspace / module.LEGACY_INSTALLER).write_bytes(b"compiled fixture")

    monkeypatch.setattr(module.product, "run_checked", run)
    result = module.prepare_legacy_installer(tmp_path / "iscc.exe", workspace)
    assert result == workspace / module.LEGACY_INSTALLER
    assert len(commands) == 1
    assert source_zip.read_bytes() == original
    assert (workspace / "source" / module.LEGACY_ENTRY).read_bytes() == b"old application"
    staged = workspace / "payload"
    files = validate_manifest(staged / protocol.INSTALL_MANIFEST, staged)
    assert module.LEGACY_ENTRY not in files
    assert (staged / protocol.MAIN_EXECUTABLE).read_bytes() == b"old application"
    assert (staged / "_internal/adblab-adb.exe").read_bytes() == b"old adb"
    assert protocol.APP_ID in (workspace / "protocol.iss").read_text(encoding="utf-8-sig")
    receipt = json.loads((workspace / "legacy-origin.json").read_text(encoding="utf-8"))
    assert receipt["historical_installer"] is False
    assert receipt["tag_sha"] == module.LEGACY_TAG_SHA


def test_run_is_rejected_on_desktop_before_download_or_install(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "prepare_legacy_installer", lambda *a: pytest.fail("downloaded"))
    with pytest.raises(ValueError, match="一次性"):
        module.run_legacy_upgrade(
            tmp_path / "iscc", tmp_path / "setup", "3.3.3", tmp_path / "fresh", disposable=True,
        )
    assert not (tmp_path / "fresh").exists()


@pytest.mark.parametrize("version", ["3.3.1", "3.3.2", "v3.3.2", "v3.2.29", "invalid"])
def test_run_rejects_non_upgrade_target_before_workspace_writes(tmp_path, monkeypatch, version):
    module = _module()
    monkeypatch.setattr(module.product, "validate_environment", lambda path, disposable: path)
    monkeypatch.setattr(module, "prepare_legacy_installer", lambda *a: pytest.fail("prepared"))
    with pytest.raises(ValueError, match="目标版本"):
        module.run_legacy_upgrade(
            tmp_path / "iscc", tmp_path / "setup", version, tmp_path / "fresh", disposable=True,
        )
    assert not (tmp_path / "fresh").exists()


def test_existing_product_prevents_download_and_data_creation(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.product, "validate_environment", lambda path, disposable: path)
    monkeypatch.setattr(module, "check_installer_file", lambda _: None)
    monkeypatch.setattr(module.product, "registered_installations", lambda: [{"path": "existing"}])
    monkeypatch.setattr(module, "prepare_legacy_installer", lambda *a: pytest.fail("prepared"))
    with pytest.raises(ValueError, match="已有产品"):
        module.run_legacy_upgrade(
            tmp_path / "iscc", tmp_path / "setup", "3.3.3", tmp_path / "fresh", disposable=True,
        )
    assert not (tmp_path / "fresh").exists()


def test_synthetic_data_uses_real_locations_and_never_overwrites(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.product, "_known_folder", lambda _: tmp_path / "local")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "redirected"))
    sentinels = module._create_sentinels()
    assert tmp_path / "local/ADBLab/config/app_settings.json" in sentinels
    assert tmp_path / "local/ADBLab/config/test_runs.json" in sentinels
    assert tmp_path / "local/ADBLab/config/connected_devices.yaml" in sentinels
    assert any(path.is_relative_to(tmp_path / "home/ADBLab") for path in sentinels)
    assert all(path.read_bytes() == value for path, value in sentinels.items())
    with pytest.raises(ValueError, match="已存在"):
        module._create_sentinels()
    assert all(path.read_bytes() == value for path, value in sentinels.items())


def test_synthetic_history_is_nonempty_valid_compatible_data(tmp_path, monkeypatch):
    module = _module()
    from services.run_library import RunLibrary

    monkeypatch.setattr(module.product, "_known_folder", lambda _: tmp_path / "local")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    sentinels = module._create_sentinels()
    history_path = tmp_path / "local/ADBLab/config/test_runs.json"
    history = RunLibrary(history_path)
    history.load()
    assert len(history.records) == 1
    assert history.records[0].run_id == "installer-legacy-ci-run"
    assert len(history.presets) == 1
    assert history_path.read_bytes() == sentinels[history_path]


def _scenario(tmp_path, monkeypatch):
    module = _module()
    from core import windows_installation as protocol
    from scripts.windows_installer.manifest import stage_payload, validate_manifest

    workspace = tmp_path / "run"
    new_setup = tmp_path / "new-setup.exe"
    new_setup.write_bytes(b"new setup")
    old_source = tmp_path / "old-source"
    new_source = tmp_path / "new-source"
    for source, content in ((old_source, b"old"), (new_source, b"new")):
        (source / "_internal").mkdir(parents=True)
        (source / "entry.exe").write_bytes(content)
        (source / "_internal/adb.exe").write_bytes(content + b" adb")
    (old_source / "_internal/retired.dll").write_bytes(b"old dependency")
    old_payload, new_payload = tmp_path / "old-payload", tmp_path / "new-payload"
    stage_payload(old_source, "entry.exe", old_payload)
    stage_payload(new_source, "entry.exe", new_payload)
    old_files = validate_manifest(old_payload / protocol.INSTALL_MANIFEST, old_payload)
    new_files = validate_manifest(new_payload / protocol.INSTALL_MANIFEST, new_payload)
    events = []
    monkeypatch.setattr(module.product, "validate_environment", lambda path, disposable: path)
    monkeypatch.setattr(module.product, "registered_installations", lambda: [])
    monkeypatch.setattr(module.product, "_shortcuts", lambda: [])
    monkeypatch.setattr(module.product, "_known_folder", lambda _: tmp_path / "local")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(module, "check_installer_file", lambda _: None)

    def prepare(iscc, target):
        target.mkdir()
        shutil.copytree(old_payload, target / "payload")
        result = target / module.LEGACY_INSTALLER
        result.write_bytes(b"old test wrapper")
        return result

    monkeypatch.setattr(module, "prepare_legacy_installer", prepare)
    app = workspace / "真实旧载荷 中文 space"

    def run(command, log, **kwargs):
        if "frozen" in command:
            events.append("frozen")
            assert command[command.index("--executable") + 1] == str(app / protocol.MAIN_EXECUTABLE)
            assert kwargs["env"].get("LOCALAPPDATA") != str(workspace)
            return
        old = Path(command[0]).name == module.LEGACY_INSTALLER
        events.append("old" if old else "new")
        payload = old_payload if old else new_payload
        if not old:
            for retired in old_files.keys() - new_files.keys():
                (app / retired).unlink()
        shutil.copytree(payload, app, dirs_exist_ok=True)

    monkeypatch.setattr(module.product, "run_checked", run)

    def ready(target, version):
        events.append(version)
        return set(validate_manifest(target / protocol.INSTALL_MANIFEST, target))

    monkeypatch.setattr(module.product, "_assert_ready", ready)

    def uninstall(target, root, label, env, managed):
        events.append("uninstall")
        for name in managed | {protocol.INSTALL_MANIFEST}:
            (target / name).unlink()

    monkeypatch.setattr(module.product, "_uninstall", uninstall)
    return module, workspace, new_setup, events, app


def test_real_payload_sequence_checks_old_new_frozen_and_retention(tmp_path, monkeypatch, capsys):
    module, workspace, setup, events, app = _scenario(tmp_path, monkeypatch)
    module.run_legacy_upgrade(tmp_path / "iscc", setup, "v3.3.3", workspace, disposable=True)
    assert events == ["old", "3.3.2", "frozen", "new", "3.3.3", "frozen", "uninstall"]
    assert (app / "_internal/retired.dll").read_bytes() == b"new user data at retired legacy path\n"
    assert "not a historical installer" in capsys.readouterr().out
    evidence = json.loads((workspace / "legacy-upgrade-evidence.json").read_text(encoding="utf-8"))
    assert evidence["old_manifest_sha256"] != evidence["new_manifest_sha256"]
    assert evidence["retired_replacement_verified"] is True


def test_upgrade_corruption_of_external_synthetic_data_fails(tmp_path, monkeypatch):
    module, workspace, setup, events, _ = _scenario(tmp_path, monkeypatch)
    original = module.product.run_checked

    def corrupt(command, log, **kwargs):
        original(command, log, **kwargs)
        if events[-1] == "new":
            (tmp_path / "local/ADBLab/config/test_runs.json").write_bytes(b"lost history")

    monkeypatch.setattr(module.product, "run_checked", corrupt)
    with pytest.raises(RuntimeError, match="合成数据"):
        module.run_legacy_upgrade(tmp_path / "iscc", setup, "3.3.3", workspace, disposable=True)
    assert "uninstall" not in events


def test_installed_payload_hash_mismatch_fails_before_frozen(tmp_path, monkeypatch):
    module, workspace, setup, events, app = _scenario(tmp_path, monkeypatch)
    original = module.product.run_checked

    def corrupt(command, log, **kwargs):
        original(command, log, **kwargs)
        if events[-1] == "old":
            (app / "ADBLab.exe").write_bytes(b"wrong old executable")

    monkeypatch.setattr(module.product, "run_checked", corrupt)
    with pytest.raises(ValueError, match="摘要"):
        module.run_legacy_upgrade(tmp_path / "iscc", setup, "3.3.3", workspace, disposable=True)
    assert "frozen" not in events


def test_frozen_failure_stops_upgrade_without_success_evidence(tmp_path, monkeypatch):
    module, workspace, setup, events, _ = _scenario(tmp_path, monkeypatch)
    original = module.product.run_checked

    def fail_probe(command, log, **kwargs):
        if "frozen" in command:
            raise RuntimeError("old frozen failed")
        original(command, log, **kwargs)

    monkeypatch.setattr(module.product, "run_checked", fail_probe)
    with pytest.raises(RuntimeError, match="old frozen failed"):
        module.run_legacy_upgrade(tmp_path / "iscc", setup, "3.3.3", workspace, disposable=True)
    assert "new" not in events
    assert not (workspace / "legacy-upgrade-evidence.json").exists()


def test_frozen_must_not_change_current_managed_payload(tmp_path, monkeypatch):
    module, workspace, setup, events, app = _scenario(tmp_path, monkeypatch)
    original = module.product.run_checked

    def corrupt(command, log, **kwargs):
        original(command, log, **kwargs)
        if "frozen" in command and "new" in events:
            (app / "ADBLab.exe").write_bytes(b"current probe mutated managed payload")

    monkeypatch.setattr(module.product, "run_checked", corrupt)
    with pytest.raises(ValueError, match="摘要"):
        module.run_legacy_upgrade(tmp_path / "iscc", setup, "3.3.3", workspace, disposable=True)
    assert "uninstall" not in events
