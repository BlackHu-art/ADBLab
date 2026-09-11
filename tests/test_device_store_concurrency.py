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
        return self

    def __exit__(self, *_exc):
        DeviceStore._file_path = self.file_path
        DeviceStore._legacy_file_path = self.legacy_path
        DeviceStore._devices = self.devices


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
