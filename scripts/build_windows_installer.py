"""把已验证的 Windows onedir 封装为安装器，保持原免安装载荷不变。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

def check_installer_file(path: Path) -> None:
    """共享发布阶段的静态 PE 校验；实际安装另由一次性 Windows 环境验证。"""
    from scripts.check_build_artifacts import CheckError
    from scripts.check_build_artifacts import check_installer_file as check

    try:
        check(path)
    except CheckError as error:
        raise ValueError(str(error)) from error


def verify_compiler(path: Path) -> None:
    """延迟载入固定编译器校验，使脚本入口和包导入使用相同路径。"""
    from scripts.prepare_inno_setup import verify_compiler as verify

    verify(path)


def protocol_include(path: Path) -> None:
    """把运行端协议常量写入编译期 include，安装器不维护另一套身份值。"""
    from core import windows_installation as protocol

    names = {
        "InstallAppId": protocol.APP_ID,
        "MainExecutable": protocol.MAIN_EXECUTABLE,
        "InstallMarker": protocol.INSTALL_MARKER,
        "InstallManifest": protocol.INSTALL_MANIFEST,
        "InstallPendingManifest": protocol.INSTALL_PENDING_MANIFEST,
        "InstallPreviousManifest": protocol.INSTALL_PREVIOUS_MANIFEST,
        "InstallLock": protocol.INSTALL_LOCK,
        "InstallSection": protocol.INSTALL_SECTION,
    }
    path.write_text(
        "".join(f'#define {key} "{value}"\n' for key, value in names.items()),
        encoding="utf-8-sig",
    )


def output_name() -> str:
    """产物版本只来自应用元数据，与保留的 ZIP 使用同一发布标签。"""
    from utils.app_metadata import APP_RELEASE_TAG

    return f"ADBLab-win-x64-{APP_RELEASE_TAG}-setup.exe"


def build(source_dir: Path, entry_name: str, output_dir: Path, iscc: Path) -> Path:
    """新目录编译并校验成功后发布；失败不修改源载荷或覆盖旧的有效安装器。"""
    from scripts.windows_installer.manifest import stage_payload, validate_payload
    from utils.app_metadata import APP_VERSION

    source_dir, output_dir = source_dir.absolute(), output_dir.absolute()
    validate_payload(source_dir, entry_name)
    for parent in (output_dir, *output_dir.parents):
        if parent.is_symlink() or (parent.exists() and parent.resolve() != parent.absolute()):
            raise ValueError("安装器输出目录不能经过链接")
    if output_dir.resolve().is_relative_to(source_dir):
        raise ValueError("安装器输出目录不能位于免安装源目录内")
    verify_compiler(iscc)
    scratch = ROOT / "build/windows-installer"
    scratch.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log = scratch / "compiler.log"
    with tempfile.TemporaryDirectory(prefix="compile-", dir=scratch) as temporary:
        working = Path(temporary)
        stage = working / "payload"
        stage_payload(source_dir, entry_name, stage)
        include = working / "protocol.iss"
        protocol_include(include)
        candidate_dir = working / "output"
        candidate_dir.mkdir()
        command = [
            str(iscc.resolve()), "/Qp", f"/DAppSourceDir={stage}", f"/DAppVersion={APP_VERSION}",
            f"/DProtocolInclude={include}", f"/O{candidate_dir}", f"/F{Path(output_name()).stem}",
            str(ROOT / "scripts/windows_installer/ADBLab.iss"),
        ]
        with log.open("wb") as stream:
            result = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=900,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if result.returncode:
            raise RuntimeError(
                f"安装器编译失败（退出码 {result.returncode}），请检查 build 下的编译日志",
            )
        candidate = candidate_dir / output_name()
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise ValueError("编译器没有生成非空安装程序")
        check_installer_file(candidate)
        output = output_dir / output_name()
        # 在目标目录内复制后原子发布，允许输出目录与临时构建区位于不同卷。
        pending = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".installer-", suffix=".exe", dir=output_dir,
                                             delete=False) as stream:
                pending = Path(stream.name)
                with candidate.open("rb") as payload:
                    while block := payload.read(1024 * 1024):
                        stream.write(block)
            check_installer_file(pending)
            os.replace(pending, output)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
    return output


def main(argv: list[str] | None = None) -> int:
    """构建失败返回非零；dry-run 只读校验输入并展示目标，不探测或执行编译器。"""
    from scripts.prepare_inno_setup import INNO_VERSION
    from scripts.windows_installer.manifest import validate_payload

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--entry-name", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_payload(args.source_dir, args.entry_name)
        compiler = args.iscc or Path(os.environ.get(
            "INNO_SETUP_ISCC", str(ROOT / f"build/tools/inno-{INNO_VERSION}/ISCC.exe"),
        ))
        if args.dry_run:
            print(json.dumps({
                "source": str(args.source_dir), "entry": args.entry_name,
                "output": str(args.output_dir / output_name()), "iscc": str(compiler),
            }, ensure_ascii=True))
            return 0
        if sys.platform != "win32":
            raise ValueError("Windows 安装器必须在 Windows 构建")
        print(build(args.source_dir, args.entry_name, args.output_dir, compiler))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
