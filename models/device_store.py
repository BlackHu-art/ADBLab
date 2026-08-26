"""在线程安全的内存快照与用户 YAML 文件之间持久化设备信息。"""

import copy
import os
import shutil
import tempfile
import time
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
    # 端点防护（如火绒企业版）会瞬时锁定或在文件尾部附加扫描块：读取按瞬态
    # 错误重试，写入失败重试一次，避免设备列表因监控拦截被清空。
    _LOAD_RETRIES = 2
    _LOAD_RETRY_DELAY_S = 0.3
    _SAVE_RETRIES = 1
    _SAVE_RETRY_DELAY_S = 0.2

    @classmethod
    def load(cls):
        """加载用户设备文件；加载失败保留内存快照并备份损坏文件。

        端点防护可能瞬时锁文件或在文件尾部附加扫描块，因此读取失败按瞬态
        错误重试，解析失败先尝试仅取第一个 YAML 文档；所有失败路径都不清
        空已有内存快照，避免打包环境下设备列表被清空。
        """
        with cls._lock:
            source_path = cls._file_path
            if not os.path.exists(source_path) and os.path.exists(cls._legacy_file_path):
                source_path = cls._legacy_file_path
            if not os.path.exists(source_path):
                return
            loaded = cls._read_snapshot(source_path)
            if loaded is None:
                return
            if source_path != cls._file_path and loaded:
                try:
                    cls._persist_snapshot(copy.deepcopy(loaded))
                except OSError:
                    # 旧版数据迁移写入失败不阻断本次加载结果。
                    cls._note_load_failure("OSError")
            cls._devices = loaded

    @classmethod
    def _read_snapshot(cls, source_path: str) -> dict | None:
        """读取并解析设备快照；失败返回 None，绝不修改内存快照。"""
        raw = cls._read_text_with_retry(source_path)
        if raw is None:
            return None
        try:
            return cls._parse_snapshot(raw, strict=True)
        except (yaml.YAMLError, ValueError) as exc:
            cls._note_load_failure(type(exc).__name__)
            try:
                tolerant = cls._parse_snapshot(raw, strict=False)
            except (yaml.YAMLError, ValueError):
                tolerant = None
            if tolerant is None:
                if source_path == cls._file_path and os.path.isfile(source_path):
                    cls._backup_corrupt_file(source_path)
                return None
            # 文件尾部带监控附加块但首个文档合法：采用数据并回写规范化文件，
            # 不产生 corrupt 备份，避免干扰反复出现时备份文件堆积。
            try:
                cls._persist_snapshot(copy.deepcopy(tolerant))
            except OSError:
                pass
            return tolerant

    @classmethod
    def _read_text_with_retry(cls, path: str) -> str | None:
        """按瞬态错误重试读取文本；持续失败时备份并记录原因。"""
        last_error: BaseException | None = None
        for attempt in range(cls._LOAD_RETRIES + 1):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError as exc:
                last_error = exc
                if attempt < cls._LOAD_RETRIES:
                    time.sleep(cls._LOAD_RETRY_DELAY_S)
            except UnicodeDecodeError as exc:
                last_error = exc
                break
        cls._note_load_failure(type(last_error).__name__ if last_error is not None else "Unknown")
        if path == cls._file_path and os.path.isfile(path):
            cls._backup_corrupt_file(path)
        return None

    @staticmethod
    def _parse_snapshot(raw: str, *, strict: bool) -> dict:
        """解析设备快照；strict 失败时按非严格模式只取第一个合法文档。"""
        if strict:
            content = yaml.safe_load(raw) or {}
        else:
            # 端点防护附加的扫描块常以 NUL 字节开始；先截断再按多文档解析，
            # 只采用第一个映射文档，忽略其余内容。
            text = raw.split("\x00", 1)[0]
            content = None
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict):
                    content = doc
                    break
            if content is None:
                raise ValueError("no YAML mapping document in device store")
        if not isinstance(content, dict):
            raise ValueError("device store is not a YAML mapping")
        return {
            str(device_id): copy.deepcopy(info)
            for device_id, info in content.items()
            if isinstance(info, dict)
        }

    @classmethod
    def _note_load_failure(cls, error_type: str) -> None:
        """记录加载失败原因；打包模式下也通过 UI 日志面板可见。"""
        message = f"DeviceStore 加载失败：{error_type}，已保留内存中的设备列表"
        try:
            LogService().log("WARNING", message)
        except Exception:
            pass
        LogService.write_developer_console("ERROR", message)

    @classmethod
    def save(cls):
        """在线程锁内保存当前设备快照。"""
        with cls._lock:
            cls._persist_snapshot(copy.deepcopy(cls._devices))

    @classmethod
    def _persist_snapshot(cls, snapshot: dict) -> None:
        """按瞬态错误重试一次原子写盘；仍失败时向调用方抛出。"""
        for attempt in range(cls._SAVE_RETRIES + 1):
            try:
                cls._write_snapshot_atomic(snapshot)
                return
            except OSError:
                if attempt < cls._SAVE_RETRIES:
                    time.sleep(cls._SAVE_RETRY_DELAY_S)
                else:
                    raise

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
                cls._persist_snapshot(copy.deepcopy(cls._devices))

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
