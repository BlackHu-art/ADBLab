"""在线程安全的内存快照与用户 YAML 文件之间持久化设备信息。"""

import copy
import os
import shutil
import tempfile
from datetime import datetime
from threading import RLock

import yaml

from core.log_service import LogService
from utils.resource_path import resource_path
from utils.user_data import user_config_path


class DeviceStore:
    """维护设备信息快照，并以原子替换方式写入用户配置目录。

    加载失败时先尝试备份损坏的用户文件，再回退为空快照；写入失败会清理临时文件并
    将异常交给调用方处理。
    """

    _lock = RLock()
    _devices = {}
    _file_path = user_config_path("connected_devices.yaml")
    _legacy_file_path = resource_path("resources/connected_devices.yaml")

    @classmethod
    def load(cls):
        """加载用户设备文件，并在首次使用时迁移有效的旧版数据。"""
        with cls._lock:
            source_path = cls._file_path
            if not os.path.exists(source_path) and os.path.exists(cls._legacy_file_path):
                source_path = cls._legacy_file_path
            if not os.path.exists(source_path):
                cls._devices = {}
                return
            try:
                with open(source_path, encoding="utf-8") as f:
                    content = yaml.safe_load(f) or {}
                if not isinstance(content, dict):
                    raise ValueError("device store is not a YAML mapping")
                loaded = {
                    str(device_id): copy.deepcopy(info)
                    for device_id, info in content.items()
                    if isinstance(info, dict)
                }
                cls._devices = loaded
                if source_path != cls._file_path and loaded:
                    cls._write_snapshot_atomic(copy.deepcopy(loaded))
            except Exception as exc:
                if source_path == cls._file_path and os.path.isfile(source_path):
                    cls._backup_corrupt_file(source_path)
                cls._devices = {}
                LogService.write_developer_console(
                    "ERROR",
                    f"DeviceStore 加载失败：{type(exc).__name__}",
                )

    @classmethod
    def save(cls):
        """在线程锁内保存当前设备快照。"""
        with cls._lock:
            cls._write_snapshot_atomic(copy.deepcopy(cls._devices))

    @classmethod
    def initialize_empty(cls):
        with cls._lock:
            cls._devices = {}

    @classmethod
    def _write_snapshot_atomic(cls, snapshot: dict):
        """写入同目录临时文件并原子替换目标文件，失败时清理临时文件。"""
        directory = os.path.dirname(cls._file_path)
        os.makedirs(directory, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".connected_devices_",
            suffix=".yaml.tmp",
            dir=directory,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(snapshot, f, allow_unicode=True, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, cls._file_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _backup_corrupt_file(path: str):
        """尽力备份损坏文件；备份失败不覆盖原始加载失败结果。"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        backup_path = f"{path}.corrupt-{timestamp}"
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            pass

    @classmethod
    def add_device(
        cls,
        alias: str,
        ip: str,
        brand: str = "Unknown",
        model: str = "Unknown",
        android_version: str = "",
    ):
        cls.upsert_devices(
            [
                {
                    "alias": alias,
                    "ip": ip,
                    "Brand": brand,
                    "Model": model,
                    "Aversion": str(android_version),
                }
            ]
        )

    @classmethod
    def upsert_devices(cls, devices: list[dict]):
        """批量写入设备信息，一轮刷新只落盘一次，减少 YAML I/O 抖动。"""
        with cls._lock:
            changed = False
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
                changed = True
            if changed:
                cls._write_snapshot_atomic(copy.deepcopy(cls._devices))

    @classmethod
    def get_all(cls):
        with cls._lock:
            return [(alias, copy.deepcopy(data)) for alias, data in cls._devices.items()]

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
                copy.deepcopy(device)
                for device in cls._devices.values()
                if isinstance(device, dict) and device.get("ip") in ip_list
            ]
