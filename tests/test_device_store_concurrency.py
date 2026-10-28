import io
import sys
import threading
from unittest.mock import patch

import pytest
import yaml

from models.device_store import DeviceStore
from tests.test_logging_contract import create_log_service  # noqa: F401  复用隔离单例的 fixture。


class _DeviceStoreState:
    def __enter__(self):
        self.file_path = DeviceStore._file_path
        self.legacy_path = DeviceStore._legacy_file_path
        self.devices = DeviceStore._devices
        self.protected_paths = DeviceStore._protected_paths.copy()
        return self

    def __exit__(self, *_exc):
        DeviceStore._file_path = self.file_path
        DeviceStore._legacy_file_path = self.legacy_path
        DeviceStore._devices = self.devices
        DeviceStore._protected_paths = self.protected_paths


def test_cancelled_load_does_not_replace_memory_or_repair_disk(tmp_path, monkeypatch):
    from concurrent.futures import CancelledError

    with _DeviceStoreState():
        target = tmp_path / "history.yaml"
        raw = "wifi:\n  ip: 192.0.2.10:5555\nusb:\n  ip: synthetic-usb\n"
        target.write_text(raw, encoding="utf-8")
        DeviceStore._file_path = str(target)
        DeviceStore._devices = {"existing": {"ip": "192.0.2.11:5555"}}
        cancel = threading.Event()
        parse = DeviceStore._parse_snapshot

        def cancel_after_parse(text, *, strict):
            result = parse(text, strict=strict)
            cancel.set()
            return result

        monkeypatch.setattr(DeviceStore, "_parse_snapshot", cancel_after_parse)
        with pytest.raises(CancelledError):
            DeviceStore.load(cancel_event=cancel)
        assert target.read_text("utf-8") == raw
        assert dict(DeviceStore.get_all()) == {"existing": {"ip": "192.0.2.11:5555"}}


def test_cancelled_load_exits_while_another_thread_still_holds_store_lock():
    from concurrent.futures import CancelledError

    holding = threading.Event()
    release = threading.Event()
    entering = threading.Event()
    exited = threading.Event()
    cancel = threading.Event()
    outcomes = []

    def holder():
        with DeviceStore._lock:
            holding.set()
            release.wait(5)

    def waiter():
        entering.set()
        try:
            DeviceStore.load(cancel_event=cancel)
        except CancelledError:
            outcomes.append("cancelled")
        finally:
            exited.set()

    holding_thread = threading.Thread(target=holder)
    waiting_thread = threading.Thread(target=waiter)
    try:
        holding_thread.start()
        assert holding.wait(2)
        waiting_thread.start()
        assert entering.wait(2)
        cancel.set()
        assert exited.wait(1), "cancelled load must leave lock wait before the holder releases"
        assert holding_thread.is_alive()
        assert outcomes == ["cancelled"]
    finally:
        release.set()
        holding_thread.join(5)
        if waiting_thread.ident is not None:
            waiting_thread.join(5)


def test_cancelled_read_retry_does_not_wait_or_backup(tmp_path, monkeypatch):
    from concurrent.futures import CancelledError

    with _DeviceStoreState():
        target = tmp_path / "history.yaml"
        target.write_text("{}", encoding="utf-8")
        DeviceStore._file_path = str(target)
        cancel = threading.Event()

        def interrupted_open(*_args, **_kwargs):
            cancel.set()
            raise OSError("synthetic lock")

        monkeypatch.setattr("models.device_store.open", interrupted_open, raising=False)
        monkeypatch.setattr(DeviceStore, "_LOAD_RETRY_DELAY_S", 30)
        with pytest.raises(CancelledError):
            DeviceStore.load(cancel_event=cancel)
        assert not list(tmp_path.glob("*.corrupt-*"))


def test_history_persists_only_ip_targets_but_keeps_usb_metadata_in_memory(tmp_path):
    with _DeviceStoreState():
        store_path = tmp_path / "connected_devices.yaml"
        DeviceStore._file_path = str(store_path)
        DeviceStore.initialize_empty()
        DeviceStore.upsert_devices([
            {"ip": "usb-demo", "Brand": "Demo", "Model": "USB Phone"},
            {"ip": "emulator-5554"},
        ])
        assert not store_path.exists()
        assert DeviceStore.get_full_devices_info(["usb-demo"])[0]["Model"] == "USB Phone"
        assert DeviceStore.get_basic_devices_info() == []

        DeviceStore.upsert_devices([
            {"alias": "wifi", "ip": "192.0.2.10:5555", "Brand": "Demo", "Model": "WiFi"},
            {"alias": "ipv6", "ip": "[2001:db8::1]:5555", "Model": "IPv6"},
            {"ip": "192.0.2.11:70000"},
            {"ip": "adb-demo._adb-tls-connect._tcp"},
        ])
        DeviceStore.save()
        stored = yaml.safe_load(store_path.read_text("utf-8"))
        assert set(stored) == {"wifi", "ipv6"}
        assert {item[2] for item in DeviceStore.get_basic_devices_info()} == {
            "192.0.2.10:5555", "[2001:db8::1]:5555",
        }
        assert DeviceStore.get_full_devices_info(["usb-demo"])[0]["Model"] == "USB Phone"


