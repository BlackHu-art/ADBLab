"""以同步值回调交付文件事务，局部和远端暂存由各事务唯一拥有。"""

from __future__ import annotations

import os
import posixpath
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core.exec import CommandResult, command_outcome
from services import file_explorer as explorer_service
from services.file_explorer import DirectoryListing, TextPreview

CancelCheck = Callable[[], bool]
DirectoryPublish = Callable[[DirectoryListing | str, bool], None]
TextPublish = Callable[[bytes | str, bool], None]
SavePublish = Callable[[str, bool], None]


class RunCommand(Protocol):
    """注入短命令执行器，清理调用允许不传取消回调。"""

    def __call__(
        self, cmd: list[str], *, timeout: float, cancelled: CancelCheck | None,
    ) -> CommandResult:
        """在给定预算内执行并返回统一状态，不拥有事务资源。"""
        ...


class CaptureCommand(Protocol):
    """将原始输出写入事务提供的文件，不改变字节内容。"""

    def __call__(
        self, cmd: list[str], output_path: str, *, timeout: float,
        cancelled: CancelCheck | None,
    ) -> CommandResult:
        """捕获输出后关闭执行资源，文件仍由调用事务清理。"""
        ...


def text_read_arguments(
    path: str, use_root: bool, byte_limit: int, completion_marker: bytes,
) -> list[str]:
    """在 worker 构造期冻结读取命令；构造异常保持同步传播。"""
    command = explorer_service.root_command(
        explorer_service.head_command(path, byte_limit + 1)
        + f" && printf %s {explorer_service.shell_quote(completion_marker.decode())}",
        use_root,
    )
    # 与目录和下载一致使用原始执行通道，不能在接收后改写换行来猜测原文。
    return ["exec-out", command]


def read_directory(
    device: str, path: str, use_root: bool, completion_marker: bytes, *,
    timeout: float, capture: CaptureCommand, cancelled: CancelCheck,
    publish: DirectoryPublish,
) -> None:
    """所有暂存文件由线程作用域清理；取消不交付结果，也不回退有歧义的 ls。"""
    if cancelled():
        return
    try:
        command = explorer_service.directory_list_command(path)
        command = explorer_service.root_command(
            f"({command}) && printf %s "
            + explorer_service.shell_quote(completion_marker.decode()), use_root,
        )
        with tempfile.TemporaryDirectory(prefix="adblab-directory-") as temporary:
            output = Path(temporary) / "listing"
            # 旧 adbd 的 shell -T 仍可能经过终端换行转换；exec-out 保留协议原始字节。
            result = capture(
                ["adb", "-s", device, "exec-out", command], str(output),
                timeout=timeout, cancelled=cancelled,
            )
            if cancelled():
                return
            if not result.success:
                outcome = command_outcome(result)
                if outcome == "cancelled":
                    return
                # 只报告错误类别，不能透传带设备标识、目录名称或本机路径的 stderr。
                detail = str(getattr(result, "error", "") or "").lower()
                if outcome == "timed_out":
                    message = "目录读取超时，请检查设备连接后重试。"
                elif "permission denied" in detail:
                    message = "目录读取被拒绝，请检查设备授权、目录访问权限及本机临时目录权限。"
                elif "unknown command" in detail or "not supported" in detail:
                    message = "ADB 或设备文件工具不支持目录读取，请检查客户端及设备工具。"
                else:
                    message = "目录读取失败，请检查设备连接、文件工具及本机临时目录。"
                publish(message, True)
                return
            limit = explorer_service.DIRECTORY_LIST_LIMIT + len(completion_marker)
            with output.open("rb") as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit or not raw.endswith(completion_marker):
                # exec-out 可能把远端 stderr 合入 stdout；没有尾标记时不能把它当目录解析。
                raise ValueError("设备目录列表不完整或过大，请检查连接及文件工具后重试。")
            listing = explorer_service.parse_directory_listing(
                raw[:-len(completion_marker)],
            )
        if not cancelled():
            publish(listing, False)
    except UnicodeError:
        if not cancelled():
            publish("目录包含非 UTF-8 名称，请在设备端重命名后刷新。", True)
    except ValueError as exc:
        if not cancelled():
            publish(str(exc), True)
    except OSError:
        if not cancelled():
            publish(
                "无法读写目录列表临时文件，请检查本机可用空间和临时目录权限。", True,
            )


def read_text(
    device: str, args: list[str], byte_limit: int, completion_marker: bytes, *,
    timeout: float, capture: CaptureCommand, cancelled: CancelCheck,
    decoded: Callable[[TextPreview], None], publish: TextPublish,
) -> None:
    """在成功、失败与取消路径都关闭并删除原始字节暂存文件。"""
    if cancelled():
        return
    try:
        with tempfile.TemporaryDirectory(prefix="adblab-text-read-") as temporary:
            path = Path(temporary) / "content"
            result = capture(
                ["adb", "-s", device] + args, str(path),
                timeout=timeout, cancelled=cancelled,
            )
            if cancelled():
                return
            if result.success:
                with path.open("rb") as stream:
                    raw = stream.read(byte_limit + 1 + len(completion_marker))
                # 旧设备可能不传递远端退出码，完成标记防止把命令错误当成可编辑正文。
                if not raw.endswith(completion_marker):
                    raise OSError("Unable to read complete text preview")
                raw = raw[:-len(completion_marker)]
                try:
                    preview = explorer_service.decode_text_preview(
                        raw, byte_limit,
                    )
                except (UnicodeError, ValueError):
                    preview = None
                if preview is not None:
                    decoded(preview)
                publish(raw, False)
            else:
                publish(result.error, True)
    except OSError as exc:
        if not cancelled():
            publish(str(exc), True)


