"""分派 CLI 子模式并启动 ADBLab 图形界面。"""

import argparse
import ctypes
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from time import perf_counter

from utils.app_metadata import APP_NAME, APP_VERSION, app_major_minor_version
from utils.resource_path import resource_path, setup_qt_search_paths
from utils.user_data import user_data_root

_ENTRY_STARTED_AT = perf_counter()


def windows_app_user_model_id() -> str:
    """生成随主次版本变化的 Windows AppUserModelID。"""
    return f"ADBLab.Frankie.{app_major_minor_version()}"


def _dispatch_cli(argv: list[str]) -> int | None:
    """分派已知 CLI 子模式；未命中时返回 None 以继续启动 GUI。"""
    if not argv:
        return None
    if argv[0] == "--adblab-native-launch":
        from core.native_launcher import launch

        return launch(argv[1:])
    if argv[0] == "--mobileperf-worker":
        return _run_mobileperf_worker(argv[1:])
    if argv[0] == "--startup-splash":
        parser = argparse.ArgumentParser(description="Run ADBLab startup splash")
        parser.add_argument("server_name")
        args = parser.parse_args(argv[1:])
        from gui.startup_worker import run_startup_splash

        return run_startup_splash(args.server_name)
    if argv[0] == "--self-check":
        return _run_self_check(argv[1:])
    return None


def _run_mobileperf_worker(argv: list[str]) -> int:
    """在隔离子进程中运行 MobilePerf 采集内核。"""
    from core.worker_stdio import prepare_worker_stdio

    prepare_worker_stdio()
    parser = argparse.ArgumentParser(description="Run mobileperf collection")
    parser.add_argument("--config", default=None, help="Path to mobileperf config file")
    args = parser.parse_args(argv)

    from mobileperf.android.startup import StartUp

    startup = StartUp(config_path=args.config)
    startup.run()
    return 0


def _run_self_check(argv: list[str]) -> int:
    """分派资源检查或最小 GUI 探针，不加载主窗口及设备业务。"""
    parser = argparse.ArgumentParser(description="Run ADBLab self checks")
    parser.add_argument("target", choices=["packaging", "gui"])
    args = parser.parse_args(argv)
    if args.target == "packaging":
        return _self_check_packaging()
    return _self_check_gui()


