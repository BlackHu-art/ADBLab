"""测试结果库的重启恢复、原子保存、有界保留与失效输入保护。"""

import json
from dataclasses import asdict, replace

import pytest

from services.run_library import RunArtifact, RunLibrary, RunRecord


def record(identifier="one", **kwargs):
    return RunRecord(
        identifier,
        "monkey",
        "com.example.app",
        10,
        20,
        "succeeded",
        {"seed": 41, "events": 100},
        **kwargs,
    )


def test_restart_retains_parameters_state_and_artifacts(tmp_path):
    path = tmp_path / "runs.json"
    artifact = tmp_path / "monkey.txt"
    artifact.write_text("log", encoding="utf-8")
    saved = record(artifacts=(RunArtifact("Monkey 日志", str(artifact)),))
    first = RunLibrary(path)
    first.record_run(saved)
    first.save_preset("快速检查", "monkey", saved.parameters)
    second = RunLibrary(path)
    second.load()
    assert second.records == (saved,)
    assert second.presets[0].parameters == saved.parameters
    assert second.presets[0].name == "快速检查"


def test_capacity_and_duplicate_update_never_delete_artifact(tmp_path):
    artifact = tmp_path / "retained.txt"
    artifact.write_text("retain", encoding="utf-8")
    library = RunLibrary(tmp_path / "runs.json", capacity=2)
    library.record_run(record(artifacts=(RunArtifact("日志", str(artifact)),)))
    library.record_run(replace(record("two"), finished_at=21))
    library.record_run(replace(record("three"), finished_at=22))
    library.record_run(replace(record("two"), finished_at=23, state="cancelled"))
    assert [r.run_id for r in library.records] == ["two", "three"]
    assert library.records[0].state == "cancelled"
    assert artifact.read_text(encoding="utf-8") == "retain"


def test_failed_replace_preserves_memory_and_original_file(tmp_path, monkeypatch):
    library = RunLibrary(tmp_path / "runs.json")
    library.record_run(record())
    original = library.path.read_bytes()

    def fail_replace(*_args):
        raise PermissionError("denied")

    monkeypatch.setattr("services.run_library.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        library.record_run(record("two"))
    assert library.records == (record(),)
    assert library.path.read_bytes() == original
    assert list(tmp_path.glob(".runs-*")) == []


@pytest.mark.parametrize(
    "raw",
    [
        b"{broken",
        b'{"version":2,"runs":[],"presets":[]}',
        b'{"version":1,"runs":[{}],"presets":[]}',
    ],
)
def test_corrupt_or_future_library_is_not_overwritten(tmp_path, raw):
    path = tmp_path / "runs.json"
    path.write_bytes(raw)
    library = RunLibrary(path)
    with pytest.raises(ValueError):
        library.load()
    with pytest.raises(ValueError):
        library.record_run(record())
    assert path.read_bytes() == raw


def test_named_preset_update_isolated_from_caller_and_other_kind():
    library = RunLibrary()
    params = {"monkey_config": {"seed": 41}}
    library.save_preset("快速", "monkey", params)
    identifier = library.presets[0].preset_id
    params["monkey_config"]["seed"] = 99
    assert library.presets[0].parameters["monkey_config"]["seed"] == 41
    library.save_preset("快速", "monkey", {"seed": 88})
    library.save_preset("快速", "performance", {"frequency_seconds": 2})
    assert len(library.presets) == 2
    assert library.presets[0].preset_id == identifier
    library.delete_preset(identifier)
    assert [p.kind for p in library.presets] == ["performance"]


@pytest.mark.parametrize(
    "params",
    [
        {"device_ip": "old-target"},
        {"seed": float("nan")},
        {"callback": object()},
        {"seed": "x" * 17000},
    ],
)
def test_invalid_or_device_bound_parameters_rejected(params):
    library = RunLibrary()
    with pytest.raises(ValueError):
        library.record_run(replace(record(), parameters=params))
    assert library.records == ()


def test_relative_or_url_artifact_is_rejected():
    library = RunLibrary()
    for path in ("relative.txt", "https://example.invalid/log", "shell:command"):
        with pytest.raises(ValueError):
            library.record_run(record(artifacts=(RunArtifact("日志", path),)))


def test_snapshot_does_not_share_nested_parameter_values(tmp_path):
    library = RunLibrary(tmp_path / "runs.json")
    saved = replace(record(), parameters={"nested": {"events": 100}})
    library.record_run(saved)
    saved.parameters["nested"]["events"] = 200
    library.records[0].parameters["nested"]["events"] = 300
    assert library.records[0].parameters["nested"]["events"] == 100
    assert json.loads(library.path.read_text(encoding="utf-8"))["version"] == 1


def test_oversized_integer_timestamp_is_rejected_without_overwriting_file(tmp_path):
    path = tmp_path / "runs.json"
    invalid = replace(record(), started_at=10**500, finished_at=10**500)
    original = json.dumps({"version": 1, "runs": [asdict(invalid)], "presets": []})
    path.write_text(original, encoding="utf-8")
    library = RunLibrary(path)
    with pytest.raises(ValueError):
        library.load()
    with pytest.raises(ValueError):
        library.record_run(record())
    assert path.read_text(encoding="utf-8") == original
