from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QTimer

from controllers._base import _ADBControllerBase
from core.log_service import LogService
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_device import ADBDevice
from models.device_store import DeviceStore


class ADBDeviceMixin(_ADBControllerBase):
    """Device connection, disconnection, restart, reboot, pairing."""

    # ── Provided by _ADBControllerBase ──
    device_model: ADBDevice
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _pending_ops: dict

    _handlers = {
        "connect_device": "_process_connect_device_result",
        "disconnect_device": "_process_disconnect_result",
        "get_device_info": "_process_device_info_result",
        "restart_device": "_process_restart_devices_result",
        "restart_adb": "_process_restart_adb_result",
        "reboot_mode": "_process_reboot_mode_result",
        "pair_device": "_process_pair_device_result",
        "tcpip_mode": "_process_tcpip_mode_result",
        "get_connected_devices": "_process_device_list",
    }

    def connect_device(self, ip: str):
        if not ip:
            self._emit_operation("connect", False, "⚠️ IP address cannot be empty")
            return
        self.device_model.connect_device_async(ip)

    def _process_connect_device_result(self, result):
        if isinstance(result, dict):
            ip = result.get("device_ip", "")
            raw = result.get("output") or result.get("error", "")
        else:
            ip = None
            raw = str(result)
            found_key = None
            with self._pending_lock:
                for key, (op_name, op_ip) in self._pending_ops.items():
                    if op_name == "connect":
                        ip = op_ip
                        found_key = key
                        break
                if found_key:
                    del self._pending_ops[found_key]
        if not ip:
            self._emit_operation("connect", False, "⚠️ Unknown device connection")
            return
        raw_lower = raw.lower()
        if "already connected" in raw_lower:
            self._emit_operation("connect", True, f"{ip} is already connected")
        elif "connected" in raw_lower:
            self._save_device_info(ip)
            self.refresh_devices()
            self._emit_operation("connect", True, f"Successfully connected to {ip}")
        else:
            self._emit_operation("connect", False, f"Connection failed: {raw}")

    def _process_device_list(self, devices: list):
        self._emit_operation("refresh", True, f"Found {len(devices)} connected devices")
        self.signals.devices_updated.emit(devices)
        self._async_update_devices(devices)

    def refresh_devices(self):
        operation_id = self._generate_operation_id()
        with self._pending_lock:
            self._pending_ops[operation_id] = ("refresh", None)
        try:
            self.device_model.get_connected_devices_async()
        except Exception as e:
            self._emit_operation("refresh", False, f"Failed to refresh devices: {str(e)}")
            self.signals.devices_updated.emit([])

    def _async_update_devices(self, devices: list):
        if not devices:
            return

        def _update():
            records = []
            for ip in devices:
                try:
                    info = ADBDevice.get_devices_basic_info(ip)
                    records.append(
                        {
                            "alias": f"device_{ip}",
                            "ip": ip,
                            "Brand": info.get("Brand", "Unknown"),
                            "Model": info.get("Model", "Unknown"),
                            "Aversion": info.get("Aversion", "Unknown"),
                        }
                    )
                except Exception:
                    pass
            if records:
                DeviceStore.upsert_devices(records)
                # 后台补全品牌/型号后再推一次列表，让占位行自动替换为真实信息。
                self.signals.devices_updated.emit(devices)

        self.executor.submit(_update)

    def _save_device_info(self, ip: str):
        try:
            info = ADBDevice.get_devices_basic_info(ip)
            DeviceStore.add_device(
                alias=f"device_{ip}",
                ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                android_version=info.get("Aversion", "Unknown"),
            )
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")

    def get_device_info(self, devices: list):
        if not devices:
            self._emit_operation("get_info", False, "Please select at least one device")
            return
        for ip in devices:
            self.device_model.get_device_info_async(ip)

    def _process_device_info_result(self, result: dict):
        device_ip = result.get("device_ip") or result.get("ip", "Unknown")
        log = self.log_service.log
        log("INFO", f"📱 Device Info - {device_ip}")
        log("INFO", f"  🧭 Model            : {result.get('Model', '-')}")
        log("INFO", f"  🏷️ Brand            : {result.get('Brand', '-')}")
        log("INFO", f"  🤖 Android Version  : {result.get('Android Version', '-')}")
        log("INFO", f"  🧪 SDK Version      : {result.get('SDK Version', '-')}")
        log("INFO", f"  🧬 CPU Architecture : {result.get('CPU Architecture', '-')}")
        log("INFO", f"  🔧 Hardware         : {result.get('Hardware', '-')}")
        log(
            "INFO",
            f"  🖼️ Resolution       : {result.get('Resolution', '-')}".replace(
                "Physical size: ", ""
            ),
        )
        log(
            "INFO",
            f"  🧮 Density          : {result.get('Density', '-')}".replace(
                "Physical density: ", ""
            ),
        )
        log("INFO", f"  🌐 Timezone         : {result.get('Timezone', '-')}")
        log("INFO", f"  🆔 Serial Number    : {result.get('Serial Number', '-')}")
        log("INFO", f"  💾 Total Memory     : {result.get('Total Memory', '-')}")
        log("INFO", f"  📉 Available Memory : {result.get('Available Memory', '-')}")
        log("INFO", "  📂 Storage          :")
        for line in result.get("Storage", "").splitlines():
            log("INFO", f"    {line}")
        log("INFO", "  📡 MAC / IP Info    :")
        for line in result.get("Mac", "").splitlines():
            log("INFO", f"    {line}")
        log("INFO", "  ✅ complete\n")

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
        ip = result.get("device_ip") or result.get("ip", "unknown device")
        if result.get("success"):
            QTimer.singleShot(
                10_000,
                lambda: (
                    self.refresh_devices(),
                    self._emit_operation(
                        "restart", True, f"{ip} Restart completed, device list refreshed"
                    ),
                ),
            )
            self._emit_operation("restart", True, f"{ip} Restarting in progress...")
        else:
            self._emit_operation(
                "restart", False, f"{ip} Restart failed: {result.get('error', 'unknown device')}"
            )

    def restart_adb(self):
        self.device_model.restart_adb_async()

    def _process_restart_adb_result(self, result: dict):
        if result.get("success"):
            QTimer.singleShot(3000, self.refresh_devices)
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
        ip = result.get("device_ip", "unknown")
        mode = result.get("mode", "?")
        if result.get("success"):
            QTimer.singleShot(10_000, self.refresh_devices)
            self._emit_operation("reboot_mode", True, f"{ip} rebooting to {mode}...")
        else:
            self._emit_operation(
                "reboot_mode", False, f"{ip} reboot failed: {result.get('error', '')}"
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
