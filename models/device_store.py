import os
from typing import List
import yaml
from threading import Lock


class DeviceStore:
    _lock = Lock()
    _devices = {}
    _file_path = os.path.join("resources", "connected_devices.yaml")

    @classmethod
    def load(cls):
        cls._devices.clear()
        if os.path.exists(cls._file_path):
            try:
                with open(cls._file_path, "r", encoding="utf-8") as f:
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
    def add_device(cls, alias: str, ip: str, brand: str = "Unknown", model: str = "Unknown"):
        cls._devices[alias] = {
            "ip": ip,
            "Brand": brand,
            "Model": model
        }
        cls.save()

    @classmethod
    def get_all(cls):
        with cls._lock:
            return list(cls._devices.items())

    @classmethod
    def get_basic_devices_info(cls):
        return [
            (data.get("Brand", "Unknown"), data.get("Model", "Unknown"), data.get("ip", ""))
            for data in cls._devices.values() if isinstance(data, dict)
        ]

    @classmethod
    def get_full_devices_info(cls, ip_list: List[str]) -> List[dict]:
        return [
            device for device in cls._devices.values()
            if isinstance(device, dict) and device.get("ip") in ip_list
        ]
