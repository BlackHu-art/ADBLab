"""应用名称补全的 helper 优先、有限兼容和取消发布契约。"""

from types import SimpleNamespace

import pytest

from core.exec import CommandResult
from models import app_manager_worker as module


def record(package="com.example.one", label="应用一"):
    return SimpleNamespace(
        package=package, label=label, version="1.2 (12)",
        installed="2026-09-25", fingerprint="a" * 64,
    )


def observe(worker):
    signal = getattr(worker, "app_metadata_loaded", None)
    assert signal is not None, "名称补全应交付包含缓存身份的结构化元数据"
    rows, legacy = [], []
    signal.connect(rows.append)
    worker.app_detail_batch.connect(lambda *args: legacy.append(args))
    return rows, legacy


def test_metadata_worker_publishes_unicode_without_dumpsys(monkeypatch):
    calls = []

    def load(device, packages, cancelled):
        calls.append((device, packages, cancelled()))
        return SimpleNamespace(records={"com.example.one": record()}, unsupported=False)

    monkeypatch.setattr(module, "load_app_metadata", load, raising=False)
    worker = module.AppManagerWorker(
        "test-device", "load_metadata_batch", packages=["com.example.one"],
    )
    rows, legacy = observe(worker)
    monkeypatch.setattr(worker, "_adb", lambda *a, **kw: pytest.fail("元数据成功不得执行 dumpsys"))
    worker.run()
    assert calls == [("test-device", ["com.example.one"], False)]
    assert rows == [{
        "package": "com.example.one", "label": "应用一", "version": "1.2 (12)",
        "installed": "2026-09-25", "fingerprint": "a" * 64,
    }]
    assert legacy == []


@pytest.mark.parametrize("unsupported", [False, True])
def test_only_explicit_unsupported_metadata_uses_legacy_query(monkeypatch, unsupported):
    monkeypatch.setattr(module, "load_app_metadata", lambda *a: SimpleNamespace(
        records={}, unsupported=unsupported,
    ), raising=False)
    worker = module.AppManagerWorker(
        "test-device", "load_metadata_batch", packages=["com.example.one"],
    )
    rows, legacy = observe(worker)
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        return CommandResult(True, (
            "__ADBLAB_PKG_BEGIN_0__\nnonLocalizedLabel=One App\n"
            "versionName=1.2\nversionCode=12\n__ADBLAB_PKG_END_0__"
        ))

    monkeypatch.setattr(worker, "_adb", adb)
    worker.run()
    assert rows == []
    assert len(calls) == int(unsupported)
    assert legacy == ([("com.example.one", "One App", "1.2 (12)", "")] if unsupported else [])


@pytest.mark.parametrize("when", ["before", "during", "between_results"])
def test_metadata_cancel_stops_service_or_late_publication(monkeypatch, when):
    worker = module.AppManagerWorker(
        "test-device", "load_metadata_batch", packages=["com.example.one", "com.example.two"],
    )
    rows, legacy = observe(worker)
    calls = []

    def load(device, packages, cancelled):
        calls.append(device)
        if when == "during":
            worker.abort()
            assert cancelled()
        return SimpleNamespace(records={pkg: record(pkg) for pkg in packages}, unsupported=False)

    monkeypatch.setattr(module, "load_app_metadata", load, raising=False)
    monkeypatch.setattr(worker, "_adb", lambda *a, **kw: pytest.fail("取消后不得启动兼容查询"))
    if when == "before":
        worker.abort()
    if when == "between_results":
        worker.app_metadata_loaded.connect(lambda row: worker.abort())
    worker.run()
    assert len(calls) == (0 if when == "before" else 1)
    assert len(rows) == (1 if when == "between_results" else 0)
    assert legacy == []


def test_unsupported_fallback_does_not_extend_initial_deadline(monkeypatch):
    worker = module.AppManagerWorker(
        "test-device", "load_metadata_batch", packages=["com.example.one"],
    )
    rows, legacy = observe(worker)
    now = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    def load(*args):
        now[0] += 31
        return SimpleNamespace(records={}, unsupported=True)

    monkeypatch.setattr(module, "load_app_metadata", load, raising=False)
    monkeypatch.setattr(worker, "_adb", lambda *a, **kw: pytest.fail("耗尽预算后不得叠加查询"))
    worker.run()
    assert rows == legacy == []


def test_unsupported_fallback_spends_only_remaining_query_budget(monkeypatch):
    worker = module.AppManagerWorker(
        "test-device", "load_metadata_batch", packages=["com.example.one"],
    )
    rows, legacy = observe(worker)
    now = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    def load(*args):
        now[0] += 12
        return SimpleNamespace(records={}, unsupported=True)

    def adb(*args, timeout, cancellable):
        assert timeout == 18.0 and cancellable
        now[0] += timeout
        return CommandResult(False, error="Timeout")

    monkeypatch.setattr(module, "load_app_metadata", load, raising=False)
    monkeypatch.setattr(worker, "_adb", adb)
    worker.run()
    assert now[0] == 130.0
    assert rows == legacy == []


def test_icon_worker_preserves_expected_identity_for_transport_validation(monkeypatch):
    identities = []

    def load(device, packages, cancelled, emit, *, expected_fingerprints=None):
        identities.append(expected_fingerprints)

    monkeypatch.setattr(module, "load_app_icons", load)
    worker = module.AppManagerWorker(
        "test-device", "load_icon_batch", packages=["com.example.one"],
        expected_fingerprints={"com.example.one": "a" * 64},
    )
    worker.run()
    assert identities == [{"com.example.one": "a" * 64}]