@pytest.mark.parametrize("legacy", [False, True])
def test_loading_old_history_cleans_non_ip_entries_and_preserves_ip_metadata(tmp_path, legacy):
    with _DeviceStoreState():
        user_path = tmp_path / "connected_devices.yaml"
        legacy_path = tmp_path / "legacy.yaml"
        source = legacy_path if legacy else user_path
        DeviceStore._file_path = str(user_path)
        DeviceStore._legacy_file_path = str(legacy_path)
        snapshot = {
            "usb": {"ip": "usb-demo", "Model": "USB"},
            "emulator": {"ip": "emulator-5554"},
            "missing": {"Model": "Missing"},
            "bad_port": {"ip": "192.0.2.1:0"},
            "wifi": {"ip": "192.0.2.10:5555", "Brand": "Demo", "Model": "WiFi", "custom": "kept"},
            "ipv6": {"ip": "[2001:db8::1]:5555", "Aversion": "14"},
        }
        source.write_text(yaml.safe_dump(snapshot), encoding="utf-8")
        DeviceStore.initialize_empty()
        DeviceStore.load()
        expected = {key: snapshot[key] for key in ("wifi", "ipv6")}
        assert dict(DeviceStore.get_all()) == expected
        assert yaml.safe_load(user_path.read_text("utf-8")) == expected
        if legacy:
            assert yaml.safe_load(legacy_path.read_text("utf-8")) == snapshot
        with patch.object(DeviceStore, "_persist_snapshot") as persist:
            DeviceStore.load()
        persist.assert_not_called()


