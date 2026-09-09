"""查询预算只读取已安装运行时的能力，不触发任何设备命令。"""

from unittest.mock import Mock, patch

import pytest


@pytest.mark.parametrize("fast_ready, expected", [(True, 5), (False, 15)])
def test_query_timeout_uses_only_cached_capability(fast_ready, expected):
    from core.adb_query import query_timeout

    runtime = Mock(spec=["can_shell_fast"])
    runtime.can_shell_fast.return_value = fast_ready
    with (
        patch("core.adb_query.adb_runtime", return_value=runtime),
        patch("core.adb_query.resolve_adb_program", return_value="resolved-adb") as resolve,
    ):
        assert query_timeout("device-1", 5) == expected
    runtime.can_shell_fast.assert_called_once_with("resolved-adb", "device-1")
    resolve.assert_called_once_with()


def test_query_timeout_without_runtime_retains_native_and_larger_caller_budget():
    from core.adb_query import query_timeout

    with patch("core.adb_query.adb_runtime", return_value=None):
        assert query_timeout("device-1", 5) == 15
        assert query_timeout("device-1", 20) == 20
        assert query_timeout("device-1", 5, native=30) == 30


def test_query_timeout_uses_explicit_adb_path_without_resolving_default():
    from core.adb_query import query_timeout

    runtime = Mock(spec=["can_shell_fast"])
    runtime.can_shell_fast.return_value = True
    with (
        patch("core.adb_query.adb_runtime", return_value=runtime),
        patch("core.adb_query.resolve_adb_program") as resolve,
    ):
        assert query_timeout("device-1", 3, adb_path="custom-adb") == 3
    runtime.can_shell_fast.assert_called_once_with("custom-adb", "device-1")
    resolve.assert_not_called()
