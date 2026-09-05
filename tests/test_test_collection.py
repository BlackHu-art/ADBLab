"""通过真实 pytest 收集验证混合测试模块的 Qt 分层。"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_qt_operation_nodes_are_ui_without_excluding_pure_operation_tests(tmp_path):
    root = Path(__file__).resolve().parents[1]
    capture = tmp_path / "collected.json"
    collector = tmp_path / "collect_markers.py"
    collector.write_text(textwrap.dedent("""
        import json
        from pathlib import Path
        import sys
        import pytest

        class Capture:
            def pytest_collection_finish(self, session):
                rows = {
                    item.name: sorted(marker.name for marker in item.iter_markers())
                    for item in session.items
                }
                Path(sys.argv[1]).write_text(json.dumps(rows), encoding="utf-8")

        raise SystemExit(pytest.main(
            ["--collect-only", "-q", "tests/test_phase1_operations.py"], plugins=[Capture()]
        ))
    """), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(collector), str(capture)], cwd=root,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = json.loads(capture.read_text(encoding="utf-8"))
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