def _self_check_gui() -> int:
    """在独立进程验证真实 QPA 插件与事件循环；由调用方提供显示环境和超时。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("ADBLab GUI self-check")
    window.resize(320, 160)
    window.show()
    QTimer.singleShot(100, app.quit)
    return app.exec()


def _self_check_packaging() -> int:
    """验证打包所需依赖、资源和用户数据目录的基本可用性。"""
    os.environ.setdefault("MOBILEPERF_LOG_DIR", str(user_data_root() / "logs"))
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    def importable(module_name: str) -> None:
        try:
            if module_name == "qfluentwidgets":
                _load_fluent_widgets()
            else:
                __import__(module_name)
            check(f"import:{module_name}", True)
        except Exception as exc:
            check(f"import:{module_name}", False, str(exc))

    importable("PySide6")
    importable("PySide6.QtNetwork")
    importable("segno")
    importable("qfluentwidgets")
    importable("mobileperf.android.startup")
    importable("gui.generated.translations_rc")

    # Fluent 会吞掉图像依赖的导入失败；主包可导入仍可能让覆盖菜单退回实色。
    try:
        from qfluentwidgets.components.widgets.acrylic_label import isAcrylicAvailable

        check(
            "ui:acrylic", isAcrylicAvailable,
            "" if isAcrylicAvailable else "Acrylic image dependencies unavailable",
        )
    except (ImportError, OSError) as exc:
        check("ui:acrylic", False, type(exc).__name__)

    from PySide6.QtCore import QCoreApplication, QFile, QTranslator
    from PySide6.QtGui import QImage

    # TLS 插件发现需要 Qt 应用对象；自检只加载后端，不访问更新服务。
    _tls_application = QCoreApplication.instance() or QCoreApplication([])
    try:
        from PySide6.QtNetwork import QSslSocket

        check("network:tls_backend", QSslSocket.supportsSsl())
    except ImportError as exc:
        check("network:tls_backend", False, str(exc))

    for locale in ("zh_CN", "en_US", "zh_HK"):
        translation = f":/adblab/i18n/adblab.{locale}.qm"
        loaded = QFile.exists(translation) and QTranslator().load(translation)
        check(
            f"resource:i18n/{locale}",
            loaded,
            "" if loaded else "translation catalog cannot be loaded",
        )

    check("resource:icon.ico", Path(resource_path("icon.ico")).is_file())
    check("resource:resources", Path(resource_path("resources")).is_dir())
    for relative_path in (
        "resources/icons",
        "resources/icons/LICENSE.txt",
        "resources/images/gallery_header.png",
        "resources/app-icon.png",
        "resources/app_settings.json",
        "resources/connected_devices.yaml",
        "resources/chkbugreport-0.5-215.jar",
        "resources/app-icon-helper.jar",
        "resources/ZFB.jpg",
    ):
        resolved = Path(resource_path(relative_path))
        check(
            f"resource:{relative_path}",
            (
                resolved.is_dir()
                if relative_path == "resources/icons"
                else resolved.is_file()
            ),
        )
    check("image:startup-icon", not QImage(resource_path("resources/app-icon.png")).isNull())
    # 用无秘密的样例验证二维码写出器被完整收集，不发起配对或 ADB 连接。
    try:
        import io

        import segno

        qr_buffer = io.BytesIO()
        segno.make_qr("ADBLab packaging check").save(qr_buffer, kind="png", border=4)
        check("image:pairing-qr", not QImage.fromData(qr_buffer.getvalue()).isNull())
    except (ImportError, OSError, ValueError) as exc:
        check("image:pairing-qr", False, type(exc).__name__)
    check(
        "resource:third-party-notices",
        any(
            Path(resource_path(relative_path)).is_file()
            for relative_path in (
                "licenses/THIRD_PARTY_NOTICES.md",
                "THIRD_PARTY_NOTICES.md",
            )
        ),
    )
    check(
        "resource:gallery-license",
        any(
            Path(resource_path(relative_path)).is_file()
            for relative_path in (
                "licenses/gallery/LICENSE.gallery.txt",
                "resources/images/LICENSE.gallery.txt",
            )
        ),
    )
    check(
        "resource:segno-license",
        any(
            Path(resource_path(relative_path)).is_file()
            for relative_path in (
                "licenses/segno/LICENSE.segno.txt",
                "resources/licenses/LICENSE.segno.txt",
            )
        ),
    )
    check(
        "resource:mobileperf-license",
        any(
            Path(resource_path(relative_path)).is_file()
            for relative_path in (
                "licenses/mobileperf/LICENSE",
                "mobileperf/LICENSE",
            )
        ),
    )
    check(
        "resource:xlsxwriter-license",
        any(
            Path(resource_path(relative_path)).is_file()
            for relative_path in (
                "licenses/xlsxwriter/LICENSE.txt",
                "mobileperf/extlib/xlsxwriter/LICENSE.txt",
            )
        ),
    )
    from utils.tool_check import check_bundled_tools

    checks.extend(check_bundled_tools())

    from utils.scrcpy_bridge import resolve_scrcpy_bridge

    # 自检验证私有 CLI 的标准输出契约，不连接设备或启动 ADB 服务。
    bridge = resolve_scrcpy_bridge()
    check("resource:scrcpy-adb-bridge", bridge is not None)
    if bridge is not None:
        import subprocess

        try:
            result = subprocess.run(
                [bridge, "--self-check"], capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
            )
            check(
                "runtime:scrcpy-adb-bridge",
                result.returncode == 0 and result.stdout == b"scrcpy-adb-bridge: ready\n",
            )
        except (OSError, subprocess.TimeoutExpired):
            check("runtime:scrcpy-adb-bridge", False, "CLI self-check failed")

    try:
        root = user_data_root()
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".self_check"
        probe.write_text(f"{APP_NAME} {APP_VERSION}", encoding="utf-8")
        probe.unlink(missing_ok=True)
        check("writable:user_data_root", True, str(root))
    except Exception as exc:
        check("writable:user_data_root", False, str(exc))

    failed = False
    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        suffix = f" - {detail}" if detail else ""
        print(f"{status} {name}{suffix}")
        failed = failed or not ok
    return 1 if failed else 0


def _load_fluent_widgets() -> None:
    """在启动单线程阶段加载 Fluent，仅移除依赖的固定推广输出。

    其他标准输出在导入结束或失败时原样转发；异常和标准错误保留，
    不修改安装目录，兼容无控制台的打包进程。
    """
    captured = StringIO()
    try:
        with redirect_stdout(captured):
            __import__("qfluentwidgets")
    finally:
        output = captured.getvalue()
        config = sys.modules.get("qfluentwidgets.common.config")
        alert = getattr(config, "ALERT", "")
        if isinstance(alert, str) and alert:
            output = output.replace(alert + "\n", "", 1)
            output = output.replace(alert.replace("📢", "") + "\n", "", 1)
        if output and sys.stdout is not None:
            sys.stdout.write(output)


def _configure_gui_scaling(value: object) -> str | float:
    """在 QApplication 创建前设置本进程比例；Auto 保留系统及启动环境。"""
    from core.settings_manager import normalise_ui_scale

    factor = normalise_ui_scale(value)
    if factor != "Auto":
        # 与 Gallery 一致：手动比例替代自动 DPI 比例，避免两者相乘。
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_SCALE_FACTOR"] = str(factor)
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    return factor


def _configure_console_logging(settings) -> None:
    """按环境变量或设置限定开发控制台输出级别。

    环境变量优先，便于在 IDE 运行配置里临时覆盖；根 logger 只按阈值收紧，
    不因 DEBUG/INFO 阈值打开第三方库的调试输出。打包运行本就不写控制台。
    """
    import logging

    from utils.console_colors import set_console_level, stdlib_level

    requested = os.environ.get("ADBLAB_CONSOLE_LOG_LEVEL", "").strip()
    applied = set_console_level(requested or settings.get("console_log_level", "DEBUG"))
    logging.getLogger().setLevel(stdlib_level(applied))


def _run_gui() -> int:
    """覆盖设置与 Qt 尚未就绪的失败，原始异常优先于清理及诊断落盘异常。"""
    from core.startup_diagnostics import StartupDiagnostics

    trace = StartupDiagnostics(started_at=_ENTRY_STARTED_AT)
    trace.record("entry", detail="frozen" if getattr(sys, "frozen", False) else "source")
    try:
        return _run_gui_session(trace)
    except BaseException as error:
        trace.record("failed", detail=type(error).__name__)
        try:
            trace.save_failure()
        except Exception as diagnostic_error:
            error.add_note(f"startup diagnostics write failed: {type(diagnostic_error).__name__}")
        raise


def _run_gui_session(trace) -> int:
    """创建 QApplication、加载主题并进入主界面事件循环。"""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_app_user_model_id())

    from core.settings_manager import AppSettings, set_error_sink
    from utils.adb_resolver import set_client_preference

    # Qt 比例必须先于 QApplication 读取。此时日志服务尚未创建，先完整缓冲
    # 设置加载诊断，再转交正式日志接收器，避免提前加载使迁移/读取失败静默。
    startup_diagnostics: list[tuple[str, str]] = []

    def buffer_setting_diagnostic(level, message):
        startup_diagnostics.append((level, message))
        trace.record("settings-diagnostic", detail=f"{level} {message}")

    set_error_sink(buffer_setting_diagnostic)
    settings = AppSettings.instance()
    _configure_console_logging(settings)
    # 客户端选择必须在首次解析前注入，否则会先缓存内置/自动结果。
    set_client_preference(settings.get("adb_client", "auto"))
    _configure_gui_scaling(settings.get("ui_scale", "Auto"))
    trace.record("settings")
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from gui.startup import StartupController
    from gui.startup_process import StartupSplashProcess

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    setup_qt_search_paths()
    splash = StartupSplashProcess(parent=app)
    startup = StartupController(splash, parent=app)
    startup.diagnostics = trace
    splash.diagnostic.connect(lambda message: trace.record("splash-process", detail=message))
    # 翻译器引用保持到应用退出；生成器结束不能提前释放 Python 包装对象。
    translators = []
    log_service = None

    def initialize():
        nonlocal log_service
        _load_fluent_widgets()
        yield "components", 15

        from core.log_service import LogService
        from gui.i18n import install_translators
        from gui.styles import BaseStyles

        translators.extend(install_translators(app, settings.get("language", "Auto")))
        log_service = LogService()
        trace.bind(log_service.record_runtime_diagnostic)
        set_error_sink(log_service.log)
        for level, message in startup_diagnostics:
            log_service.log(level, message)
        startup_diagnostics.clear()
        BaseStyles.reload_from_settings()
        BaseStyles.set_accent_color(settings.get("accent_color", "#0F6CBD"))
        BaseStyles.switch_theme(settings.get("theme", "System"))
        yield "appearance", 25

        from gui.startup_task import StartupTask
        from models.device_store import DeviceStore

        # 先完成独占加载再创建任何读取快照的控件，避免 GUI 等待 DeviceStore 的锁。
        history = StartupTask("device-history", DeviceStore.load)
        yield history
        if history.error is not None:
            if not isinstance(history.error, Exception):
                raise history.error
            log_service.log(
                "WARNING",
                f"连接历史启动加载失败：{type(history.error).__name__}，继续使用内存快照",
            )
        yield "history-ready", 30

        started_at = perf_counter()
        from gui.main_frame import MainFrame

        trace.record("window-import", elapsed_ms=(perf_counter() - started_at) * 1000)

        started_at = perf_counter()
        window = MainFrame(deferred_startup=True, device_history_loaded=True)
        startup.set_window(window)
        window.startup_diagnostics = trace
        trace.record("window-shell", elapsed_ms=(perf_counter() - started_at) * 1000)
        names = {
            40: "window-base", 45: "apps-overview", 50: "system-overview",
            55: "remote-overview", 60: "devices-host", 65: "apps-host",
            70: "workspace", 85: "pages", 95: "navigation",
        }
        while (progress := window.advance_startup()) is not None:
            yield names[progress], progress

    # 排队退出，让中止信号所在轮次的 QObject 延迟释放先收口。
    startup.failed.connect(lambda _error: QTimer.singleShot(0, app, lambda: app.exit(1)))
    startup.cancelled.connect(lambda: QTimer.singleShot(0, app, lambda: app.exit(0)))
    try:
        startup.start(initialize())
        exit_code = app.exec()
    finally:
        _finish_gui(startup, splash, log_service, trace)
    if startup.error is not None:
        raise startup.error
    return exit_code


def _finish_gui(startup, splash, log_service, trace) -> None:
    """逐项尝试清理；已有启动异常优先，单独清理失败仍须向调用方报告。"""
    from PySide6.QtCore import QEventLoop

    primary = sys.exception() or startup.error
    errors = []

    def settle():
        if not startup.is_settled:
            # 提前退出时继续驱动已有关闭屏障，不能把停止请求当作清理完成。
            cleanup_loop = QEventLoop()
            startup.settled.connect(cleanup_loop.quit)
            startup.cancel()
            if not startup.is_settled:
                cleanup_loop.exec()

    cleanup = [("startup", settle), ("splash", splash.shutdown)]
    if log_service is not None:
        cleanup.append(("logger", log_service.shutdown))
    for name, action in cleanup:
        try:
            action()
        except BaseException as error:
            errors.append(error)
            trace.record("cleanup-failed", detail=f"{name} {type(error).__name__}")
    if errors and primary is None and startup.error is None:
        raise errors[0]


if __name__ == "__main__":
    exit_code = _dispatch_cli(sys.argv[1:])
    if exit_code is None:
        exit_code = _run_gui()
    sys.exit(exit_code)
