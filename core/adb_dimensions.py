"""纯解析 Android wm size 输出，为投屏和输入共享有效逻辑尺寸。"""

import re

_SIZE_LINE = re.compile(r"(Physical|Override) size:\s*([0-9]+)x([0-9]+)")


def parse_wm_size(output: str) -> list[str] | None:
    """只接受独立的正整数尺寸行；有效 Override 优先于物理尺寸。"""
    physical = None
    for line in output.splitlines():
        match = _SIZE_LINE.fullmatch(line.strip())
        if match is None:
            continue
        kind, width, height = match.groups()
        if not width.strip("0") or not height.strip("0"):
            continue
        dimensions = [width, height]
        if kind == "Override":
            return dimensions
        physical = dimensions
    return physical
