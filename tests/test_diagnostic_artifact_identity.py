from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from controllers._app import ADBAppMixin
from controllers._media import ADBMediaMixin
from models.adb_testing import ADBTesting


def test_bugreport_same_time_owns_new_directory_and_never_converts_old_files(tmp_path):
    model = ADBTesting()

    def run(argv, **kwargs):
        if "getprop" in argv:
            return {"success": True, "output": "13.0"}
        (Path(argv[-1]) / "bugreport-current.txt").write_text("report")
        return {"success": True}

    with (
        patch.object(model, "_run", side_effect=run),
        patch.object(model, "_convert_bugreport_to_html") as convert,
        patch("models.adb_testing.datetime") as clock,
    ):
        clock.now.return_value.strftime.return_value = "123456"
        first = model.capture_bugreport_async.__wrapped__(model, "mock-device", str(tmp_path), 1)
        old = Path(first["bugreport_path"]) / "bugreport-old.txt"
        old.write_text("old")
        convert.reset_mock()
        second = model.capture_bugreport_async.__wrapped__(model, "mock-device", str(tmp_path), 1)
    assert first["bugreport_path"] != second["bugreport_path"]
    assert old.read_text() == "old"
    assert len(convert.call_args_list) == 1
    assert str(second["bugreport_path"]) in convert.call_args.args[0]


def test_anr_directory_is_unique_even_with_same_requested_name(tmp_path):
    model = ADBTesting()
    with patch.object(model, "_run", return_value={"success": True}):
        results = [
            model.pull_anr_files_async.__wrapped__(
                model, "mock-device", "same-anr", str(tmp_path), 1
            )
            for _ in range(2)
        ]
    assert results[0]["artifact_path"] != results[1]["artifact_path"]


def test_log_exports_same_second_get_unique_paths(tmp_path):
    controller = SimpleNamespace(
        testing_model=Mock(),
        advanced_model=Mock(),
        _require_devices=lambda *args: True,
        _get_screenshot_dir=lambda: str(tmp_path),
    )
    with (
        patch("controllers._app.datetime") as appclock,
        patch("controllers._media.datetime") as mediaclock,
    ):
        for clock in (appclock, mediaclock):
            clock.now.return_value.strftime.return_value = "123456"
        for _ in range(2):
            ADBAppMixin._save_single_device_log(controller, "mock-device", str(tmp_path))
            ADBMediaMixin.logcat_filtered(controller, ["mock-device"])
    for command in (
        controller.testing_model.retrieve_device_logs_async,
        controller.advanced_model.logcat_filtered_async,
    ):
        assert command.call_args_list[0].args[1] != command.call_args_list[1].args[1]


def test_bugreport_conversion_failure_does_not_use_prior_report(tmp_path):
    model = ADBTesting()
    prior = tmp_path / "historical" / "bugreport-old.txt"
    prior.parent.mkdir()
    prior.write_text("old report")

    def run(argv, **kwargs):
        if "getprop" in argv:
            return {"success": True, "output": "13.0"}
        (Path(argv[-1]) / "bugreport-current.txt").write_text("current report")
        return {"success": True}

    with (
        patch.object(model, "_run", side_effect=run),
        patch.object(
            model, "_convert_bugreport_to_html", side_effect=RuntimeError("conversion failed")
        ) as convert,
    ):
        result = model.capture_bugreport_async.__wrapped__(model, "mock-device", str(tmp_path), 1)
    assert result["success"]
    assert prior.read_text() == "old report"
    assert convert.call_count == 1
    assert str(result["bugreport_path"]) in convert.call_args.args[0]
