"""core.process_utils 的纯单元测试：端口占用查找与进程树终止。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psutil
import pytest

from core.process_utils import find_pids_listening_on, kill_process_tree, process_name


def _conn(status, port, pid):
    conn = SimpleNamespace(status=status, laddr=SimpleNamespace(ip="0.0.0.0", port=port), pid=pid)
    return conn


def test_find_pids_listening_on_returns_deduped_pids():
    conns = [
        _conn(psutil.CONN_LISTEN, 5037, 111),
        _conn(psutil.CONN_LISTEN, 5037, 111),  # 同一 PID 的 IPv4/IPv6 双监听
        _conn(psutil.CONN_ESTABLISHED, 5037, 222),
        _conn(psutil.CONN_LISTEN, 9999, 333),
    ]
    with patch("psutil.net_connections", return_value=conns):
        assert find_pids_listening_on(5037) == [111]


def test_find_pids_listening_on_returns_partial_when_access_denied():
    with patch("psutil.net_connections", side_effect=psutil.AccessDenied()):
        assert find_pids_listening_on(5037) == []


def test_find_pids_listening_on_rejects_invalid_port():
    with pytest.raises(ValueError):
        find_pids_listening_on(0)
    with pytest.raises(ValueError):
        find_pids_listening_on("5037")


def test_process_name_returns_empty_on_missing_process():
    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(123)):
        assert process_name(123) == ""


def test_kill_process_tree_terminates_children_then_parent():
    parent = MagicMock()
    child = MagicMock()
    parent.children.return_value = [child]
    with patch("psutil.Process", return_value=parent):
        ok, detail = kill_process_tree(123)
    assert ok is True
    assert detail == "terminated"
    assert child.terminate.called
    assert parent.terminate.called
    parent.wait.assert_called()


def test_kill_process_tree_already_exited_reports_success():
    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(123)):
        ok, detail = kill_process_tree(123)
    assert ok is True
    assert detail == "already-exited"


def test_kill_process_tree_access_denied_reports_failure():
    with patch("psutil.Process", side_effect=psutil.AccessDenied(123, "denied")):
        ok, detail = kill_process_tree(123)
    assert ok is False
    assert detail