def test_history_cleanup_write_failure_still_filters_list_and_can_retry(tmp_path):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "connected_devices.yaml"
        snapshot = {"usb": {"ip": "usb-demo"}, "wifi": {"ip": "192.0.2.10:5555"}}
        store_path.write_text(yaml.safe_dump(snapshot), encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore.initialize_empty()
        with patch.object(DeviceStore, "_persist_snapshot", side_effect=OSError("blocked")):
            DeviceStore.load()
        assert dict(DeviceStore.get_all()) == {"wifi": snapshot["wifi"]}
        assert yaml.safe_load(store_path.read_text("utf-8")) == snapshot
        assert log_service.return_value.log.call_args.args[0] == "WARNING"
        DeviceStore.save()
        assert yaml.safe_load(store_path.read_text("utf-8")) == {"wifi": snapshot["wifi"]}


def test_device_store_concurrent_upserts_keep_all_devices(tmp_path):
    with _DeviceStoreState():
        DeviceStore._file_path = str(tmp_path / "config" / "connected_devices.yaml")
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore.initialize_empty()

        threads = [
            threading.Thread(
                target=DeviceStore.upsert_devices,
                args=([{"alias": f"d{i}", "ip": f"192.0.2.{i + 1}:5555", "Model": f"M{i}"}],),
            )
            for i in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        stored = yaml.safe_load((tmp_path / "config" / "connected_devices.yaml").read_text("utf-8"))
        assert len(stored) == 20
        assert {item["ip"] for item in stored.values()} == {
            f"192.0.2.{i + 1}:5555" for i in range(20)
        }


def test_device_store_failed_replace_keeps_previous_file(tmp_path, monkeypatch):
    with _DeviceStoreState():
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        store_path.write_text("existing:\n  ip: stable\n", encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"new": {"ip": "replacement"}}

        def fail_replace(_source, _target):
            raise OSError("replace failed")

        monkeypatch.setattr("models.device_store.os.replace", fail_replace)

        try:
            DeviceStore.save()
        except OSError:
            pass
        else:
            raise AssertionError("save should propagate an atomic replacement failure")

        assert yaml.safe_load(store_path.read_text("utf-8")) == {"existing": {"ip": "stable"}}
        assert not list(store_path.parent.glob(".connected_devices_*.yaml.tmp"))


def test_device_store_corrupt_yaml_is_backed_up_and_snapshot_kept(tmp_path):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        store_path.write_text("broken: [", encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"stale": {"ip": "old"}}

        DeviceStore.load()

        # 加载失败必须保留内存快照，避免端点防护干扰时设备列表被清空。
        assert DeviceStore.get_all() == [("stale", {"ip": "old"})]
        backups = list(store_path.parent.glob("connected_devices.yaml.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text("utf-8") == "broken: ["
        log_service.return_value.log.assert_called_once()
        level, message = log_service.return_value.log.call_args.args
        assert level == "WARNING"
        assert message.startswith("DeviceStore 加载失败：")
        log_service.write_developer_console.assert_not_called()


@pytest.mark.parametrize("invalid_root", ["[]", "false", "0", "''", "[item]", "invalid"])
def test_device_store_rejects_non_mapping_roots_and_keeps_snapshot(tmp_path, invalid_root):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "connected_devices.yaml"
        store_path.write_text(invalid_root, encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"retained": {"ip": "device-1"}}

        DeviceStore.load()

        assert DeviceStore.get_all() == [("retained", {"ip": "device-1"})]
        assert store_path.read_text("utf-8") == invalid_root
        backups = list(tmp_path.glob("connected_devices.yaml.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text("utf-8") == invalid_root
        log_service.return_value.log.assert_called_once()


@pytest.mark.parametrize("empty_content", ["", " \n", "{}"])
def test_device_store_still_accepts_empty_files_and_empty_mappings(tmp_path, empty_content):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "connected_devices.yaml"
        store_path.write_text(empty_content, encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"previous": {"ip": "device-1"}}

        DeviceStore.load()

        assert DeviceStore.get_all() == []
        assert not list(tmp_path.glob("connected_devices.yaml.corrupt-*"))
        log_service.return_value.log.assert_not_called()


def test_device_store_load_tolerates_trailing_garbage_and_rewrites(tmp_path):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        # 模拟端点防护在文件尾部附加的 4KB 扫描块：首个文档合法，尾部是二进制垃圾。
        store_path.write_bytes(
            b"device_a:\n  ip: 192.0.2.1:5555\n" + b"\x00\x01\x02" + b"\x00" * 4096
        )
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore.initialize_empty()

        DeviceStore.load()

        assert DeviceStore.get_all() == [("device_a", {"ip": "192.0.2.1:5555"})]
        # 宽容解析成功后回写规范化文件，且不产生 corrupt 备份。
        rewritten = yaml.safe_load(store_path.read_text("utf-8"))
        assert rewritten == {"device_a": {"ip": "192.0.2.1:5555"}}
        assert not list(store_path.parent.glob("connected_devices.yaml.corrupt-*"))
        log_service.return_value.log.assert_called_once()


def test_device_store_load_retries_transient_oserror(tmp_path, monkeypatch):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        store_path.write_text("device_a:\n  ip: 192.0.2.1:5555\n", encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore.initialize_empty()

        monkeypatch.setattr("models.device_store.time.sleep", lambda _s: None)
        real_open = open
        calls = {"count": 0}

        def flaky_open(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("sharing violation")
            return real_open(*args, **kwargs)

        with patch("builtins.open", side_effect=flaky_open):
            DeviceStore.load()

        assert calls["count"] == 2
        assert DeviceStore.get_all() == [("device_a", {"ip": "192.0.2.1:5555"})]
        log_service.write_developer_console.assert_not_called()


def test_device_store_load_unreadable_keeps_snapshot(tmp_path, monkeypatch):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        store_path.write_text("device_a:\n  ip: a\n", encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"stale": {"ip": "old"}}

        monkeypatch.setattr("models.device_store.time.sleep", lambda _s: None)
        real_open = open

        def flaky_open(file, *args, **kwargs):
            # 只让 DeviceStore 的 UTF-8 文本读取失败；copy2 的二进制备份
            # 打开（encoding 缺失）不受影响，模拟火绒只锁住业务读取窗口。
            if str(file).endswith("connected_devices.yaml") and kwargs.get("encoding") == "utf-8":
                raise OSError("sharing violation")
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=flaky_open):
            DeviceStore.load()

        assert DeviceStore.get_all() == [("stale", {"ip": "old"})]
        backups = list(store_path.parent.glob("connected_devices.yaml.corrupt-*"))
        assert len(backups) == 1
        log_service.return_value.log.assert_called_once()
        assert log_service.return_value.log.call_args.args[0] == "WARNING"
        log_service.write_developer_console.assert_not_called()


@pytest.mark.parametrize("closed", [False, True])
def test_load_failure_prints_once_and_respects_log_service_shutdown(request, monkeypatch, closed):
    service = request.getfixturevalue("create_log_service")()
    stream = io.StringIO()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stderr", stream)
    emitted = []
    service.log_received.connect(lambda level, message: emitted.append((level, message)))
    if closed:
        service.shutdown()

    DeviceStore._note_load_failure("ParserError")
    service._flush_buffer()

    if closed:
        assert stream.getvalue() == ""
        assert emitted == []
        assert service.diagnostics.text() == ""
    else:
        assert stream.getvalue().count("DeviceStore") == 1
        assert "[WARNING]" in stream.getvalue()
        assert "[ERROR]" not in stream.getvalue()
        assert len(emitted) == 1 and emitted[0][0] == "WARNING"
        assert "ParserError" in emitted[0][1]
        assert service.diagnostics.text().count("DeviceStore") == 1


@pytest.mark.parametrize("failure_point", ["construct", "log"])
def test_load_failure_keeps_console_fallback_when_logging_service_fails(failure_point):
    with patch("models.device_store.LogService") as log_service:
        if failure_point == "construct":
            log_service.side_effect = RuntimeError("service unavailable")
        else:
            log_service.return_value.log.side_effect = RuntimeError("service write failed")

        DeviceStore._note_load_failure("PermissionError")

        log_service.write_developer_console.assert_called_once()
        level, message = log_service.write_developer_console.call_args.args
        assert level == "ERROR"
        assert "DeviceStore" in message and "PermissionError" in message

@pytest.mark.parametrize("hot", [False, True])
@pytest.mark.parametrize("entry", ["save", "add", "upsert"])
def test_unread_unbacked_history_refuses_all_writes(tmp_path, monkeypatch, hot, entry):
    with _DeviceStoreState(), patch("models.device_store.LogService"):
        target = tmp_path / "history.yaml"
        raw = b"original:\n  ip: 192.0.2.10:5555\n"
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        DeviceStore._devices = {"stale": {"ip": "192.0.2.11:5555"}} if hot else {}
        monkeypatch.setattr(DeviceStore, "_LOAD_RETRIES", 0)
        with patch("models.device_store.open", side_effect=OSError("locked"), create=True), patch(
            "models.device_store.shutil.copy2", side_effect=OSError("backup locked")
        ):
            DeviceStore.load()
        operations = {
            "save": DeviceStore.save,
            "add": lambda: DeviceStore.add_device("new", "192.0.2.12:5555"),
            "upsert": lambda: DeviceStore.upsert_devices(
                [{"alias": "new", "ip": "192.0.2.12:5555"}]
            ),
        }
        with pytest.raises(OSError, match="未安全读取或备份"):
            operations[entry]()
        assert target.read_bytes() == raw
        assert not list(tmp_path.glob(".connected_devices_*.yaml.tmp"))

@pytest.mark.parametrize("recovery", ["reload", "backup"])
def test_protected_history_unlocks_only_after_reload_or_backup(tmp_path, monkeypatch, recovery):
    with _DeviceStoreState(), patch("models.device_store.LogService"):
        target = tmp_path / "history.yaml"
        original = {"original": {"ip": "192.0.2.10:5555", "custom": "retained"}}
        raw = yaml.safe_dump(original).encode()
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        DeviceStore._devices = {"stale": {"ip": "192.0.2.11:5555"}}
        monkeypatch.setattr(DeviceStore, "_LOAD_RETRIES", 0)
        with patch("models.device_store.open", side_effect=OSError("locked"), create=True), patch(
            "models.device_store.shutil.copy2", side_effect=OSError("backup locked")
        ):
            DeviceStore.load()
        if recovery == "reload":
            DeviceStore.load()
            assert dict(DeviceStore.get_all()) == original
        else:
            with patch("models.device_store.open", side_effect=OSError("locked"), create=True):
                DeviceStore.load()
            backups = list(tmp_path.glob("history.yaml.corrupt-*"))
            assert len(backups) == 1
            assert backups[0].read_bytes() == raw
        DeviceStore.add_device("new", "192.0.2.12:5555")
        stored = yaml.safe_load(target.read_text("utf-8"))
        assert "new" in stored
        if recovery == "reload":
            assert stored["original"] == original["original"]
            assert "stale" not in stored
        assert not list(tmp_path.glob(".connected_devices_*.yaml.tmp"))


def test_protection_survives_path_switch_and_empty_memory_reset(tmp_path, monkeypatch):
    with _DeviceStoreState(), patch("models.device_store.LogService"):
        target = tmp_path / "protected.yaml"
        raw = b"broken: ["
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        with patch("models.device_store.shutil.copy2", side_effect=OSError("backup locked")):
            DeviceStore.load()
        DeviceStore.initialize_empty()
        other = tmp_path / "other.yaml"
        DeviceStore._file_path = str(other)
        DeviceStore.add_device("other", "192.0.2.12:5555")
        assert "other" in yaml.safe_load(other.read_text("utf-8"))
        DeviceStore._file_path = str(target.parent / "." / target.name)
        with pytest.raises(OSError, match="未安全读取或备份"):
            DeviceStore.save()
        assert target.read_bytes() == raw


def test_cancelled_unread_load_keeps_later_save_protected(tmp_path, monkeypatch):
    from concurrent.futures import CancelledError

    with _DeviceStoreState():
        target = tmp_path / "history.yaml"
        raw = b"original:\n  ip: 192.0.2.10:5555\n"
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        cancel = threading.Event()

        def cancel_read(*_args, **_kwargs):
            cancel.set()
            raise OSError("locked")

        with patch("models.device_store.open", side_effect=cancel_read, create=True):
            with pytest.raises(CancelledError):
                DeviceStore.load(cancel_event=cancel)
        with pytest.raises(OSError, match="未安全读取或备份"):
            DeviceStore.save()
        assert target.read_bytes() == raw
        assert not list(tmp_path.glob("*.corrupt-*"))
        DeviceStore.load()
        DeviceStore.save()
        assert yaml.safe_load(target.read_text("utf-8")) == {"original": {"ip": "192.0.2.10:5555"}}


def test_save_waiting_for_failed_load_cannot_overwrite_unread_history(tmp_path, monkeypatch):
    with _DeviceStoreState(), patch("models.device_store.LogService"):
        target = tmp_path / "history.yaml"
        raw = b"original:\n  ip: 192.0.2.10:5555\n"
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        DeviceStore._devices = {"stale": {"ip": "192.0.2.11:5555"}}
        monkeypatch.setattr(DeviceStore, "_LOAD_RETRIES", 0)
        reading = threading.Event()
        release = threading.Event()
        saving = threading.Event()
        outcomes = []

        def locked_read(*_args, **_kwargs):
            reading.set()
            assert release.wait(3)
            raise OSError("locked")

        def save():
            saving.set()
            try:
                DeviceStore.save()
            except OSError as exc:
                outcomes.append(str(exc))

        loader = threading.Thread(target=DeviceStore.load)
        saver = threading.Thread(target=save)
        with patch("models.device_store.open", side_effect=locked_read, create=True), patch(
            "models.device_store.shutil.copy2", side_effect=OSError("backup locked")
        ):
            try:
                loader.start()
                assert reading.wait(2)
                saver.start()
                assert saving.wait(2)
            finally:
                release.set()
                loader.join(3)
                if saver.ident is not None:
                    saver.join(3)
        assert not loader.is_alive() and not saver.is_alive()
        assert len(outcomes) == 1 and "未安全读取或备份" in outcomes[0]
        assert target.read_bytes() == raw

@pytest.mark.parametrize("tolerant", [False, True])
@pytest.mark.parametrize("hot", [False, True])
def test_cancel_after_parsing_keeps_file_protected_until_snapshot_published(
    tmp_path, monkeypatch, tolerant, hot
):
    from concurrent.futures import CancelledError

    with _DeviceStoreState(), patch("models.device_store.LogService"):
        target = tmp_path / "history.yaml"
        raw = b"original:\n  ip: 192.0.2.10:5555\n" + (b"\x00scan" if tolerant else b"")
        target.write_bytes(raw)
        DeviceStore._file_path = str(target)
        old = {"stale": {"ip": "192.0.2.11:5555"}} if hot else {}
        DeviceStore._devices = old.copy()
        cancel = threading.Event()
        connection_snapshot = DeviceStore._connection_snapshot

        def cancel_after_parse(snapshot):
            result = connection_snapshot(snapshot)
            cancel.set()
            return result

        with monkeypatch.context() as scoped:
            scoped.setattr(DeviceStore, "_connection_snapshot", cancel_after_parse)
            with pytest.raises(CancelledError):
                DeviceStore.load(cancel_event=cancel)
        assert dict(DeviceStore.get_all()) == old
        cancel.clear()
        with pytest.raises(OSError, match="未安全读取或备份"):
            DeviceStore.save()
        assert target.read_bytes() == raw
        assert not list(tmp_path.glob("*.corrupt-*"))
        assert not list(tmp_path.glob(".connected_devices_*.yaml.tmp"))
        DeviceStore.load()
        DeviceStore.save()
        assert yaml.safe_load(target.read_text("utf-8")) == {"original": {"ip": "192.0.2.10:5555"}}
