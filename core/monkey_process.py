"""Monkey 远端进程租约；按启动身份停止，不扫描或终止同名外部任务。"""

from __future__ import annotations

import os
import shlex
import uuid
from collections.abc import Callable
from pathlib import Path

from core.owned_process import SCOPE_ENV


class MonkeyProcessLease:
    """每次启动独占目录和 PID/starttime；未确认退出时保留租约供重试。

    启动与停止共享取消标记。启动尚未发布身份时停止不能报告成功；晚到启动
    读到标记后写入确认，下一次停止才可释放目录。设备不可达时不按名称降级。
    """

    def __init__(self) -> None:
        self.token = uuid.uuid4().hex
        self.path = f"/data/local/tmp/adblab-monkey-{self.token}"
        self.released = False
        self._local_obligation: Path | None = None

    def _release_local_obligation(self) -> None:
        """远端确认后原子退役标记；父进程中途退出也不会重新成为活动义务。"""
        if self._local_obligation is not None:
            retired = self._local_obligation.with_name(".done-" + self._local_obligation.name)
            self._local_obligation.rename(retired)
            self._local_obligation = None
            retired.rmdir()

    def discard_unsubmitted(self) -> None:
        """仅本机 spawn 明确失败时调用；未提交设备的租约不应阻塞父进程收尾。"""
        self.released = True
        self._release_local_obligation()

    @staticmethod
    def _identity_function() -> str:
        # comm 可能包含空格或括号，先删去最后一个右括号以前的内容。
        return (
            'identity() { [ -d "/proc/$1" ] || { printf GONE; return; }; '
            'stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1; '
            'stat=${stat##*) }; set -- $stat; '
            '[ "$1" = Z ] && { printf GONE; return; }; '
            '[ "$#" -ge 20 ] || return 1; shift 19; printf "%s" "$1"; }; '
        )

    def command(self, arguments: list[str]) -> str:
        """构造保留 PID 的 exec 包装；全部业务动态参数按 shell 单参数转义。"""
        scope = os.environ.get(SCOPE_ENV)
        if scope and self._local_obligation is None:
            self._local_obligation = Path(scope) / f"remote-{self.token}"
            self._local_obligation.mkdir()
        script = (
            f"d={shlex.quote(self.path)}; mkdir -p \"$d\" || exit 125; "
            + self._identity_function()
            + 'birth=$(identity $$) || exit 125; '
            'printf "%s %s\\n" "$$" "$birth" > "$d/identity.tmp" || exit 125; '
            'mv "$d/identity.tmp" "$d/identity" || exit 125; '
            'if [ -e "$d/cancel" ]; then touch "$d/done"; exit 130; fi; '
            f"exec {shlex.join(arguments)}"
        )
        return "sh -c " + shlex.quote(script)

    def stop(self, run: Callable[[str], str]) -> bool:
        """只终止仍匹配 PID/starttime 的任务；返回值必须包含本租约确认标记。"""
        if self.released:
            self._release_local_obligation()
            return True
        marker = f"ADBLAB_MONKEY_STOPPED_{self.token}"
        script = (
            f"d={shlex.quote(self.path)}; mkdir -p \"$d\" || exit 125; "
            'touch "$d/cancel" || exit 125; '
            + self._identity_function()
            + 'read pid birth < "$d/identity" || exit 125; '
            'case "$pid:$birth" in *[!0-9:]*|:*|*:) exit 125;; esac; '
            '[ "$pid" -gt 1 ] || exit 125; '
            'for signal in TERM KILL; do '
            'current=$(identity "$pid") || exit 125; '
            'if [ "$current" != "$birth" ]; then break; fi; '
            'kill -"$signal" "$pid" || exit 125; '
            'n=0; while [ "$n" -lt 10 ]; do '
            'current=$(identity "$pid") || exit 125; [ "$current" != "$birth" ] && break; '
            'sleep 0.1; n=$((n+1)); done; done; '
            'current=$(identity "$pid") || exit 125; [ "$current" != "$birth" ] || exit 125; '
            # 只移除本次随机目录内协议规定的文件，拒绝递归删除未知内容。
            'rm -f "$d/identity" "$d/identity.tmp" "$d/cancel" "$d/done" && '
            f'rmdir "$d" && printf "%s\\n" {marker}'
        )
        output = run("sh -c " + shlex.quote(script))
        self.released = isinstance(output, str) and marker in output.splitlines()
        if self.released:
            self._release_local_obligation()
        return self.released
