"""格式化 ADB 路径与后端诊断并转交现有开发控制台，不创建日志服务或文件。"""

from __future__ import annotations

import json
import ntpath
import sys

from utils.console_colors import should_emit

_COMMANDS = frozenset({
    "version", "devices", "start-server", "kill-server", "host-features",
    "features", "shell", "exec-out", "exec-in", "install", "install-multiple",
    "install-multi-package", "uninstall", "push", "pull", "sync", "logcat",
    "bugreport", "forward", "reverse", "connect", "disconnect", "pair",
    "reconnect", "get-state", "get-serialno", "get-devpath", "root", "unroot",
    "remount", "reboot", "tcpip", "usb", "wait-for-device", "track-devices",
    "jdwp", "track-jdwp", "backup", "restore", "help",
})


def enabled(level: str = "DEBUG") -> bool:
    """判断指定级别能否输出，使调用方在序列化前跳过禁用路径。"""
    if getattr(sys, "frozen", False) or not should_emit(level):
        return False
    stream_name = "stderr" if level in {"WARNING", "ERROR", "CRITICAL"} else "stdout"
    stream = getattr(sys, stream_name, None)
    return stream is not None and not getattr(stream, "closed", False)


def _summary(name: str, fields: dict[str, object]) -> tuple[str, str] | None:
    """区分用户选择、能力快照与本次调用，不把一次原生测速描述为全局切换。"""
    if name == "resolve_result" and fields.get("cached") is False:
        selected = fields.get("selected_adb")
        if selected:
            source = str(fields.get("source", "unknown"))
            label = {
                "bundled": "应用自带", "runtime_cache": "应用工具缓存", "PATH": "系统 PATH",
            }.get(source, "已解析路径")
            return (
                "INFO", f"[ADB] 已选择 ADB 客户端：{selected}；来源：{label}（{source}）",
            )
        return "WARNING", "[ADB] 未找到可用的 ADB；请检查应用工具目录和系统 PATH。"
    mode = {"auto": "自动选择", "fast": "优先快速", "native": "原生 ADB"}.get(
        str(fields.get("selection_mode")), "待检测",
    )
    path = fields.get("selected_adb") or "未检测到客户端"
    if name in {"mode", "probe_complete"}:
        action = "执行模式已切换" if name == "mode" else "执行环境检测结束"
        scan = "快速直连" if fields.get("fast_devices") else "原生 ADB"
        if not fields.get("selected_adb"):
            scan = "不可用"
        return "INFO", (
            f"[ADB] {action}；模式：{mode}；设备列表选路：{scan}；"
            f"快速 Shell：{fields.get('fast_shell_devices', 0)}/"
            f"{fields.get('checked_devices', 0)}；状态：{fields.get('status', 'unknown')}；"
            f"客户端：{path}"
        )
    if name == "probe_start":
        return "INFO", f"[ADB] 开始检测执行环境；模式：{mode}；客户端：{path}"
    if name == "execute" and fields.get("phase") == "start":
        backend = fields.get("backend")
        if backend == "native_client":
            description = "本次原生 ADB 调用"
        elif backend == "server_direct":
            description = "本次快速直连调用（不启动 adb.exe）"
        else:
            return None
        return "INFO", (
            f"[ADB] {description}；命令类别：{fields.get('command', 'other')}；"
            f"客户端：{fields.get('executable')}"
        )
    return None


def event(name: str, **fields: object) -> None:
    """转交摘要及详细诊断；仅接受明确路径、固定类别和状态，不传业务原文。"""
    # GUI 先初始化日志服务；独立命令入口不能因为诊断而引入 Qt 依赖。
    service_module = sys.modules.get("core.log_service")
    if service_module is None:
        return
    summary = _summary(name, fields)
    if summary is not None and enabled(summary[0]):
        service_module.LogService.write_developer_console(*summary)
    if enabled("DEBUG"):
        message = "[ADB] " + json.dumps({**fields, "event": name}, ensure_ascii=False)
        service_module.LogService.write_developer_console("DEBUG", message)


def _command_index(arguments: list[str]) -> int:
    """跳过目标和服务参数；未知选项不猜测参数数量。"""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-s", "-t", "-H", "-P", "-L", "--one-device"}:
            index += 2
        elif argument in {"-a", "-d", "-e"}:
            index += 1
        else:
            break
    return index


def _command_category(arguments: list[str]) -> str:
    """只识别固定命令名，跳过目标和服务参数但绝不保留这些参数的值。"""
    index = _command_index(arguments)
    value = arguments[index] if index < len(arguments) else ""
    return value if value in _COMMANDS else "other"


def command_summary(arguments: list[str]) -> str:
    """慢命令只保留固定类别；整句 Shell 和动态参数不进入诊断。"""
    category = _command_category(arguments)
    if category != "shell":
        return category
    shell = arguments[_command_index(arguments) + 1:]
    if not shell:
        return "shell"
    subcommands = {
        "input": {"text", "tap", "swipe", "keyevent", "motionevent"},
        "pm": {"list", "path", "install", "uninstall", "clear", "enable", "disable-user"},
        "am": {"start", "broadcast", "force-stop", "startservice", "stopservice"},
        "settings": {"get", "put", "delete", "list"},
        "cmd": {"package", "activity", "appops"},
        "dumpsys": {"package", "activity", "meminfo", "battery", "window", "gfxinfo"},
        "getprop": set(), "monkey": set(), "sh": set(),
    }
    first = shell[0]
    if first not in subcommands:
        return "shell other"
    second = shell[1] if len(shell) > 1 else ""
    suffix = f" {second}" if second in subcommands[first] else ""
    return f"shell {first}{suffix}"


def command(
    cmd: list[str], *, backend: str, phase: str = "start", **fields: object,
) -> None:
    """记录 ADB 执行路径与命令类别，忽略其他程序及所有原始命令参数。"""
    if not cmd or ntpath.basename(cmd[0]).lower() not in {"adb", "adb.exe"}:
        return
    event(
        "execute", **fields, backend=backend, phase=phase,
        executable=cmd[0], command=_command_category(cmd[1:]),
    )
