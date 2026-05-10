import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QThreadPool, Slot

from core.log_service import LogService
from core.mail.email_task import GetRandomEmailTask
from core.settings_manager import AppSettings
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_device import ADBDevice
from models.adb_testing import ADBTesting
from models.device_store import DeviceStore
from utils.resource_path import resource_path


class _ADBControllerBase:
    """Shared infrastructure for ADBController — models, signals, handler dispatch."""

    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.device_model = ADBDevice()
        self.app_model = ADBApp()
        self.testing_model = ADBTesting()
        self.advanced_model = ADBAdvanced()
        self.connected_devices_file = resource_path("resources/connected_devices.yaml")
        self.package_info = resource_path("resources/package_info.yaml")
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_ops = {}
        self._pending_lock = threading.Lock()
        self._connect_model_signals()
        self.last_save_dir = None
        self._active_viewers = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._batch_trackers = {}
        self._build_handler_map()

        try:
            DeviceStore.load()
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()

    def _connect_model_signals(self):
        self.device_model.command_finished.connect(self._handle_async_response)
        self.app_model.command_finished.connect(self._handle_async_response)
        self.testing_model.command_finished.connect(self._handle_async_response)
        self.advanced_model.command_finished.connect(self._handle_async_response)

    def _build_handler_map(self):
        self._handler_map = {}
        for klass in reversed(type(self).__mro__):
            registered = klass.__dict__.get("_handlers", {})
            for op_key, handler_name in registered.items():
                self._handler_map[op_key] = getattr(self, handler_name)

    def _generate_operation_id(self) -> str:
        return str(uuid.uuid4())

    @Slot(str, bool, str)
    def _emit_operation(self, operation: str, success: bool, message: str):
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return
        self.log_service.log(level, f"{message}")
        self.signals.operation_completed.emit(operation, success, message)

    def _handle_async_response(self, method_name: str, result):
        op_type = method_name.replace("_async", "")

        if isinstance(result, str) and result.startswith("AsyncError:"):
            error_msg = result[11:]
            self.log_service.log("ERROR", f"[{op_type}] {error_msg}")
            self._emit_operation(op_type, False, error_msg)
            return

        if op_type == "get_connected_devices":
            if isinstance(result, list):
                self._process_device_list(result)
            else:
                self._emit_operation(op_type, False, "Invalid device list format")
            return

        handler = self._handler_map.get(op_type)
        if handler:
            try:
                handler(result)
            except Exception as e:
                self.log_service.log("ERROR", f"[{op_type}] Handler error: {str(e)}")
                self._emit_operation(op_type, False, f"Handler error: {str(e)}")
        else:
            self._default_async_handler(op_type, result)

    def _default_async_handler(self, op_type: str, result):
        if isinstance(result, dict):
            if "ip" in result:
                self.signals.device_info_updated.emit(result["ip"], result)
            if result.get("success", False):
                self._emit_operation(op_type, True, f"{op_type} completed")
            else:
                error_msg = result.get("error", "Unknown error")
                self._emit_operation(op_type, False, error_msg)
        else:
            self._emit_operation(op_type, True, f"{op_type} completed")

    def _indent_output(self, text: str, prefix: str = "     ") -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines() if line.strip())

    def _get_screenshot_dir(self) -> str:
        if self.last_save_dir and os.path.exists(self.last_save_dir):
            return self.last_save_dir
        settings = AppSettings.instance()
        default_dir = settings.save_directory
        os.makedirs(default_dir, exist_ok=True)
        self.last_save_dir = default_dir
        return default_dir

    def get_random_email_and_code(self):
        task = GetRandomEmailTask()
        self._email_task = task
        task.signals.log_signal.connect(self.log_service.log)
        task.signals.email_updated.connect(self.signals.email_updated)
        task.signals.vercode_updated.connect(self.signals.vercode_updated)
        self.thread_pool.start(task)
