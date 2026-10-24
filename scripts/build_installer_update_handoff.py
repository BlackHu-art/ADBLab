"""构建仅标准库的 Windows onefile 交接程序，候选自检通过后才替换正式缓存。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

def _check_archive(executable: Path) -> None:
    """读取真实冻结清单，拒绝 Qt、第三方 Python 模块及协议闭包之外的应用模块。"""

    from PyInstaller.archive.readers import CArchiveReader

    from utils.installer_update_helper import HELPER_RUNTIME_SOURCES

    archive = CArchiveReader(str(executable))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    allowed = {
        relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        for relative in HELPER_RUNTIME_SOURCES
    }
    for module in pyz.toc:
        root = module.split(".")[0]
        if root not in sys.stdlib_module_names and module not in allowed:
            raise ValueError(f"交接 helper 收集了非协议模块：{module}")
    if any(any(name in member.lower() for name in ("pyside", "shiboken", "qt6", "qt5"))
           for member in archive.toc):
        raise ValueError("交接 helper 不能包含 Qt 运行库")
    required = {
        "core.installer_update_protocol", "core.installer_update_process",
        "services.app_update", "utils.app_metadata", "utils.user_data",
    }
    if not required.issubset(pyz.toc):
        raise ValueError("交接 helper 缺少运行协议依赖")


def main() -> int:
    """只构建 Windows helper，沿用共享锁与发布协议，失败保留旧产物和候选诊断。"""

    if sys.platform != "win32":
        return 0
    from scripts.build_scrcpy_adb_bridge import _build_lock, _publish, _self_check
    from utils.installer_update_helper import HELPER_NAME, helper_source_digest

    build = ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)
    if build.resolve() != ROOT.resolve() / "build":
        raise ValueError("交接 helper 构建目录不能指向仓库之外。")
    with _build_lock(build / "update-handoff-build.lock"):
        output = build / "runtime-helpers" / HELPER_NAME
        filename = f"{HELPER_NAME}.exe"
        executable = output / filename
        stamp = output / "source.sha256"
        expected = helper_source_digest(ROOT)
        if (
            executable.is_file() and stamp.is_file()
            and stamp.read_text(encoding="ascii").strip() == expected
        ):
            _check_archive(executable)
            log = build / "update-handoff-self-check.log"
            print(f"交接 helper 自检日志：{log}")
            return _self_check(executable, log, check=False)
        staging_root = build / "update-handoff-staging"
        staging_root.mkdir(exist_ok=True)
        if staging_root.resolve() != build.resolve() / "update-handoff-staging":
            raise ValueError("交接 helper 候选构建目录不能重定向。")
        stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=staging_root))
        candidate = stage / "dist" / HELPER_NAME
        print(f"交接 helper 构建和自检日志：{stage}")
        command = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--console", "--noupx", "--name", HELPER_NAME,
            "--paths", str(ROOT), "--distpath", str(candidate),
            "--workpath", str(stage / "work"), "--specpath", str(stage),
        ]
        # utils 包的可选 GUI/ADB 分支不属于独立协议，静态分析也不能沿它们收集主应用。
        for module in (
            "utils.adb_resolver", "PySide6", "PyQt6", "PyQt5", "PySide2",
            "shiboken6", "qfluentwidgets", "tkinter",
        ):
            command.extend(("--exclude-module", module))
        command.append(str(ROOT / "scripts/installer_update_handoff.py"))
        with (stage / "build.log").open("wb") as stream:
            subprocess.run(command, cwd=ROOT, check=True, stdout=stream, stderr=subprocess.STDOUT)
        _check_archive(candidate / filename)
        _self_check(candidate / filename, stage / "self-check.log", check=True)
        if helper_source_digest(ROOT) != expected:
            raise RuntimeError("交接 helper 构建期间源码已变化，请重试；旧产物保持不变。")
        (candidate / "source.sha256").write_text(expected + "\n", encoding="ascii")
        output.parent.mkdir(parents=True, exist_ok=True)
        _publish(candidate, output, stage / "previous")
        # 只清理由本次 mkdtemp 创建、仍位于明确 staging 根内的目录。
        if stage.resolve().parent != staging_root.resolve():
            raise RuntimeError("交接 helper 候选清理路径不在本次构建目录内。")
        try:
            shutil.rmtree(stage)
        except OSError as error:
            print(f"交接 helper 已发布，候选暂未清理（{type(error).__name__}）：{stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
