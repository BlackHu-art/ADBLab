"""分派 CLI 子模式并启动 ADBLab 图形界面。"""

import argparse
import ctypes
import os
import sys
from pathlib import Path

from utils.app_metadata import APP_NAME, APP_VERSION, app_major_minor_version
from utils.resource_path import resource_path, setup_qt_search_paths
from utils.user_data import user_data_root


def windows_app_user_model_id() -> str:
    """生成随主次版本变化的 Windows AppUserModelID。"""
    return f"ADBLab.Frankie.{app_major_minor_version()}"


def _dispatch_cli(argv: list[str]) -> int | None:
    """分派已知 CLI 子模式；未命中时返回 None 以继续启动 GUI。"""
    if not argv:
        return None
    if argv[0] == "--mobileperf-worker":
        return _run_mobileperf_worker(argv[1:])
    if argv[0] == "--self-check":
        return _run_self_check(argv[1:])
    return None


def _run_mobileperf_worker(argv: list[str]) -> int:
    """在隔离子进程中运行 MobilePerf 采集内核。"""
    parser = argparse.ArgumentParser(description="Run mobileperf collection")
    parser.add_argument("--config", default=None, help="Path to mobileperf config file")
    args = parser.parse_args(argv)

    from mobileperf.android.startup import StartUp

    startup = StartUp(config_path=args.config)
    startup.run()
    return 0


def _run_self_check(argv: list[str]) -> int:
    """解析并执行无需启动 Qt 界面的自检子命令。"""
    parser = argparse.ArgumentParser(description="Run ADBLab self checks")
    parser.add_argument("target", choices=["packaging"])
    args = parser.parse_args(argv)
    if args.target == "packaging":
        return _self_check_packaging()
    return 1


def _self_check_packaging() -> int:
    """验证打包所需依赖、资源和用户数据目录的基本可用性。"""
    os.environ.setdefault("MOBILEPERF_LOG_DIR", str(user_data_root() / "logs"))
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    def importable(module_name: str) -> None:
        try:
            __import__(module_name)
            check(f"import:{module_name}", True)
        except Exception as exc:
            check(f"import:{module_name}", False, str(exc))

    importable("PySide6")
    importable("mobileperf.android.startup")

    check("resource:icon.ico", Path(resource_path("icon.ico")).is_file())
    check("resource:resources", Path(resource_path("resources")).is_dir())
    if sys.platform == "win32":
        check(
            "resource:scrcpy.exe",
            Path(resource_path("scrcpy-win64-v3.3.1/scrcpy.exe")).is_file(),
        )
        check(
            "resource:adb.exe",
            Path(resource_path("scrcpy-win64-v3.3.1/adb.exe")).is_file(),
        )

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


def _run_gui() -> int:
    """创建 QApplication、加载主题并进入主界面事件循环。"""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_app_user_model_id())

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from core.log_service import LogService
    from core.settings_manager import AppSettings, set_error_sink
    from gui.main_frame import MainFrame
    from gui.styles import BaseStyles

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    setup_qt_search_paths()

    # 先于任何设置读取创建日志服务并注入设置层错误接收器，使启动期
    # （MainFrame 创建之前）的设置加载/保存错误可见，而不是静默丢弃。
    LogService()
    set_error_sink(LogService().log)

    # 字体管理器同时更新 QApplication 与各字体角色，保持单一应用入口。
    BaseStyles.reload_from_settings()
    saved_theme = AppSettings.instance().get("theme", "Light")
    BaseStyles.switch_theme(saved_theme)

    window = MainFrame()
    window.show()
    return app.exec()


if __name__ == "__main__":
    exit_code = _dispatch_cli(sys.argv[1:])
    if exit_code is None:
        exit_code = _run_gui()
    sys.exit(exit_code)
