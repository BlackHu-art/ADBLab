"""提供设备连接、重启、配对和基础信息查询的控制能力。"""

from __future__ import annotations

import threading
from _thread import LockType
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PySide6.QtCore import QTimer

from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogService
from models.adb_advanced import ADBAdvanced
from models.adb_device import ADBDevice
from models.device_store import DeviceStore
from utils.adb_targets import normalize_adb_connect_target


@dataclass
class _OverviewRefresh:
    """控制器拥有的单批查询身份；同拓扑请求只保留一个后续刷新意图。"""

    generation: int
    topology: tuple[str, ...]
    pending: bool = False


class ADBDeviceMixin(_ADBControllerBase):
    """协调设备连接、断开、重启、配对和基础信息持久化。"""

    # 以下属性由 _ADBControllerBase 提供。
    device_model: ADBDevice
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    _overview_refresh: _OverviewRefresh | None = None
    _overview_store_lock: LockType | None = None
    log_service: LogService
    executor: ThreadPoolExecutor

    _handlers = {
        "connect_device": "_process_connect_device_result",
        "disconnect_device": "_process_disconnect_result",
        "restart_device": "_process_restart_devices_result",
        "restart_adb": "_process_restart_adb_result",
        "reboot_mode": "_process_reboot_mode_result",
        "pair_device": "_process_pair_device_result",
        "tcpip_mode": "_process_tcpip_mode_result",
        "get_connected_devices": "_process_device_list",
    }

    def connect_device(self, ip: str):
        target, error = normalize_adb_connect_target(ip)
        if error:
            self._emit_operation("connect", False, error)
            return
        self.device_model.connect_device_async(target)

    def _process_connect_device_result(self, result):
        if isinstance(result, dict):
            ip = result.get("device_ip", "")
            raw = result.get("output") or result.get("error", "")
        else:
            ip = None
            raw = str(result)
        if not ip:
            self._emit_operation("connect", False, "⚠️ Unknown device connection")
            return
        raw_lower = raw.lower()
        if "already connected" in raw_lower:
            self._finalize_connected_device(ip, f"{ip} is already connected")
        elif "connected" in raw_lower:
            self._finalize_connected_device(ip, f"Successfully connected to {ip}")
        else:
            self._emit_operation("connect", False, f"Connection failed: {raw}")

    def _finalize_connected_device(self, ip: str, message: str):
        # 设备信息查询（getprop）与 DeviceStore 落盘放到 executor，避免阻塞 GUI 线程。
        self.executor.submit(self._save_device_info, ip)
        self.refresh_devices()
        self._emit_operation("connect", True, message)

    def _process_device_list(self, devices: list):
        devices = list(dict.fromkeys(devices or []))
        topology = tuple(devices)
        with self._device_topology_lock:
            if topology != self._device_topology:
                self._device_topology_generation += 1
                self._device_topology = topology
            generation = self._device_topology_generation
        self._emit_operation("refresh", True, f"Found {len(devices)} connected devices")
        self.signals.devices_updated.emit(devices)
        self._async_update_devices(devices, generation=generation)

    def publish_detected_devices(self, devices: list[str]):
        self._process_device_list(list(devices or []))

    def refresh_devices(self):
        if getattr(self, "_shutting_down", False):
            return
        try:
            self.device_model.get_connected_devices_async()
        except Exception as e:
            self._emit_operation("refresh", False, f"Failed to refresh devices: {str(e)}")

    def _async_update_devices(self, devices: list, *, generation: int):
        """逐台发布当前拓扑的概览快照，最后统一落盘；旧代次与关闭后的结果不发布。"""
        if not devices:
            return

        topology = tuple(devices)
        with self._device_topology_lock:
            if (
                getattr(self, "_shutting_down", False)
                or generation != self._device_topology_generation
                or topology != self._device_topology
            ):
                return
            active = self._overview_refresh
            if active is not None and (
                active.generation, active.topology
            ) == (generation, topology):
                active.pending = True
                return
            refresh = _OverviewRefresh(generation, topology)
            self._overview_refresh = refresh
            if self._overview_store_lock is None:
                self._overview_store_lock = threading.Lock()
            store_lock = self._overview_store_lock

        def _is_current_topology() -> bool:
            if getattr(self, "_shutting_down", False):
                return False
            with self._device_topology_lock:
                return (
                    self._overview_refresh is refresh
                    and generation == self._device_topology_generation
                    and topology == self._device_topology
                )

        def _update_batch():
            records = []
            for ip in devices:
                if not _is_current_topology():
                    return
                try:
                    info = ADBDevice.get_device_overview_info(
                        ip, cancelled=lambda: not _is_current_topology(),
                    )
                    record = {
                        **info,
                        "alias": f"device_{ip}",
                        "ip": ip,
                        "Brand": info.get("Brand", "Unknown"),
                        "Model": info.get("Model", "Unknown"),
                        "Aversion": info.get("Aversion", "Unknown"),
                        "SDK Version": info.get("SDK Version", ""),
                        "CPU Architecture": info.get("CPU Architecture", ""),
                        "Hardware": info.get("Hardware", ""),
                    }
                    records.append(record)
                except Exception:
                    record = {}
                    self.log_service.log(
                        "WARNING", "设备概览属性读取失败，将清除本轮缺失的动态指标",
                    )
                if not _is_current_topology():
                    return
                # 已完成的设备不等待后续查询；扩展字段仅在窗口内存中展示。
                self.signals.device_info_updated.emit(ip, record)
            if records:
                # 设备属性查询可能持续数秒；拓扑已变化时旧结果不得再写盘或刷新 UI，
                # 否则已离线设备会被晚到的补全任务重新显示。
                if not _is_current_topology():
                    return
                try:
                    # 只在后台串行写盘；取得写锁后重查代次，旧结果不能追写覆盖新批次。
                    with store_lock:
                        if not _is_current_topology():
                            return
                        DeviceStore.upsert_devices(records)
                except Exception as e:
                    self.log_service.log("ERROR", f"DeviceStore write failed: {str(e)}")
                    return
                # 后台补全品牌/型号后再推一次列表，让占位行自动替换为真实信息。
                if _is_current_topology():
                    self.signals.devices_updated.emit(devices)

        def _update():
            try:
                while _is_current_topology():
                    _update_batch()
                    with self._device_topology_lock:
                        if self._overview_refresh is not refresh:
                            return
                        if not refresh.pending or getattr(self, "_shutting_down", False):
                            self._overview_refresh = None
                            return
                        refresh.pending = False
            finally:
                with self._device_topology_lock:
                    if self._overview_refresh is refresh:
                        self._overview_refresh = None

        try:
            self.executor.submit(_update)
        except RuntimeError:
            with self._device_topology_lock:
                if self._overview_refresh is refresh:
                    self._overview_refresh = None
            raise

    def _save_device_info(self, ip: str):
        if getattr(self, "_shutting_down", False):
            return
        try:
            info = ADBDevice.get_devices_basic_info(
                ip, cancelled=lambda: getattr(self, "_shutting_down", False),
            )
            if getattr(self, "_shutting_down", False):
                return
            DeviceStore.add_device(
                alias=f"device_{ip}",
                ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                android_version=info.get("Aversion", "Unknown"),
            )
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")

    def disconnect_devices(self, devices: list):
        if not self._require_devices(devices, "disconnect"):
            return
        for ip in devices:
            self.device_model.disconnect_device_async(ip)

    def _process_disconnect_result(self, result: dict):
        ip = result.get("device_ip") or result.get("ip", "unknown")
        if result.get("success"):
            self.refresh_devices()
            self._emit_operation("disconnect", True, f"Successfully disconnected {ip}")
        else:
            self._emit_operation(
                "disconnect", False, f"Disconnect failed: {result.get('error', 'unknown error')}"
            )

    def restart_devices(self, devices: list):
        if not self._require_devices(devices, "restart"):
            return
        for ip in devices:
            self.device_model.restart_device_async(ip)

    def _process_restart_devices_result(self, result: dict):
        """报告重启命令的提交结果；延迟刷新只更新设备列表，不推断设备启动完成。"""
        ip = result.get("device_ip") or result.get("ip", "unknown device")
        if result.get("requires_refresh", result.get("success", False)):
            QTimer.singleShot(10_000, self.signals, self.refresh_devices)
        if result.get("success"):
            self._emit_operation(
                "restart", True,
                f"{ip} Reboot request submitted; device startup has not been verified",
            )
        else:
            self._emit_operation(
                "restart", False, f"{ip} {result.get('error', 'Restart failed: unknown device')}"
            )

    def restart_adb(self):
        self.device_model.restart_adb_async()

    def _process_restart_adb_result(self, result: dict):
        if result.get("success"):
            # 重启后既有连接与能力状态都已失效，先通知运行时重测再安排刷新。
            owner = getattr(self, "window_owner", None)
            notify = getattr(owner, "note_adb_server_restarted", None)
            if callable(notify):
                notify()
            QTimer.singleShot(3000, self.signals, self.refresh_devices)
            self._emit_operation(
                "restart_adb",
                True,
                f"ADB service has been restarted: {result.get('raw_output', '')}",
            )
        else:
            self._emit_operation(
                "restart_adb", False, f"ADB restart failed: {result.get('error', 'unknown error')}"
            )

    def reboot_mode(self, devices: list, mode: str):
        if not self._require_devices(devices, "reboot_mode"):
            return
        for ip in devices:
            self.advanced_model.reboot_mode_async(ip, mode)

    def _process_reboot_mode_result(self, result: dict):
        """报告模式重启提交或未知状态；延迟刷新不证明设备已完成启动。"""
        ip = result.get("device_ip", "unknown")
        mode = result.get("mode", "?")
        if result.get("requires_refresh", result.get("success", False)):
            QTimer.singleShot(10_000, self.signals, self.refresh_devices)
        if result.get("success"):
            self._emit_operation(
                "reboot_mode", True,
                f"{ip} Reboot request submitted for {mode}; device startup has not been verified",
            )
        else:
            self._emit_operation(
                "reboot_mode", False, f"{ip} {result.get('error', 'Reboot failed')}"
            )

    def pair_device(self, ip: str, port: str, pairing_code: str):
        if not ip:
            self._emit_operation("pair_device", False, "⚠️ IP address cannot be empty")
            return
        self.advanced_model.pair_device_async(ip, port, pairing_code)

    def _process_pair_device_result(self, result: dict):
        ip = result.get("ip", "")
        if result.get("success"):
            self._emit_operation(
                "pair_device", True, f"Paired with {ip}: {result.get('output', '')}"
            )
        else:
            self._emit_operation("pair_device", False, f"Pairing failed: {result.get('error')}")

    def tcpip_mode(self, devices: list, port: str = "5555"):
        if not self._require_devices(devices, "tcpip_mode"):
            return
        for ip in devices:
            self.advanced_model.tcpip_mode_async(ip, port)

    def _process_tcpip_mode_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "tcpip_mode", True, f"ADB over TCP/IP enabled on {ip}:{result.get('port')}"
            )
        else:
            self._emit_operation(
                "tcpip_mode", False, f"TCP/IP mode failed on {ip}: {result.get('error')}"
            )
