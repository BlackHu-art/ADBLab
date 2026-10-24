"""应用写动作事务；执行器与同步通知由调用方提供，不持有 Qt 对象。"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from typing import TYPE_CHECKING

from services.app_data_errors import clear_data_error_code
from services.app_permissions import is_permission_name
from services.apps.package_details import is_safe_package

if TYPE_CHECKING:
    from core.exec import CommandResult
    from services.apps.queries import QueryExecutor


def command_error(result: CommandResult, fallback: str) -> str:
    """优先保留执行层错误，其次输出；空诊断使用调用方兜底。"""
    error = str(getattr(result, "error", "") or "").strip()
    if error:
        return error
    output = str(getattr(result, "output", "") or "").strip()
    return output or fallback


def modify_app(
    action: str,
    package: str,
    user_id: int,
    *,
    execute: QueryExecutor,
    log: Callable[[str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
    feedback: Callable[[str, str], None],
) -> None:
    """执行一次已准入用户的应用动作；同步回调异常沿原路径传播。"""
    if not is_safe_package(package):
        failure(f"Invalid package: {package}")
        return
    cmds = {
        "disable": ["shell", "pm", "disable-user", "--user", str(user_id), package],
        "enable": ["shell", "pm", "enable", "--user", str(user_id), package],
        "uninstall": ["uninstall", "--user", str(user_id), package],
        "force_stop": ["shell", "am", "force-stop", "--user", str(user_id), package],
    }
    cmd = cmds.get(action)
    if not cmd:
        failure(f"Invalid app action: {action}")
        return
    r = execute(*cmd)
    log(f"{'OK' if r.success else 'FAIL'}: {action} {package}")
    if r.success:
        completed(action)
    else:
        feedback("error", command_error(r, f"{action} failed: {package}"))


def launch_app(
    package: str,
    user_id: int,
    *,
    execute: QueryExecutor,
    log: Callable[[str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
) -> None:
    """显式指定用户启动应用，并保留零退出码错误诊断。"""
    if not is_safe_package(package):
        failure(f"Invalid package: {package}")
        return
    # am 可能以退出码 0 把启动失败写到 stderr；仅在此命令合流，避免误报成功。
    # 包名和用户已限定为安全 token，重定向由 Android shell 处理，不经过宿主 shell。
    result = execute(
        "shell",
        "am",
        "start",
        "--user",
        str(user_id),
        "-a",
        "android.intent.action.MAIN",
        "-p",
        package,
        "-c",
        "android.intent.category.LAUNCHER",
        "-f",
        "0x10200000",
        "2>&1",
    )
    if not result.success or re.search(r"(?im)^Error(?:\s|:)", result.output):
        failure(f"Failed to launch {package}: {command_error(result, 'launch command failed')}")
        return
    log(f"Launched {package}")
    completed("launch")


def clear_app(
    package: str,
    user_id: int,
    *,
    execute: QueryExecutor,
    log: Callable[[str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
    permission_denied: Callable[[], None],
) -> None:
    """清除指定用户的数据；权限拒绝只发布诊断和延迟提示，不重试。"""
    if not is_safe_package(package):
        failure(f"Invalid package: {package}")
        return
    r = execute("shell", "pm", "clear", "--user", str(user_id), package)
    if not r.success:
        if clear_data_error_code(r.output, r.error):
            # 用户提示不承诺能绕过系统策略；日志保留已有诊断供任务详情追溯。
            diagnostic = "\n".join(dict.fromkeys(text for text in (r.output, r.error) if text))
            log(f"Failed to clear data for {package}: {diagnostic}")
            permission_denied()
            return
        failure(f"Failed to clear data for {package}: {command_error(r, 'clear command failed')}")
        return
    log(f"Cleared data: {package} — {r.stdout.strip()}")
    completed("clear")


def modify_permission(
    package: str,
    permission: str,
    action: str,
    user_id: int,
    *,
    execute: QueryExecutor,
    log: Callable[[str], None],
    failure: Callable[[str], None],
    completed: Callable[[str], None],
) -> None:
    """校验并引用权限字面值后单次写入；成功通知在日志之后发布。"""
    if not is_safe_package(package):
        failure(f"Invalid package: {package}")
        return
    if action not in {"grant", "revoke"}:
        failure(f"Invalid permission action: {action}")
        return
    if not is_permission_name(permission):
        failure("权限标识无效，请刷新应用详情后重试。")
        return
    # 自定义权限允许 $ 等字符；保留名称原值，由 Android shell 的引用保护字面参数。
    r = execute("shell", "pm", action, "--user", str(user_id), package, shlex.quote(permission))
    if not r.success:
        failure(
            f"Failed to {action} permission {permission}: "
            f"{command_error(r, 'permission command failed')}"
        )
        return
    log(f"Permission {action}: {permission} — {r.stdout.strip() or 'OK'}")
    completed("permissions_changed")
