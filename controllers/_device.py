"""提供设备连接、重启、配对和基础信息查询的控制能力。"""

from __future__ import annotations

import threading
from _thread import LockType
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogService
from models.adb_advanced import ADBAdvanced
from models.adb_device import ADBDevice
from models.device_store import DeviceStore
from utils.adb_targets import normalize_adb_connect_target

if TYPE_CHECKING:
    from services.adb_pairing import PairingOutcome


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
    _overview_query_slots: threading.BoundedSemaphore | None = None
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

    def accept_wireless_connection(self, outcome: PairingOutcome) -> None:
        """只接纳当前配对协调器核实的结果；历史使用缓存，成功反馈归连接窗口。

        在线 transport 与连接端点分别使用；后台写入前重查环境及关闭状态，不为历史
        追加 ADB 查询。已开始的存储 I/O 自然完成，历史保存失败不撤销已核实连接。
        """
        owner = getattr(self, "window_owner", None)
        pairing = getattr(owner, "_adb_pairing", None)
        accepts = getattr(pairing, "accepts_outcome", None)
        if (
            getattr(self, "_shutting_down", False)
            or getattr(owner, "_closing", False)
            or not callable(accepts)
            or not accepts(outcome)
        ):
            return
        revision = outcome.context_revision

        def _is_current() -> bool:
            # 后台只读取生命周期代次，不调用 Qt 对象的方法或读取控件。
            return bool(
                not getattr(self, "_shutting_down", False)
                and self.window_owner is owner
                and not getattr(owner, "_closing", False)
                and getattr(owner, "_adb_pairing", None) is pairing
                and getattr(pairing, "context_revision", None) == revision
            )

        if not _is_current():
            return
        self.refresh_devices()
        endpoint, error = normalize_adb_connect_target(outcome.connection_endpoint)
        if error:
            return
        device_id = outcome.device_id
        if self._overview_store_lock is None:
            self._overview_store_lock = threading.Lock()
        store_lock = self._overview_store_lock

        def _save_history() -> None:
            if not _is_current():
                return
            try:
                # 与现有概览写入串行，在获得锁后读取最新缓存并再次核对会话。
                with store_lock:
                    if not _is_current():
                        return
                    records = DeviceStore.get_all()
                    live = next((
                        info for _alias, info in records
                        if isinstance(info, dict) and info.get("ip") == device_id
                    ), {})
                    alias, saved = next((
                        (alias, info) for alias, info in records
                        if isinstance(info, dict) and normalize_adb_connect_target(
                            str(info.get("ip", "")),
                        ) == (endpoint, "")
                    ), (f"device_{endpoint}", {}))

                    def _field(key: str, default: str) -> str:
                        for info in (live, saved):
                            value = info.get(key)
                            if isinstance(value, str) and value.strip().casefold() not in (
                                "", "unknown",
                            ):
                                return value
                        return default

                    if not _is_current():
                        return
                    DeviceStore.add_device(
                        alias=alias, ip=endpoint,
                        brand=_field("Brand", "Unknown"), model=_field("Model", "Unknown"),
                        android_version=_field("Aversion", ""),
                    )
            except Exception:
                # 存储异常可能包含路径或设备信息，不把异常正文送入诊断或用户提示。
                self.log_service.log("WARNING", "无线连接已确认，但连接历史保存失败")

        try:
            self.executor.submit(_save_history)
        except RuntimeError:
            if _is_current():
                self.log_service.log("WARNING", "无线连接已确认，但连接历史未能安排保存")

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

    def publish_detected_devices(
        self, devices: list[str], *, discovery_token: tuple[int, int] | None = None,
    ):
        """仅接纳最新发现区间捕获的扫描，阻止防抖和信号队列中的旧快照回退拓扑。"""
        if getattr(self, "_shutting_down", False):
            return
        if discovery_token is not None:
            current = self.device_discovery_token()
            if discovery_token != current or current[1]:
                return
        self._process_device_list(list(devices or []))

    def refresh_devices(self):
        if getattr(self, "_shutting_down", False):
            return
        with self._device_topology_lock:
            self._discovery_generation = getattr(self, "_discovery_generation", 0) + 1
            self._discovery_refresh_pending = getattr(self, "_discovery_refresh_pending", 0) + 1
            generation = self._discovery_generation
        try:
            self.device_model.get_connected_devices_async()
        except Exception as e:
            # async_command 可能先同步发出失败结果再抛出；同次提交只能收口一次。
            if self.device_discovery_token()[0] == generation:
                self._finish_device_discovery()
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
            if self._overview_query_slots is None:
                self._overview_query_slots = threading.BoundedSemaphore(3)
            query_slots = self._overview_query_slots

        def _is_current_topology() -> bool:
            if getattr(self, "_shutting_down", False):
                return False
            with self._device_topology_lock:
                return (
                    self._overview_refresh is refresh
                    and generation == self._device_topology_generation
                    and topology == self._device_topology
                )

        def _query_device(ip):
            # 旧拓扑尚在退出时仍共享命令额度；等待额度期间也响应取消。
            while not query_slots.acquire(timeout=0.05):
                if not _is_current_topology():
                    return None
            try:
                if not _is_current_topology():
                    return None
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
                except Exception:
                    record = {}
                    self.log_service.log(
                        "WARNING", "设备概览属性读取失败，将清除本轮缺失的动态指标",
                    )
                return record
            finally:
                query_slots.release()

        def _update_batch():
            records_by_device = {}
            # 子池由当前 Controller 任务拥有；退出上下文先收口查询，再结束监督中的父任务。
            with ThreadPoolExecutor(
                max_workers=min(3, len(devices)), thread_name_prefix="adblab-overview",
            ) as queries:
                pending = {queries.submit(_query_device, ip): ip for ip in devices}
                try:
                    for future in as_completed(pending):
                        if not _is_current_topology():
                            return
                        ip = pending[future]
                        record = future.result()
                        if record is None or not _is_current_topology():
                            return
                        if record:
                            records_by_device[ip] = record
                        # 先完成的设备立即发布，不受前面慢设备的查询顺序阻挡。
                        self.signals.device_info_updated.emit(ip, record)
                finally:
                    for future in pending:
                        future.cancel()
            records = [records_by_device[ip] for ip in devices if ip in records_by_device]
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
        """提交重启前撤销无线配对上下文，失败重启也不能继续旧会话。"""
        owner = getattr(self, "window_owner", None)
        invalidate = getattr(owner, "invalidate_wireless_pairing", None)
        if callable(invalidate):
            invalidate("server_restart")
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
