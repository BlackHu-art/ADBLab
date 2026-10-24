"""在隔离用户缓存中验证冻结交接，不安装产品或修改开发机注册表。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

# 此载荷只写测试哨兵，不具有安装或修改产品数据的能力。
FIXTURE = '''
import hashlib, json, os, sys, time
from pathlib import Path
if len(sys.argv) == 1:
    Path(os.environ["ADBLAB_HANDOFF_PROBE_MARKER"]).write_text("started", encoding="ascii")
else:
    from core.installer_handoff import InstallerHandoff
    from services.app_update import InstallerAsset
    from services.installer_update import DownloadWriter
    root, helper, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    body = Path(sys.executable).read_bytes()
    asset = InstallerAsset(1, 2, "v99.0.0", "99.0.0", "ADBLab-win-x64-v99.0.0-setup.exe",
        "https://github.com/BlackHu-art/ADBLab/releases/download/v99.0.0/"
        "ADBLab-win-x64-v99.0.0-setup.exe", len(body), hashlib.sha256(body).hexdigest())
    writer = DownloadWriter(asset)
    for pos in range(0, len(body), 65536):
        writer.write(body[pos:pos+65536])
    verified = writer.finish()
    owner = InstallerHandoff()
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    owner._helper_source = lambda: (helper, digest)
    owner.prepare(verified)
    if mode == "corrupt":
        with verified.path.open("r+b") as stream:
            stream.write(b"NO")
    owner.mark_shutdown_success(mode != "unapproved")
    owner.commit()
    (root / "ready.json").write_text(json.dumps({"helper_pid": owner._process.pid,
        "cache": str(verified.path.parent)}), encoding="utf-8")
    deadline = time.monotonic() + 30
    while not (root / "exit-gate").exists():
        if time.monotonic() >= deadline:
            raise SystemExit(9)
        time.sleep(0.02)
    raise SystemExit(7 if mode == "abnormal" else 0)
'''


def _until(predicate, *, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("frozen handoff probe deadline")
        time.sleep(0.05)


def run_probe(helper: Path, workspace: Path) -> None:
    """使用独占工作目录及四个独立 LOCALAPPDATA，测试成功和禁止执行的场景。"""
    from core.installer_update_process import ParentProcess

    helper = helper.resolve(strict=True)
    workspace = workspace.absolute()
    workspace.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="handoff-probe-", dir=workspace))
    print(f"Probe evidence: {stage}", flush=True)
    source = stage / "fixture.py"
    source.write_text(FIXTURE, encoding="utf-8")
    with (workspace / "fixture-build.log").open("wb") as log:
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
            "--console", "--noupx", "--name", "handoff-fixture", "--paths", str(ROOT),
            "--exclude-module", "PySide6", "--exclude-module", "PyQt5",
            "--exclude-module", "utils.adb_resolver", "--distpath", str(stage / "dist"),
            "--workpath", str(stage / "work"), "--specpath", str(stage), str(source),
        ], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    fixture = stage / "dist/handoff-fixture.exe"
    for mode in ("success", "unapproved", "abnormal", "corrupt"):
        case = stage / mode
        install = case / "安装 目录"
        install.mkdir(parents=True)
        helper_copy = install / helper.name
        shutil.copyfile(helper, helper_copy)
        environment = dict(os.environ, LOCALAPPDATA=str(case / "本地 数据"),
                           ADBLAB_HANDOFF_PROBE_MARKER=str(case / "payload-started"),
                           PYINSTALLER_RESET_ENVIRONMENT="1")
        parent = subprocess.Popen([str(fixture), str(case), str(helper_copy), mode],
                                  cwd=case, env=environment, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            _until(lambda: (case / "ready.json").exists() or parent.poll() is not None)
            assert (case / "ready.json").exists(), f"parent preparation failed: {mode}"
            info = json.loads((case / "ready.json").read_text(encoding="utf-8"))
            assert not (case / "payload-started").exists(), "started before parent exit"
            # 持续存在的 helper 不得占用安装根中的 EXE 或 DLL。
            install.rename(case / "已释放 安装目录")
            try:
                helper_parent = ParentProcess(info["helper_pid"])
            except OSError:
                helper_parent = None
            (case / "exit-gate").write_text("exit", encoding="ascii")
            assert parent.wait(timeout=15) == (7 if mode == "abnormal" else 0)
            cache = Path(info["cache"])
            _until(lambda: bool(list(cache.glob("handoff-*.json"))))
            statuses = [json.loads(path.read_text())["status"]
                        for path in cache.glob("handoff-*.json")]
            if mode == "success":
                _until(lambda: (case / "payload-started").exists())
                assert statuses == ["handed_off"], statuses
            else:
                assert "handed_off" not in statuses, statuses
                assert not (case / "payload-started").exists(), mode
            if helper_parent is not None:
                try:
                    assert helper_parent.wait(15), "helper did not exit"
                finally:
                    helper_parent.close()
            print(f"{mode}: passed", flush=True)
        finally:
            if parent.poll() is None:
                # 本脚本生成的无业务 fixture 才能在失败时回收，绝不查询或结束产品进程。
                parent.kill()
                parent.wait(timeout=5)
    # 成功载荷是短进程；等待其退出，探针完成后只保留可检查的文件证据。
    _until(lambda: _payload_released(stage))


def _payload_released(stage: Path) -> bool:
    """以删除共享访问探测本次哨兵载荷是否退出，不删除文件。"""
    from core.windows_installation import _windows_api

    kernel = _windows_api()
    for path in stage.rglob("ADBLab-win-x64-v99.0.0-setup.exe"):
        handle = kernel.CreateFileW(str(path), 0x10000, 7, None, 3, 0x80, None)
        if handle == -1 or handle == 0xFFFFFFFFFFFFFFFF:
            return False
        kernel.CloseHandle(handle)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("requires Windows")
    run_probe(args.helper, args.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
