"""通过真实 pytest 收集验证混合测试模块的 Qt 分层。"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


def _run_pytest(tmp_path, arguments, *, block_qt=False):
    """在独立解释器中执行项目夹具，并捕获真实选择结果及成功用例。"""
    root = Path(__file__).resolve().parents[1]
    capture = tmp_path / "pytest_result.json"
    runner = textwrap.dedent("""
        import importlib.abc
        import json
        from pathlib import Path
        import sys

        if sys.argv[2] == "block-qt":
            class RejectQt(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".")[0] in {"PySide6", "qfluentwidgets"}:
                        raise AssertionError("Pure test attempted Qt import: " + fullname)
            sys.meta_path.insert(0, RejectQt())

        import pytest

        class Capture:
            def __init__(self):
                self.rows = {}
                self.passed = []

            def pytest_collection_finish(self, session):
                self.rows = {
                    item.nodeid: sorted(marker.name for marker in item.iter_markers())
                    for item in session.items
                }

            def pytest_runtest_logreport(self, report):
                if report.when == "call" and report.passed:
                    self.passed.append(report.nodeid)

        capture = Capture()
        result = pytest.main(sys.argv[3:], plugins=[capture])
        Path(sys.argv[1]).write_text(json.dumps({
            "collected": capture.rows,
            "passed": capture.passed,
            "qt_modules": sorted(name for name in sys.modules
                                 if name.split(".")[0] in {"PySide6", "qfluentwidgets"}),
        }), encoding="utf-8")
        raise SystemExit(result)
    """)
    result = subprocess.run(
        [sys.executable, "-c", runner, str(capture),
         "block-qt" if block_qt else "allow-qt", "-c", str(root / "pyproject.toml"), *arguments],
        cwd=root,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(capture.read_text(encoding="utf-8"))


def test_qt_operation_nodes_are_ui_without_excluding_pure_operation_tests(tmp_path):
    result = _run_pytest(tmp_path, ["--collect-only", "-q", "tests/test_phase1_operations.py"])
    collected = {node.rsplit("::", 1)[-1]: marks for node, marks in result["collected"].items()}
    qt_nodes = {
        "test_async_command_keeps_signal_signature_and_strips_reserved_operation_kwargs",
        "test_async_command_carries_manager_generation_without_forwarding_it_to_model_method",
        "test_async_command_carries_owner_token_without_forwarding_it_to_model_method",
        "test_async_command_reports_business_runtime_error_with_same_operation_metadata",
        "test_async_command_long_running_routes_to_long_pool",
        "test_command_task_runs_in_real_thread_pool_and_emits_finished",
    }
    assert {name for name, markers in collected.items() if "ui" in markers} == qt_nodes
    non_ui = {name for name, markers in collected.items() if "ui" not in markers}
    pure_operation = (
        "test_operation_state_machine_cleans_terminal_entry_and_ignores_duplicate_finish"
    )
    assert pure_operation in non_ui


def test_action_markers_select_gui_feedback_and_only_qt_result_nodes(tmp_path):
    files = ["tests/test_action_feedback.py", "tests/test_action_results.py"]
    all_nodes = _run_pytest(tmp_path, ["--collect-only", "-q", *files])["collected"]
    feedback = {node for node in all_nodes if node.startswith(files[0] + "::")}
    qt_results = {
        files[1] + "::" + name for name in (
            "test_async_model_preserves_action_identity_and_original_operation_protocol",
            "test_native_screenshot_partial_batch_keeps_last_successful_unit_successful",
            "test_model_submission_error_ends_action_without_leaving_a_running_job",
            "test_automatic_recording_pull_creates_one_media_result_per_device",
        )
    }
    assert feedback
    expected_ui = feedback | qt_results
    assert {node for node, marks in all_nodes.items() if "ui" in marks} == expected_ui
    for expression, expected in (("ui", expected_ui), ("not ui", set(all_nodes) - expected_ui)):
        selected = _run_pytest(
            tmp_path, ["--collect-only", "-q", "-m", expression, *files],
        )["collected"]
        assert set(selected) == expected


def test_pure_logic_executes_when_qt_imports_are_forbidden(tmp_path):
    result = _run_pytest(tmp_path, [
        "-q", "-m", "not ui", "tests/test_adb_values.py",
        "tests/test_run_library.py",
        "tests/test_action_results.py::test_progress_is_not_success_and_multiple_targets_finish_once",
        "tests/test_action_results.py::test_notes_are_bounded_by_source_and_rejected_after_close",
    ], block_qt=True)
    assert result["collected"]
    assert set(result["passed"]) == set(result["collected"])
    assert result["qt_modules"] == []


def test_ui_fixture_dispatch_preserves_state_and_storage_between_test_kinds(tmp_path):
    probe = tmp_path / "test_fixture_dispatch.py"
    probe.write_text(textwrap.dedent("""
        import sys
        import pytest

        state = {}

        @pytest.fixture
        def application_indirectly(qt_application):
            return qt_application

        def test_pure_before_ui():
            assert "PySide6" not in sys.modules
            assert "gui.run_library" not in sys.modules

        def test_unmarked_indirect_fixture(application_indirectly, tmp_path):
            from PySide6.QtCore import QTimer
            from PySide6.QtGui import QFont
            from PySide6.QtWidgets import QWidget
            from gui.styles import BaseStyles
            from gui import run_library
            from services.run_library import RunLibrary

            state["application"] = application_indirectly
            state["font"] = application_indirectly.font().toString()
            state["theme"] = BaseStyles.current_theme()
            assert run_library.user_data_root() == tmp_path
            assert RunLibrary.for_user().path.parent == tmp_path
            state["window"] = window = QWidget()
            state["destroyed"] = []
            window.destroyed.connect(lambda: state["destroyed"].append(True))
            timer = QTimer(window)
            timer.start(1000)
            application_indirectly.setFont(QFont("Arial", 19))
            BaseStyles.switch_theme("Dark" if state["theme"] == "Light" else "Light")

        @pytest.mark.ui
        def test_marker_without_application_argument(tmp_path):
            from PySide6.QtWidgets import QApplication, QWidget
            from gui.styles import BaseStyles
            from gui import run_library
            from shiboken6 import isValid

            assert QApplication.instance() is state["application"]
            assert QApplication.font().toString() == state["font"]
            assert BaseStyles.current_theme() == state["theme"]
            assert not isValid(state["window"])
            assert state["destroyed"] == [True]
            assert run_library.user_data_root() == tmp_path
            state["marked_window"] = QWidget()

        def test_pure_after_ui(tmp_path):
            from shiboken6 import isValid

            assert not isValid(state["marked_window"])
            assert sys.modules["gui.run_library"].user_data_root() == tmp_path
    """), encoding="utf-8")
    result = _run_pytest(tmp_path, [
        "-q", "-p", "tests.conftest", "--confcutdir", str(tmp_path), str(probe),
    ])
    assert len(result["passed"]) == 4


def test_registered_ui_functions_exist_and_carry_the_ui_marker(tmp_path):
    """按函数名登记的 Qt 用例改名或漏登记后，必须在收集期失败而不是静默失去隔离。"""

    from tests.conftest import _INTEGRATION_TEST_FILES, _UI_TEST_FILES, _UI_TEST_FUNCTIONS

    # 文件级名单相交时，elif 会静默吞掉 integration 标记，先在这里拦住。
    assert not set(_UI_TEST_FILES) & set(_INTEGRATION_TEST_FILES)
    targets = sorted(_UI_TEST_FUNCTIONS)
    collected = _run_pytest(
        tmp_path, ["--collect-only", "-q", *[f"tests/{name}" for name in targets]],
    )["collected"]
    for name in targets:
        # 与 conftest 一致按 originalname 匹配：参数化用例的收集名带 [param] 后缀。
        available = {
            node.rsplit("::", 1)[-1].partition("[")[0]: marks
            for node, marks in collected.items()
            if node.startswith(f"tests/{name}::")
        }
        registered = set(_UI_TEST_FUNCTIONS[name])
        missing = sorted(registered - set(available))
        assert not missing, f"{name} 登记的用例不存在：{missing}"
        unmarked = sorted(item for item in registered if "ui" not in available[item])
        assert not unmarked, f"{name} 登记的用例缺少 ui 标记：{unmarked}"
