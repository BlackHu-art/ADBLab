"""应用查询 helper 的有界传输、取消与精确路径清理边界。"""

from __future__ import annotations

import base64
import logging
import shlex
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.exec import CommandRunner
from utils.resource_path import resource_path

# 原生 adb 启动可能超过 8 秒；渲染预算还需容纳设备端 15 秒退出保护。
_COMMAND_TIMEOUT = 30
# 限制编码后的 shell 参数，保留 Windows 原生回退所需的命令行空间。
_MAX_INLINE_HELPER_BYTES = 16 * 1024
_CLEANED = "\n__ADBLAB_ICONS_CLEANED__\n"
_DEPLOY_FAILED = "__ADBLAB_ICONS_DEPLOY_FAILED__"


@dataclass(frozen=True)
class HelperResult:
    """已确认收尾的 helper 输出；错误仅使用固定分类，不包含设备或路径信息。"""

    output: str = ""
    error: str = ""


def run_app_helper(
    device_id: str, packages: list[str], cancelled: Callable[[], bool], *,
    output_limit: int, metadata: bool = False, icon_metadata: bool = False,
) -> HelperResult:
    """执行已校验的设备与包名批次；取消仍清理，清理失败不发布任何协议数据。

    图标与元数据共用同一临时组件和传输边界；发送后的失败只补清理，不重放查询。
    调用方分别校验包数、目标与协议，元数据模式只加入固定开关。
    """
    failure = HelperResult(error="READ_FAILED")
    helper = Path(resource_path("resources/app-icon-helper.jar"))
    if not helper.is_file():
        return HelperResult(error="MISSING")
    remote = f"/data/local/tmp/adblab-icons-{uuid.uuid4().hex}.jar"
    target = shlex.quote(remote)
    adb = ["adb", "-s", device_id]
    try:
        with helper.open("rb") as source:
            payload = source.read(_MAX_INLINE_HELPER_BYTES + 1)
    except OSError:
        return failure
    arguments = " ".join(shlex.quote(package) for package in packages)
    if metadata:
        arguments = "--metadata " + arguments
    elif icon_metadata:
        arguments = "--icons-metadata " + arguments
    if 0 < len(payload) <= _MAX_INLINE_HELPER_BYTES:
        return _run_inline_helper(adb, target, payload, arguments, output_limit, cancelled)
    results = failure
    try:
        deploy = [*adb, "push", str(helper), remote]
        pushed = CommandRunner.run(deploy, timeout=_COMMAND_TIMEOUT, cancelled=cancelled)
        if not pushed.success:
            results = HelperResult(error="DEPLOY_FAILED")
        elif not cancelled():
            # 设备端先把动态代码改为只读，再截断 stdout，避免主机捕获无界输出。
            script = (
                f"{{ chmod 400 {target} && CLASSPATH={target} "
                f"app_process / com.adblab.icons.Main {arguments}; }} "
                f"2>/dev/null | head -c {output_limit + 1}"
            )
            result = CommandRunner.run(
                [*adb, "shell", script], timeout=_COMMAND_TIMEOUT, cancelled=cancelled
            )
            if result.success and not cancelled():
                results = HelperResult(output=result.output)
    except Exception:
        # 外部执行边界的异常只传播固定错误；finally 仍处理可能已部分传输的文件。
        results = failure
    finally:
        try:
            removed = CommandRunner.run(
                [*adb, "shell", f"rm -f -- {target}"], timeout=_COMMAND_TIMEOUT
            )
            cleaned = removed.success
        except Exception:
            cleaned = False
        if not cleaned:
            logging.getLogger(__name__).warning("应用查询临时文件清理失败")
            results = HelperResult(error="CLEANUP_FAILED")
    return results


def _run_inline_helper(
    adb: list[str], target: str, payload: bytes, arguments: str, output_limit: int,
    cancelled: Callable[[], bool],
) -> HelperResult:
    """一次调用部署、渲染并确认清理；异常才补精确路径清理，绝不重放提取。

    内置小文件受字节上限约束，原生和快速后端共用相同脚本，减少原生启动次数。
    EXIT trap 在设备上收尾；主机只有收到完整清理标记才省略补偿清理。取消关闭连接
    不等于设备已收尾，因此缺失标记时仍执行独立且有界的必要清理。
    """
    results = HelperResult(error="READ_FAILED")
    encoded = base64.b64encode(payload).decode("ascii")
    cleanup = f"rm -f -- {target} && printf {shlex.quote(_CLEANED)}"
    # 部署失败也以零码交付协议，避免执行器丢弃 stdout；业务仍按失败标记返回错误。
    script = (
        f"trap {shlex.quote(cleanup)} EXIT; trap 'exit 130' HUP INT TERM; "
        f"umask 077; if ! (printf %s {encoded} | base64 -d > {target}); then "
        f"printf {shlex.quote(_DEPLOY_FAILED)}; exit 0; fi; "
        f"chmod 400 {target} || exit 1; "
        f"{{ CLASSPATH={target} app_process / com.adblab.icons.Main {arguments}; }} "
        f"2>/dev/null | head -c {output_limit + 1}"
    )
    cleaned = False
    try:
        result = CommandRunner.run(
            [*adb, "shell", "sh", "-c", shlex.quote(script)],
            timeout=_COMMAND_TIMEOUT, cancelled=cancelled,
        )
        # 执行器统一去掉输出首尾空白；清理确认以末尾完整协议行判断，不依赖最后一个换行。
        output = result.output.rstrip("\r\n")
        marker = _CLEANED.strip()
        cleaned = output == marker or output.endswith("\n" + marker)
        if cleaned:
            output = output[:-len(marker)].rstrip("\r\n")
        if output == _DEPLOY_FAILED:
            results = HelperResult(error="DEPLOY_FAILED")
        elif result.success and not cancelled():
            results = HelperResult(output=output)
    except Exception:
        # 执行器或设备错误只影响本批；界面不暴露底层路径和设备标识。
        results = HelperResult(error="READ_FAILED")
    finally:
        if not cleaned:
            try:
                cleaned = CommandRunner.run(
                    [*adb, "shell", f"rm -f -- {target}"], timeout=_COMMAND_TIMEOUT,
                ).success
            except Exception:
                cleaned = False
        if not cleaned:
            logging.getLogger(__name__).warning("应用查询临时文件清理失败")
            results = HelperResult(error="CLEANUP_FAILED")
    return results
