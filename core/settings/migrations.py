"""原地迁移历史设置字典；诊断由调用方显式提供，不访问设置文件。"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from core.settings.schema import DEFAULTS

Reporter = Callable[[str, str], None]


def legacy_panel_ratio(left_width: Any, right_width: Any) -> float:
    """把旧版左右像素宽度迁移为受限的左栏比例。"""

    try:
        left = max(0.0, float(left_width))
        right = max(0.0, float(right_width))
    except (TypeError, ValueError, OverflowError):
        return DEFAULTS["panel_split_ratio"]
    total = left + right
    if total <= 0:
        return DEFAULTS["panel_split_ratio"]
    return max(0.2, min(0.7, left / total))


def stored_schema_version(stored: dict) -> int:
    """读取存储字典的 schema 版本；缺失或非正整数一律视为 v1（种子时代）。"""

    version = stored.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return 1
    return max(1, version)


def migrate_1_to_2(stored: dict, report: Reporter) -> None:
    """v1 → v2：折算面板比例并补齐缺失键，用户已设值一律不动（ADR-0006）。"""

    if "panel_split_ratio" not in stored:
        stored["panel_split_ratio"] = legacy_panel_ratio(
            stored.get("left_panel_width"),
            stored.get("right_panel_width"),
        )
    for key, default in DEFAULTS.items():
        if key not in stored:
            stored[key] = deepcopy(default)
    monkey = stored.get("monkey_params")
    if isinstance(monkey, dict):
        merged = deepcopy(DEFAULTS["monkey_params"])
        merged.update(monkey)
        stored["monkey_params"] = merged
    else:
        stored["monkey_params"] = deepcopy(DEFAULTS["monkey_params"])


def migrate_2_to_3(stored: dict, report: Reporter) -> None:
    """v2 → v3：剔除未知键（含 monkey_params 内的死键）并记录警告（ADR-0006）。"""

    prune_unknown_keys(stored, report)


def run_migrations(stored: dict, from_version: int, report: Reporter) -> None:
    """按版本升序对存储字典做原地结构迁移。"""

    for version in range(from_version, CURRENT_SCHEMA_VERSION):
        migration = _MIGRATIONS.get(version)
        if migration is not None:
            migration(stored, report)


def prune_unknown_keys(stored: dict, report: Reporter) -> None:
    """剔除未知顶层键与未知 monkey_params 键，每类一次性记录警告。"""

    unknown = sorted(
        str(key) for key in stored if key not in DEFAULTS and key != "schema_version"
    )
    for key in unknown:
        stored.pop(key, None)
    if unknown:
        report(
            "WARNING",
            f"Ignored {len(unknown)} unknown settings key(s): {', '.join(unknown)}",
        )
    monkey = stored.get("monkey_params")
    if not isinstance(monkey, dict):
        return
    monkey_defaults = DEFAULTS["monkey_params"]
    monkey_unknown = sorted(str(key) for key in monkey if key not in monkey_defaults)
    for key in monkey_unknown:
        monkey.pop(key, None)
    if monkey_unknown:
        report(
            "WARNING",
            f"Ignored {len(monkey_unknown)} unknown monkey_params key(s): "
            f"{', '.join(monkey_unknown)}",
        )


_MIGRATIONS: dict[int, Callable[[dict, Reporter], None]] = {
    1: migrate_1_to_2,
    2: migrate_2_to_3,
}
CURRENT_SCHEMA_VERSION = max(_MIGRATIONS) + 1
