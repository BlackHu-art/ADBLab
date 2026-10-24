"""应用只读查询事务；执行、取消、时钟及结果回调均由调用方显式提供。"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal, Protocol

from services.apps.package_details import (
    _DETAIL_BEGIN,
    _DETAIL_END,
    InstalledApp,
    PackageDetail,
    has_package_detail,
    is_safe_package,
    parse_batch_detail,
    parse_installed_apps,
    split_package_detail_sections,
)

if TYPE_CHECKING:
    from core.exec import CommandResult
    from services.app_metadata import AppMetadata, MetadataBatch

Cancelled = Callable[[], bool]
Clock = Callable[[], float]
QueryBudget = Callable[[], float]
MetadataLoader = Callable[[str, Sequence[str], Cancelled], 'MetadataBatch']


class QueryExecutor(Protocol):
    """仅注入已经固定设备的执行器；只读事务显式传递取消语义。"""

    def __call__(self, *args: str, timeout: float = 30,
                 cancellable: bool = False) -> CommandResult: ...


class QueryError(Exception):
    """预期查询失败；异常文本沿用原有可操作错误提示。"""


def _is_user_id(value: object) -> bool:
    return type(value) is int and 0 <= value < 2**31


def validate_loaded_user(user_id: object, *, required: bool) -> None:
    """写入需要已绑定用户；可选身份只允许 None 或实际整型编号，拒绝 bool。"""
    if user_id is None and not required:
        return
    if not _is_user_id(user_id):
        raise QueryError('尚未确认应用所属用户，请刷新应用列表后重试。')


def parse_current_user(output: str) -> int | None:
    """仅接受设备输出的有界 ASCII 用户编号，未知输出不猜测用户 0。"""
    text = output.strip()
    if not re.fullmatch(r'[0-9]{1,10}', text):
        return None
    user_id = int(text)
    return user_id if _is_user_id(user_id) else None


def read_current_user(*, execute: QueryExecutor, cancelled: Cancelled,
                      timeout: float) -> int | None:
    """执行一次可取消用户探测；失败、取消及未知输出均返回 None。"""
    result = execute('shell', 'am', 'get-current-user', timeout=timeout, cancellable=True)
    if cancelled() or not result.success:
        return None
    return parse_current_user(result.stdout)


def bind_current_user(expected_user: int | None, *, read_user: Callable[[], int | None],
                      cancelled: Cancelled) -> int | None:
    """只读一次当前用户；优先服从取消，已绑定身份不随设备切换自动改绑。"""
    current = read_user()
    if cancelled():
        return None
    if current is None:
        raise QueryError('无法确认设备当前用户，请检查设备并刷新应用列表。')
    if expected_user is not None and current != expected_user:
        raise QueryError('设备用户已切换，请刷新应用列表后重试。')
    return current


def load_installed_apps(user_id: int, *, execute: QueryExecutor,
                        cancelled: Cancelled) -> list[InstalledApp] | None:
    """同一显式用户的列表与禁用状态都成功后才返回结果；取消返回 None。"""
    result = execute('shell', 'pm', 'list', 'packages', '-f', '--user',
                     str(user_id), cancellable=True)
    if cancelled():
        return None
    if not result.success:
        error = str(getattr(result, 'error', '') or '').strip()
        raise QueryError(f"Failed to list apps: {error or 'adb command failed'}")
    disabled = execute('shell', 'pm', 'list', 'packages', '-d', '--user',
                       str(user_id), cancellable=True)
    if cancelled():
        return None
    if not disabled.success:
        raise QueryError('Failed to read disabled app states; refresh to retry')
    # 解析后不增加取消检查，adapter 必须先保留 Loaded 日志再按原门禁发布。
    return parse_installed_apps(result.stdout, disabled.stdout)


def read_package_snapshot(package: str, part: Literal['details', 'permissions'], *,
                          execute: QueryExecutor, cancelled: Cancelled) -> str | None:
    """一次快照供详情和权限共用；命令失败或无版本字段不伪造成功载荷。"""
    if not is_safe_package(package):
        raise QueryError(f'Invalid package: {package}')
    result = execute('shell', f'dumpsys package {package}', cancellable=True)
    if cancelled():
        return None
    if not result.success or not has_package_detail(result.stdout):
        raise QueryError(f'Failed to read app {part}; retry after checking the device')
    return result.stdout


def _load_package_details_once(packages: Sequence[str], *, deadline: float,
                               execute: QueryExecutor, cancelled: Cancelled, clock: Clock,
                               on_detail: Callable[[PackageDetail], None],
                               log: Callable[[str], None]) -> list[str]:
    """只对未闭合片段允许兼容查询；失败、取消或无预算时不重试。"""
    script_parts = []
    for i, package in enumerate(packages):
        script_parts.extend([
            f'echo {_DETAIL_BEGIN.format(i)}', f'dumpsys package {package}',
            f'echo {_DETAIL_END.format(i)}',
        ])
    remaining = deadline - clock()
    if cancelled() or remaining <= 0:
        return []
    result = execute('shell', ' ; '.join(script_parts), timeout=remaining, cancellable=True)
    if cancelled():
        return []
    if not result.success:
        log('Failed to read app details; refresh to retry')
        return []
    sections = split_package_detail_sections(result.stdout, len(packages))
    missing = []
    for i, package in enumerate(packages):
        if cancelled():
            return []
        output = sections.get(i, '')
        if has_package_detail(output):
            # 原发布门禁位于解析前；解析期间到来的取消不撤回本条已准入记录。
            if not cancelled():
                on_detail(parse_batch_detail(package, output))
        elif i not in sections:
            missing.append(package)
        if i % 10 == 0:
            log(f'Details: {i + 1}/{len(packages)}')
    return missing


def load_package_details(packages: Sequence[str], *, execute: QueryExecutor,
                         cancelled: Cancelled, query_budget: QueryBudget, clock: Clock,
                         on_detail: Callable[[PackageDetail], None], log: Callable[[str], None],
                         deadline: float | None = None) -> None:
    """批量及逐包兼容查询共享截止时间，已完成记录可在取消前逐条交付。"""
    if not packages or cancelled():
        return
    command_budget = query_budget()
    if deadline is None:
        deadline = clock() + max(command_budget, len(packages) * 2)
    safe_packages = [package for package in packages if is_safe_package(package)]
    if len(safe_packages) != len(packages):
        log('Invalid package names skipped while reading details')
    if not safe_packages:
        return
    remaining_packages = _load_package_details_once(
        safe_packages, deadline=deadline, execute=execute, cancelled=cancelled, clock=clock,
        on_detail=on_detail, log=log,
    )
    for package in remaining_packages:
        remaining = deadline - clock()
        if cancelled() or remaining <= 0:
            return
        result = execute('shell', f'dumpsys package {package}',
                         timeout=min(command_budget, remaining), cancellable=True)
        if cancelled():
            return
        if not result.success:
            log('Failed to read app details; refresh to retry')
            return
        if has_package_detail(result.stdout):
            if not cancelled():
                on_detail(parse_batch_detail(package, result.stdout))


def load_metadata_with_fallback(device_id: str, packages: Sequence[str], *,
                                expected_user: int | None, execute: QueryExecutor,
                                cancelled: Cancelled, query_budget: QueryBudget, clock: Clock,
                                metadata_loader: MetadataLoader,
                                on_metadata: Callable[[AppMetadata], None],
                                on_detail: Callable[[PackageDetail], None],
                                log: Callable[[str], None], failure: Callable[[str], None]) -> None:
    """helper 仅明确不支持且无记录时共用剩余预算兼容；记录身份逐条核验。"""
    if not packages or cancelled():
        return
    deadline = clock() + 30.0
    result = metadata_loader(device_id, packages, cancelled)
    if cancelled():
        return
    if result.unsupported and not result.records:
        if clock() < deadline:
            load_package_details(
                packages, deadline=deadline, execute=execute, cancelled=cancelled,
                query_budget=query_budget, clock=clock, on_detail=on_detail, log=log,
            )
        return
    for item in result.records.values():
        if cancelled():
            return
        if expected_user is not None and item.user_id != expected_user:
            failure('设备用户已切换，请刷新应用列表后重试。')
            continue
        on_metadata(item)
    if len(result.records) < len(set(packages)):
        log('部分应用信息未读取，请刷新重试。')