def _text_shell(
    device: str, command: str, *, root: bool, cleanup: bool = False,
    run: RunCommand, cancelled: CancelCheck,
) -> CommandResult:
    """普通命令使用可取消预算，清理独立于操作取消并保持固定设备。"""
    return run(
        ["adb", "-s", device, "shell", explorer_service.root_command(command, root)],
        timeout=15 if cleanup else 30,
        cancelled=None if cleanup else cancelled,
    )


def _resolve_text_target(
    device: str, path: str, use_root: bool, *, capture: CaptureCommand,
    cancelled: CancelCheck,
) -> str:
    """按原始字节验证真实目标；取消或失败清理暂存，绝不使用有损解码的近似路径。"""
    command = explorer_service.root_command(
        explorer_service.resolve_text_target_command(path), use_root,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="adblab-text-target-") as temporary:
            output = Path(temporary) / "target"
            # 与读取正文一致使用 exec-out，防止旧 adbd 改写 readlink 的路径分隔符。
            result = capture(
                ["adb", "-s", device, "exec-out", command], str(output),
                timeout=30, cancelled=cancelled,
            )
            if cancelled():
                raise InterruptedError("Text save cancelled")
            if not result.success:
                raise OSError("Unable to resolve writable text file")
            with output.open("rb") as stream:
                raw = stream.read(8193)
    except OSError as exc:
        raise OSError("Unable to resolve writable text file") from exc
    prefix, suffix = b"ADBLAB_TARGET:", b"\n:END"
    if len(raw) > 8192 or not raw.startswith(prefix) or not raw.endswith(suffix):
        raise OSError("Unable to resolve writable text file")
    # suffix 只移除 readlink 的一个分隔换行；文件名自身的换行必须保留至拒绝。
    try:
        target = raw[len(prefix):-len(suffix)].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise OSError("Invalid text file target") from exc
    if not target.startswith("/") or any(char in target for char in "\0\r\n"):
        raise OSError("Invalid text file target")
    return target


def save_device_text(
    device: str, path: str, content: bytes, use_root: bool, *, timeout: float,
    run: RunCommand, capture: CaptureCommand, cancelled: CancelCheck,
    publish: SavePublish, warning: Callable[[str], None],
) -> None:
    """上传正文不进入 argv；发布前任一步失败保留原文件，终态晚于清理。"""
    if cancelled():
        return
    owned: list[tuple[str, bool]] = []
    error = ""
    try:
        target = _resolve_text_target(
            device, path, use_root, capture=capture, cancelled=cancelled,
        )
        token = uuid.uuid4().hex
        directory = posixpath.join(posixpath.dirname(target), f".adblab-save-{token}")
        upload_directory = (
            f"/data/local/tmp/adblab-save-{token}" if use_root else directory
        )
        for remote, root in [(directory, use_root)] + (
            [(upload_directory, False)] if use_root else []
        ):
            if cancelled():
                return
            # 即使命令返回在取消时丢失，归属标记仍允许收口本次已创建的目录。
            owned.append((remote, root))
            result = _text_shell(
                device, explorer_service.prepare_text_directory_command(remote),
                root=root, run=run, cancelled=cancelled,
            )
            if not result.success:
                raise OSError(result.error or "Unable to prepare text save")
        with tempfile.TemporaryDirectory(prefix="adblab-text-save-") as temporary:
            local = Path(temporary) / "content"
            local.write_bytes(content)
            if cancelled():
                return
            uploaded = f"{upload_directory}/upload"
            pushed = run(
                ["adb", "-s", device, "push", str(local), uploaded],
                timeout=timeout, cancelled=cancelled,
            )
            if not pushed.success:
                raise OSError(pushed.error or "Unable to upload text")
            if cancelled():
                return
            published = _text_shell(
                device,
                explorer_service.publish_text_command(target, directory, uploaded),
                root=use_root, run=run, cancelled=cancelled,
            )
            if not published.success:
                raise OSError(published.error or "Unable to publish text")
    except OSError as exc:
        error = str(exc)
    finally:
        for remote, root in reversed(owned):
            result = _text_shell(
                device,
                explorer_service.cleanup_text_directory_command(remote),
                root=root, run=run, cancelled=cancelled, cleanup=True,
            )
            if not result.success:
                # 正文已经发布，清理失败只影响设备端临时目录，不能改写保存结果。
                warning("文本保存临时文件清理失败，请检查设备连接。")
        if not cancelled():
            publish(error or "OK", bool(error))


def save_local_text(
    path: str, content: bytes, *, cancelled: CancelCheck, publish: SavePublish,
) -> None:
    """临时文件始终位于目标目录，发布后才发送成功。"""
    if cancelled():
        return
    temporary = ""
    error = ""
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=".adblab-save-", dir=str(Path(path).parent),
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        if cancelled():
            return
        os.replace(temporary, path)
    except OSError as exc:
        error = str(exc)
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError as exc:
                error = error or str(exc)
        if not cancelled():
            publish(error or "OK", bool(error))
