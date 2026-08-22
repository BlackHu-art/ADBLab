"""RuntimeData 每运行隔离契约测试（ADR-0004）。"""

import pytest

from mobileperf.android.globaldata import RuntimeData


@pytest.fixture(autouse=True)
def _reset_runtime_data():
    yield
    RuntimeData.end_run()


def test_runtime_data_class_level_fallback_without_active_run():
    assert RuntimeData._instance is None
    RuntimeData.packages = ["fallback"]
    assert RuntimeData.packages == ["fallback"]
    RuntimeData.packages = None


def test_begin_run_creates_isolated_instance():
    RuntimeData.begin_run()
    assert RuntimeData._instance is not None
    RuntimeData.packages = ["com.example.app"]
    RuntimeData.config_dic["key"] = "value"
    assert RuntimeData.packages == ["com.example.app"]
    assert RuntimeData.config_dic == {"key": "value"}


def test_end_run_clears_state_and_restores_fallback():
    RuntimeData.begin_run()
    RuntimeData.packages = ["session"]
    RuntimeData.end_run()

    assert RuntimeData._instance is None
    assert RuntimeData.packages is None


def test_consecutive_runs_do_not_leak_state():
    RuntimeData.begin_run()
    RuntimeData.packages = ["first"]
    RuntimeData.exit_event.set()
    RuntimeData.end_run()

    RuntimeData.begin_run()
    assert RuntimeData.packages is None
    assert not RuntimeData.exit_event.is_set()


def test_end_run_without_begin_is_idempotent():
    RuntimeData.end_run()
    assert RuntimeData._instance is None
