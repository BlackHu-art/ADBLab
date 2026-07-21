import argparse
import ctypes
import os
import sys
from pathlib import Path

from utils.app_metadata import APP_NAME, APP_VERSION, app_major_minor_version
from utils.resource_path import resource_path, setup_qt_search_paths
from utils.user_data import user_data_root


def windows_app_user_model_id() -> str:
    return f"ADBLab.Frankie.{app_major_minor_version()}"


def _dispatch_cli(argv: list[str]) -> int | None:
    if not argv:
        return None
    if argv[0] == "--mobileperf-worker":
        return _run_mobileperf_worker(argv[1:])
    if argv[0] == "--self-check":
        return _run_self_check(argv[1:])
    return None


def _run_mobileperf_worker(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run mobileperf collection")
    parser.add_argument("--config", default=None, help="Path to mobileperf config file")
    args = parser.parse_args(argv)

    from mobileperf.android.startup import StartUp

    startup = StartUp(config_path=args.config)
    startup.run()
    return 0


def _run_self_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run ADBLab self checks")
    parser.add_argument("target", choices=["packaging"])
    args = parser.parse_args(argv)
    if args.target == "packaging":
        return _self_check_packaging()
    return 1


def _self_check_packaging() -> int:
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
    importable("requests")
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
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(windows_app_user_model_id())

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from core.settings_manager import AppSettings
    from gui.main_frame import MainFrame
    from gui.styles import BaseStyles

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    setup_qt_search_paths()

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
