import os
import yaml

class DeviceStore:
    _devices = {}
    _file_path = os.path.join("resources", "connected_devices.yaml")

    @classmethod
    def load(cls):
        """从 YAML 文件中加载设备列表"""
        cls._devices.clear()
        if os.path.exists(cls._file_path):
            try:
                with open(cls._file_path, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f) or {}
                    for d in content.get("devices", []):
                        alias = d.get("alias")
                        ip = d.get("ip")
                        if alias and ip:
                            cls._devices[alias] = ip
            except Exception as e:
                print(f"[DeviceStore] Failed to load devices: {e}")

    @classmethod
    def add_device(cls, alias: str, ip: str):
        cls._devices[alias] = ip

    @classmethod
    def get_all(cls):
        return list(cls._devices.items())

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
