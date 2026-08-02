import threading
from unittest.mock import patch

import yaml

from models.device_store import DeviceStore


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


def test_device_store_concurrent_upserts_keep_all_devices(tmp_path):
    with _DeviceStoreState():
        DeviceStore._file_path = str(tmp_path / "config" / "connected_devices.yaml")
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore.initialize_empty()

        threads = [
            threading.Thread(
                target=DeviceStore.upsert_devices,
                args=([{"alias": f"d{i}", "ip": f"device-{i}", "Model": f"M{i}"}],),
            )
            for i in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        stored = yaml.safe_load((tmp_path / "config" / "connected_devices.yaml").read_text("utf-8"))
        assert len(stored) == 20
        assert {item["ip"] for item in stored.values()} == {f"device-{i}" for i in range(20)}


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


def test_device_store_corrupt_yaml_is_backed_up_and_cleared(tmp_path):
    with _DeviceStoreState(), patch("models.device_store.LogService") as log_service:
        store_path = tmp_path / "config" / "connected_devices.yaml"
        store_path.parent.mkdir(parents=True)
        store_path.write_text("broken: [", encoding="utf-8")
        DeviceStore._file_path = str(store_path)
        DeviceStore._legacy_file_path = str(tmp_path / "missing.yaml")
        DeviceStore._devices = {"stale": {"ip": "old"}}

        DeviceStore.load()

        assert DeviceStore.get_all() == []
        backups = list(store_path.parent.glob("connected_devices.yaml.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text("utf-8") == "broken: ["
        log_service.assert_not_called()
        log_service.write_developer_console.assert_called_once()
        level, message = log_service.write_developer_console.call_args.args
        assert level == "ERROR"
        assert message.startswith("DeviceStore 加载失败：")
