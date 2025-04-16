import os
import yaml
from threading import Lock


class DeviceStore:
    _lock = Lock()
    _devices = {}
    _file_path = os.path.join("resources", "connected_devices.yaml")

    @classmethod
    def load(cls):
        """适配新YAML格式"""
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
    def get_all(cls):
        with cls._lock:
            return list(cls._devices.items())
    
    @classmethod
    def get_basic_devices_info(cls):
        """返回 [(brand, model, ip)] 格式"""
        return [
            (data.get("Brand", "Unknown"), data.get("Model", "Unknown"), data.get("ip", ""))
            for data in cls._devices.values() if isinstance(data, dict)
        ]

    @classmethod
    def add_device(cls, alias: str, ip: str, brand: str = "Unknown", model: str = "Unknown"):
        cls._devices[alias] = {
            "ip": ip,
            "Brand": brand,
            "Model": model
        }

    @classmethod
    def get_ip_by_alias(cls, alias: str) -> str:
        return cls._devices.get(alias, "")

    @classmethod
    def get_alias_by_ip(cls, ip: str) -> str:
        for alias, device_ip in cls._devices.items():
            if device_ip == ip:
                return alias
        return ""

    @classmethod
    def remove_device(cls, alias: str):
        if alias in cls._devices:
            del cls._devices[alias]

    @classmethod
    def clear(cls):
        cls._devices.clear()
