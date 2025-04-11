import os
import yaml

class DeviceStore:
    _devices = {}

    @classmethod
    def add_device(cls, alias: str, ip: str):
        """添加或更新设备到设备池"""
        cls._devices[alias] = ip

    @classmethod
    def get_all(cls):
        """返回所有设备的 (alias, ip) 元组列表"""
        return list(cls._devices.items())

    @classmethod
    def get_ip_by_alias(cls, alias: str) -> str:
        """根据别名获取 IP"""
        return cls._devices.get(alias, "")

    @classmethod
    def get_alias_by_ip(cls, ip: str) -> str:
        """根据 IP 获取别名"""
        for alias, device_ip in cls._devices.items():
            if device_ip == ip:
                return alias
        return ""

    @classmethod
    def remove_device(cls, alias: str):
        """移除设备"""
        if alias in cls._devices:
            del cls._devices[alias]

    @classmethod
    def clear(cls):
        """清空所有设备"""
        cls._devices.clear()
