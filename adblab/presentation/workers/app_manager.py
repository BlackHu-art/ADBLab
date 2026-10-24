"""在 QThread 中执行应用列表、管理、备份和恢复操作。"""

import threading
from time import monotonic
from typing import Literal, cast

from PySide6.QtCore import QCoreApplication, QThread, Signal

from core.adb_query import query_timeout
from core.exec import CommandRunner
from services.app_data_errors import CLEAR_DATA_PERMISSION_MESSAGE
from services.app_icons import load_app_icons
from services.app_metadata import AppMetadata, load_app_metadata
from services.app_permissions import parse_package_permissions
from services.apps import actions, archives, queries
from services.apps.package_details import (
    PackageDetail,
    parse_app_details,
    parse_batch_detail,
)


class AppManagerWorker(QThread):
    """在界面线程外执行应用管理 ADB 操作，并通过信号返回结果。

    只读查询支持执行中取消；写操作保留阶段间中断及必要清理契约。命令失败通过已有日志或
    完成信号传播，禁止后台线程直接访问界面对象。
    """

    log_message = Signal(str)
    user_context_loaded = Signal(int)
    apps_loaded = Signal(list)
    app_details_loaded = Signal(dict)
    app_detail_batch = Signal(str, str, str, str)
    app_metadata_loaded = Signal(dict)
    app_icon_loaded = Signal(str, bytes, str)
    permissions_loaded = Signal(list, list, list)
    backup_progress = Signal(str, str)
    operation_done = Signal(str)
    operation_feedback = Signal(str, str)

    def __init__(self, device_ip: str, operation: str, *, user_id: int | None = None, **kwargs):
        super().__init__()
        self.device_ip = device_ip
        self.operation = operation
        self.user_id = user_id
        self.kwargs = kwargs
        self._aborted = threading.Event()
        self.operation_done.connect(self._report_success)

    def _report_success(self, action: str) -> None:
        """保留原完成信号的刷新用途，额外提供明确的用户反馈级别。"""
        self.operation_feedback.emit("success", f"{action}: {self.kwargs.get('package_name', '')}")

    def _report_failure(self, message: str) -> None:
        """保留日志消费者，同时以结构化失败通知界面，禁止解析日志文字判定级别。"""
        self.log_message.emit(message)
        self.operation_feedback.emit("error", message)

    def abort(self):
        """取消在途只读查询；写操作仍在原有阶段边界处理停止意图。"""
        self._aborted.set()
        self.requestInterruption()

    def _cancelled(self) -> bool:
        """统一读取任务和监督器的停止意图，供执行层及结果发布前检查。"""
        return self._aborted.is_set() or self.isInterruptionRequested()

    def run(self):
        """按 operation 分派后台操作；未知操作不执行任何任务。"""
        if self._aborted.is_set() or self.isInterruptionRequested():
            return
        ops = {
            "load_apps": self._load_apps,
            "load_detail_batch": lambda: self._load_detail_batch(self.kwargs.get("packages", [])),
            "load_metadata_batch": lambda: self._load_metadata_batch(
                self.kwargs.get("packages", []),
            ),
            "load_icon_batch": self._load_icon_batch,
            "app_details": lambda: self._fetch_app_details(self.kwargs.get("package_name")),
            "app_snapshot": lambda: self._fetch_app_snapshot(self.kwargs.get("package_name")),
            "permissions": lambda: self._fetch_permissions(self.kwargs.get("package_name")),
            "modify_app": lambda: self._modify_app(
                self.kwargs.get("action"), self.kwargs.get("package_name")
            ),
            "backup_app": lambda: self._backup_app(
                self.kwargs.get("package_name"), self.kwargs.get("save_dir")
            ),
            "restore_apps": lambda: self._restore_apps(self.kwargs.get("file_paths", [])),
            "modify_permission": lambda: self._modify_permission(
                self.kwargs.get("package_name"),
                self.kwargs.get("permission"),
                self.kwargs.get("action"),
            ),
            "launch_app": lambda: self._launch_app(self.kwargs.get("package_name")),
            "clear_app": lambda: self._clear_app(self.kwargs.get("package_name")),
        }
        f = ops.get(self.operation)
        if f:
            writes = {"modify_app", "modify_permission", "launch_app", "clear_app",
                      "backup_app", "restore_apps"}
            try:
                queries.validate_loaded_user(self.user_id, required=self.operation in writes)
            except queries.QueryError as error:
                self._report_failure(str(error))
                return
            # helper 在响应中携带用户身份；批量文字兼容查询仅读取包级元数据。
            # 其余查询和写入先核对快照用户，写命令仍显式指定，避免检查后的切换重定向目标。
            if self.operation not in {
                "load_metadata_batch", "load_icon_batch", "load_detail_batch",
            }:
                if not self._bind_current_user():
                    return
            f()

    def _read_current_user(self) -> int | None:
        """可取消地读取具体用户编号；失败或未知输出绝不猜测系统用户 0。"""
        return queries.read_current_user(
            execute=self._adb, cancelled=self._cancelled,
            timeout=query_timeout(self.device_ip, 5),
        )

    def _bind_current_user(self) -> bool:
        """首次读取固定用户；已绑定任务在用户变化时拒绝继续，不自动改绑。"""
        try:
            current = queries.bind_current_user(
                self.user_id, read_user=self._read_current_user, cancelled=self._cancelled,
            )
        except queries.QueryError as error:
            self._report_failure(str(error))
            return False
        if current is None:
            return False
        self.user_id = current
        return True

    def _adb(self, *args, timeout: float = 30, cancellable: bool = False):
        """仅显式只读调用传递取消，避免写操作或必要清理被一并中断。"""
        cmd = ["adb", "-s", self.device_ip] + list(args)
        if cancellable:
            return CommandRunner.run(cmd, timeout=timeout, cancelled=self._cancelled)
        return CommandRunner.run(cmd, timeout=timeout)

    def _load_apps(self):
        self.log_message.emit("Fetching installed apps...")
        try:
            try:
                apps = queries.load_installed_apps(
                    cast(int, self.user_id), execute=self._adb, cancelled=self._cancelled,
                )
            except queries.QueryError as error:
                self._report_failure(str(error))
                return
            if apps is None:
                return
            self.log_message.emit(f"Loaded {len(apps)} apps.")
            if not self._cancelled():
                self.user_context_loaded.emit(self.user_id)
                self.apps_loaded.emit(apps)
        except Exception as e:
            self._report_failure(f"Error: {e}")

    def _load_icon_batch(self):
        """把页面已验证的身份交给服务核对，禁止将另一版本的像素记入当前缓存。"""
        options = {}
        if "expected_fingerprints" in self.kwargs:
            options["expected_fingerprints"] = self.kwargs["expected_fingerprints"]
        if self.user_id is not None:
            options["expected_user_id"] = self.user_id
        load_app_icons(
            self.device_ip, self.kwargs.get("packages", []), self._cancelled,
            self.app_icon_loaded.emit, **options,
        )

    def _load_metadata_batch(self, packages):
        """由查询服务完成 helper 与兼容事务，保留调用时的执行与时钟替换接缝。"""
        queries.load_metadata_with_fallback(
            self.device_ip, packages, expected_user=self.user_id, execute=self._adb,
            cancelled=self._cancelled, query_budget=lambda: query_timeout(self.device_ip, 5),
            clock=monotonic, metadata_loader=load_app_metadata,
            on_metadata=self._publish_metadata, on_detail=self._publish_package_detail,
            log=self.log_message.emit, failure=self._report_failure,
        )

    def _publish_metadata(self, item: AppMetadata) -> None:
        """将服务已准入的元数据映射为既有五字段载荷，不再改变取消时序。"""
        self.app_metadata_loaded.emit({
            "package": item.package,
            "label": item.label,
            "version": item.version,
            "installed": item.installed,
            "fingerprint": item.fingerprint,
        })

    def _load_detail_batch(self, packages, *, deadline: float | None = None):
        """批量及解析兼容查询交给同一服务，外来截止时间不重建预算。"""
        queries.load_package_details(
            packages, deadline=deadline, execute=self._adb, cancelled=self._cancelled,
            query_budget=lambda: query_timeout(self.device_ip, 5), clock=monotonic,
            on_detail=self._publish_package_detail, log=self.log_message.emit,
        )

    def _publish_package_detail(self, detail: PackageDetail) -> None:
        """交付服务在原解析前门禁准入的记录，载荷保持原四个字段。"""
        self.app_detail_batch.emit(*detail)

    def _emit_package_detail(self, pkg: str, out: str):
        if self._cancelled():
            return
        self.app_detail_batch.emit(*parse_batch_detail(pkg, out))

    def _fetch_app_details(self, pkg):
        out = self._read_package_snapshot(pkg, "details")
        if out is not None:
            self._emit_app_details(pkg, out)

    def _fetch_app_snapshot(self, pkg):
        """详情首载共用同一次设备快照，分别发布既有详情与权限结果。"""
        out = self._read_package_snapshot(pkg, "details")
        if out is not None:
            self._emit_app_details(pkg, out)
            self._emit_permissions(out)

    def _read_package_snapshot(self, pkg, part: Literal["details", "permissions"]) -> str | None:
        """查询服务验证成功后先发布用户；后续详情和权限仍各有取消门禁。"""
        try:
            output = queries.read_package_snapshot(
                pkg, part, execute=self._adb, cancelled=self._cancelled,
            )
        except queries.QueryError as error:
            self._report_failure(str(error))
            return None
        if output is None:
            return None
        self.user_context_loaded.emit(self.user_id)
        return output

    def _emit_app_details(self, pkg, out: str) -> None:
        details = parse_app_details(pkg, out)
        if self._cancelled():
            return
        self.app_details_loaded.emit(details)

    def _fetch_permissions(self, pkg):
        out = self._read_package_snapshot(pkg, "permissions")
        if out is not None:
            self._emit_permissions(out)

    def _emit_permissions(self, out: str) -> None:
        if self.user_id is None:
            return
        declared, requested, runtime = parse_package_permissions(out, self.user_id)
        if not self._cancelled():
            self.permissions_loaded.emit(declared, requested, runtime)

    def _modify_app(self, action, pkg):
        """将动作和同步信号交给服务，用户准入仍由 run 负责。"""
        actions.modify_app(
            action, pkg, cast(int, self.user_id), execute=self._adb,
            log=self.log_message.emit, failure=self._report_failure,
            feedback=self.operation_feedback.emit, completed=self.operation_done.emit,
        )

    def _launch_app(self, pkg):
        """沿用已绑定用户与原信号，服务负责单次启动事务。"""
        actions.launch_app(
            pkg, cast(int, self.user_id), execute=self._adb,
            log=self.log_message.emit, failure=self._report_failure,
            completed=self.operation_done.emit,
        )

    def _clear_app(self, pkg):
        """仅在服务识别权限拒绝时才翻译用户提示。"""
        actions.clear_app(
            pkg, cast(int, self.user_id), execute=self._adb,
            log=self.log_message.emit, failure=self._report_failure,
            permission_denied=self._report_clear_permission_denied,
            completed=self.operation_done.emit,
        )

    def _report_clear_permission_denied(self) -> None:
        """在原拒绝路径中延迟翻译并发布可操作提示。"""
        self.operation_feedback.emit(
            "error", QCoreApplication.translate("ADBLab", CLEAR_DATA_PERMISSION_MESSAGE),
        )

    def _modify_permission(self, pkg, perm, action):
        """向权限服务传递已绑定用户，不复制设备准入策略。"""
        actions.modify_permission(
            pkg, perm, action, cast(int, self.user_id), execute=self._adb,
            log=self.log_message.emit, failure=self._report_failure,
            completed=self.operation_done.emit,
        )

    def _backup_app(self, pkg, save_dir):
        """由归档服务持有暂存事务，保留执行与取消的实例替换接缝。"""
        archives.backup_app(
            pkg, save_dir, cast(int, self.user_id), execute=self._adb,
            cancelled=self._cancelled, progress=self.backup_progress.emit,
            log=self.log_message.emit, feedback=self.operation_feedback.emit,
            failure=self._report_failure, completed=self.operation_done.emit,
        )

    def _restore_apps(self, files):
        """恢复服务每次写入前经 adapter 复核原固定用户。"""
        archives.restore_apps(
            files, execute=self._adb, cancelled=self._cancelled,
            confirm_user=self._restore_target_user, log=self.log_message.emit,
            feedback=self.operation_feedback.emit, failure=self._report_failure,
            completed=self.operation_done.emit,
        )

    def _restore_target_user(self) -> int | None:
        """复核失败直接停止；成功后读取当时用户，用户 0 仍为合法目标。"""
        if not self._bind_current_user():
            return None
        return cast(int, self.user_id)
