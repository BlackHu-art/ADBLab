"""一次性 runner 的标准用户身份、环境和系统集成验收边界。"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import stat
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

ADMINISTRATORS = "S-1-5-32-544"
_USER_SID = re.compile(r"S-1-5-21-\d+-\d+-\d+-\d+\Z")
_JOB_FIELDS = {"installer", "version", "iscc", "python", "workspace", "expected_sid"}
_ENVIRONMENT_KEYS = {
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA",
    "GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_TEMP",
}


def _safe_path(value: str) -> Path:
    """只接受绝对、无重解析点路径；不存在的末端可以由本次验收创建。"""
    path = Path(value)
    if not value or not path.is_absolute():
        raise ValueError("标准用户目录必须是非空绝对路径")
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and (
            getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )):
            raise ValueError("标准用户验收路径不能经过重解析点")
    return path.resolve()


def _read_windows_identity() -> dict[str, Any]:
    """读取当前进程真实令牌与已加载用户 hive，不依赖环境变量判定身份。"""
    if sys.platform != "win32":
        raise ValueError("标准用户验收仅支持 Windows")
    import winreg

    from scripts.check_windows_installer import _known_folder

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    userenv.GetUserProfileDirectoryW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    userenv.GetUserProfileDirectoryW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())

    def token_info(kind: int):
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
        if not 0 < size.value <= 1024 * 1024:
            raise OSError("无法读取进程令牌长度")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer

    def sid_string(pointer) -> str:
        output = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return output.value or ""
        finally:
            kernel.LocalFree(ctypes.cast(output, ctypes.c_void_p))

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenGroups(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("groups", SidAndAttributes * 1)]

    try:
        user_buffer = token_info(1)
        sid = sid_string(ctypes.cast(user_buffer, ctypes.POINTER(ctypes.c_void_p))[0])
        groups_buffer = token_info(2)
        count = ctypes.cast(groups_buffer, ctypes.POINTER(wintypes.DWORD))[0]
        offset = TokenGroups.groups.offset
        if offset + count * ctypes.sizeof(SidAndAttributes) > len(groups_buffer):
            raise OSError("进程令牌组信息不完整")
        groups = [sid_string(SidAndAttributes.from_buffer(
            groups_buffer, offset + index * ctypes.sizeof(SidAndAttributes)).sid)
            for index in range(count)]
        elevation = ctypes.cast(token_info(20), ctypes.POINTER(wintypes.DWORD))[0] != 0
        size = wintypes.DWORD()
        userenv.GetUserProfileDirectoryW(token, None, ctypes.byref(size))
        if not 0 < size.value <= 32768:
            raise OSError("无法定位当前令牌的用户 profile")
        profile = ctypes.create_unicode_buffer(size.value)
        if not userenv.GetUserProfileDirectoryW(token, profile, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        # 不允许借用 .DEFAULT 或 runner 管理员 hive；未加载即失败。
        with winreg.OpenKey(winreg.HKEY_USERS, sid, 0, winreg.KEY_READ):
            pass
        if _safe_path(profile.value) != _safe_path(str(_known_folder(40))):
            raise ValueError("令牌 profile 与 Shell profile 不一致")
        return {
            "sid": sid, "elevated": elevation, "groups": groups, "profile_loaded": True,
            "profile": profile.value, "local_appdata": str(_known_folder(28)),
            "appdata": str(_known_folder(26)), "programs": str(_known_folder(2)),
            "desktop": str(_known_folder(16)),
        }
    finally:
        kernel.CloseHandle(token)


def _validate_identity(identity: dict[str, Any], expected_sid: str | None) -> None:
    if not _USER_SID.fullmatch(identity["sid"]) or (
        expected_sid is not None and identity["sid"] != expected_sid
    ):
        raise ValueError("当前令牌不是本次标准用户账户")
    # 包括 deny-only 管理员组，不能把过滤后的管理员令牌误当作标准账户。
    if identity["elevated"] or ADMINISTRATORS in identity["groups"]:
        raise ValueError("验收进程必须使用非管理员且未提升的令牌")
    if not identity["profile_loaded"]:
        raise ValueError("标准用户 profile 尚未加载")
    profile = _safe_path(identity["profile"])
    if not profile.is_dir():
        raise ValueError("标准用户 profile 目录不存在")
    for name in ("local_appdata", "appdata", "programs", "desktop"):
        directory = _safe_path(identity[name])
        if directory == profile or not directory.is_relative_to(profile):
            raise ValueError("一次性账户 Shell 目录不属于该用户 profile")


def assert_standard_user(expected_sid: str | None = None) -> dict[str, Any]:
    """只读核实真实身份与环境归属；失败不得继续安装或回退管理员运行。"""
    identity = _read_windows_identity()
    _validate_identity(identity, expected_sid)
    for variable, name in (("USERPROFILE", "profile"), ("LOCALAPPDATA", "local_appdata"),
                           ("APPDATA", "appdata")):
        if _safe_path(os.environ.get(variable, "")) != _safe_path(identity[name]):
            raise ValueError("当前环境仍指向其他用户目录")
    if _safe_path(str(Path.home())) != _safe_path(identity["profile"]):
        raise ValueError("Python home 与当前用户 profile 不一致")
    return identity | {"admin_group": False}


def build_environment(identity: dict[str, Any], source: dict[str, str]) -> dict[str, str]:
    """白名单继承机器与 CI 上下文，用户目录全部从已校验令牌和 Shell 重建。"""
    _validate_identity(identity, identity["sid"])
    result = {key: value for key, value in source.items() if key.upper() in _ENVIRONMENT_KEYS}
    profile = Path(identity["profile"])
    temporary = Path(identity["local_appdata"]) / "Temp"
    result.update({
        "USERPROFILE": str(profile), "HOMEDRIVE": profile.drive,
        "HOMEPATH": str(profile)[len(profile.drive):],
        "LOCALAPPDATA": identity["local_appdata"], "APPDATA": identity["appdata"],
        "TEMP": str(temporary), "TMP": str(temporary), "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    })
    return result


def load_job(path: Path) -> dict[str, str]:
    """只读取本次工作目录中的有限非秘密配置，不接受任意命令或额外字段。"""
    if not (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("RUNNER_OS") == "Windows"):
        raise ValueError("标准用户 bootstrap 只允许一次性 Windows 托管 runner")
    job_path = _safe_path(str(path))
    if job_path.stat().st_size > 16384:
        raise ValueError("标准用户 job 配置过大")
    value = json.loads(job_path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or set(value) != _JOB_FIELDS or not all(
        isinstance(item, str) and item and "\x00" not in item for item in value.values()
    ):
        raise ValueError("标准用户 job 字段不符合固定契约")
    if not _USER_SID.fullmatch(value["expected_sid"]):
        raise ValueError("标准用户 job 缺少有效账户 SID")
    temporary = _safe_path(os.environ.get("RUNNER_TEMP", ""))
    workspace = _safe_path(value["workspace"])
    if workspace == temporary or not workspace.is_relative_to(temporary) or (
        job_path != workspace / "job.json" or (workspace / "run").exists()
    ):
        raise ValueError("标准用户 job 必须位于本次专属目录且尚未执行")
    for name in ("installer", "python", "iscc"):
        if not _safe_path(value[name]).is_file():
            raise ValueError("标准用户 job 输入文件不存在")
    return value


def _read_registration(hive: str, view: int, sid: str | None = None) -> dict[str, str] | None:
    import winreg

    from core.windows_installation import APP_ID

    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
    if hive == "HKU":
        key = f"{sid}\\{key}"
    root = {"HKCU": winreg.HKEY_CURRENT_USER, "HKU": winreg.HKEY_USERS,
            "HKLM": winreg.HKEY_LOCAL_MACHINE}[hive]
    access = winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if view == 64 else winreg.KEY_WOW64_32KEY)
    try:
        handle = winreg.OpenKey(root, key, 0, access)
    except FileNotFoundError:
        return None
    with handle:
        return {"path": str(winreg.QueryValueEx(handle, "InstallLocation")[0]),
                "version": str(winreg.QueryValueEx(handle, "DisplayVersion")[0])}


def _read_shortcut(path: Path) -> dict[str, str]:
    if not _safe_path(str(path)).is_file():
        raise ValueError("当前用户快捷方式不存在")
    # 托管 runner 的 PowerShell 7 按 UTF-8 读取脚本，避免旧版用 ANSI 误读中文源码。
    powershell = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell/7/pwsh.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-File",
         str(Path(__file__).with_name("read_shortcut.ps1")), "-LiteralPath", str(path)],
        capture_output=True, text=True, encoding="utf-8-sig", timeout=30, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("读取快捷方式失败")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or set(value) != {"target", "working_directory"} or not all(
        isinstance(item, str) and item for item in value.values()
    ):
        raise ValueError("快捷方式解析结果缺少目标或工作目录")
    return value


def assert_current_user_installation(app: Path, version: str, identity: dict[str, Any]) -> None:
    """确认产品登记与两个快捷方式均属于当前标准账户且精确指向本次安装。"""
    current = assert_standard_user(identity["sid"])
    app = _safe_path(str(app))
    for hive, sid in (("HKCU", None), ("HKU", current["sid"])):
        value = _read_registration(hive, 64, sid)
        if value is None or _safe_path(value["path"]) != app or value["version"] != version:
            raise ValueError("当前标准用户卸载登记路径或版本不符合预期")
    for view in (64, 32):
        if _read_registration("HKLM", view) is not None:
            raise ValueError("标准用户安装不应生成系统级卸载登记")
    for path in (Path(current["programs"]) / "ADBLab/ADBLab.lnk",
                 Path(current["desktop"]) / "ADBLab.lnk"):
        value = _read_shortcut(path)
        if _safe_path(value["target"]) != app / "ADBLab.exe" or (
            _safe_path(value["working_directory"]) != app
        ):
            raise ValueError("当前用户快捷方式目标或工作目录错误")


def main(argv: list[str] | None = None) -> int:
    """先校验身份并重建环境，再以同一标准令牌调用固定的扩展验收入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args(argv)
    original_environment = dict(os.environ)
    try:
        job = load_job(args.job)
        identity = _read_windows_identity()
        _validate_identity(identity, job["expected_sid"])
        environment = build_environment(identity, dict(os.environ))
        os.environ.clear()
        os.environ.update(environment)
        identity = assert_standard_user(job["expected_sid"])
        _safe_path(environment["TEMP"]).mkdir(parents=True, exist_ok=True)
        workspace = Path(job["workspace"])
        with (workspace / "identity.json").open("x", encoding="utf-8") as stream:
            json.dump(identity, stream, ensure_ascii=False, indent=2)
        print("PASS actual standard-user token: expected SID matched, admin group absent, "
              "not elevated, own profile and HKU loaded", flush=True)
        result = subprocess.run(
            [job["python"], "-B", str(ROOT / "scripts/check_windows_installer_extended.py"),
             "--installer", job["installer"], "--version", job["version"],
             "--iscc", job["iscc"], "--workspace", str(workspace / "run"),
             "--disposable", "--require-standard-user"],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, check=False,
        )
        return result.returncode
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # 不输出异常对象或环境；第三方错误可能包含不应写入诊断的参数。
        print(f"FAIL 标准用户验收边界失败：{type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        # 允许安全单测和调用方复用入口；标准用户子进程已经得到独立白名单副本。
        os.environ.clear()
        os.environ.update(original_environment)


if __name__ == "__main__":
    raise SystemExit(main())
