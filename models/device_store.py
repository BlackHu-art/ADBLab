import os
from threading import Lock

import yaml

from utils.resource_path import resource_path


class DeviceStore:
    _lock = Lock()
    _devices = {}
    _file_path = resource_path("resources/connected_devices.yaml")

    @classmethod
    def load(cls):
        cls._devices.clear()
        if os.path.exists(cls._file_path):
            try:
                with open(cls._file_path, encoding="utf-8") as f:
                    content = yaml.safe_load(f) or {}
                    for device_id, info in content.items():
                        if isinstance(info, dict):
                            cls._devices[device_id] = info
            except Exception as e:
                print(f"[DeviceStore] Failed to load devices: {e}")

    @classmethod
    def save(cls):
        os.makedirs(os.path.dirname(cls._file_path), exist_ok=True)
        with open(cls._file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cls._devices, f)

    @classmethod
    def add_device(
        cls, alias: str, ip: str, brand: str = "Unknown", model: str = "Unknown", android_version: str = ""
    ):
        cls.upsert_devices([
            {
                "alias": alias,
                "ip": ip,
                "Brand": brand,
                "Model": model,
                "Aversion": str(android_version),
            }
        ])

    @classmethod
    def upsert_devices(cls, devices: list[dict]):
        """批量写入设备信息，一轮刷新只落盘一次，减少 YAML I/O 抖动。"""
        with cls._lock:
            for device in devices:
                if not isinstance(device, dict):
                    continue
                ip = str(device.get("ip", "")).strip()
                if not ip:
                    continue
                alias = str(device.get("alias") or f"device_{ip}")
                cls._devices[alias] = {
                    "ip": ip,
                    "Brand": device.get("Brand", "Unknown"),
                    "Model": device.get("Model", "Unknown"),
                    "Aversion": str(device.get("Aversion", "")),
                }
        if devices:
            cls.save()

    @classmethod
    def get_all(cls):
        with cls._lock:
            return list(cls._devices.items())

    @classmethod
    def get_basic_devices_info(cls):
        with cls._lock:
            return [
                (data.get("Brand", "Unknown"), data.get("Model", "Unknown"), data.get("ip", ""))
                for data in cls._devices.values()
                if isinstance(data, dict)
            ]

    @classmethod
    def get_full_devices_info(cls, ip_list: list[str]) -> list[dict]:
        with cls._lock:
            return [
                device
                for device in cls._devices.values()
                if isinstance(device, dict) and device.get("ip") in ip_list
            ]
