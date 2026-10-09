"""自动编码选择遵守设备能力、启动预算和精确客户端选择。"""

import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest

from core.exec import CommandResult
from services.remote.scrcpy_service import ScrcpyService
from services.remote.types import ScrcpyConfig


@pytest.fixture
def config(tmp_path):
    adb = tmp_path / "selected adb.exe"
    adb.touch()
    return ScrcpyConfig(
        exe="scrcpy.exe", adb=str(adb), device="fixture-device", maxsize="1280",
        fps="30", bitrate="8", codec="h265", buffer="20", orientation="0",
    )


def _runner(listing, *, success=True, on_listing=None):
    def run(command, **kwargs):
        if "--version" in command:
            return CommandResult(True, "scrcpy 4.1")
        if command[-1] == "echo ok":
            return CommandResult(True, "ok")
        if command[-1] == "wm size":
            return CommandResult(True, "Physical size: 1080x2400")
        if "--list-encoders" in command:
            if on_listing is not None:
                on_listing(kwargs)
            return CommandResult(success, listing, error="probe failed" if not success else "")
        pytest.fail(f"Unexpected query: {command}")

    return Mock(run=Mock(side_effect=run))


@pytest.mark.parametrize("listing,codec,encoder,kind", [
    (
        "--video-codec=h264 --video-encoder=OMX.google.h264.encoder (hybrid)\n"
        "--video-codec=vp8 --video-encoder=OMX.google.vp8.encoder (hybrid)",
        "h264", "OMX.google.h264.encoder", "hybrid",
    ),
    (
        "--video-codec=h265 --video-encoder=c2.vendor.hevc.encoder (hw) [vendor]\n"
        "--video-codec=h264 --video-encoder=c2.android.avc.encoder (sw)",
        "h265", "c2.vendor.hevc.encoder", "hw",
    ),
    (
        "--video-codec=h265 --video-encoder=c2.vendor.hevc.encoder (hw)\n"
        "--video-codec=h264 --video-encoder=c2.vendor.avc.encoder (hw)",
        "h264", "c2.vendor.avc.encoder", "hw",
    ),
    (
        "--video-codec=av1 --video-encoder=c2.vendor.av1.encoder (hw)",
        "av1", "c2.vendor.av1.encoder", "hw",
    ),
])
def test_plan_automatically_selects_matching_available_encoder(
    config, listing, codec, encoder, kind,
):
    runner = _runner(listing)
    plan = ScrcpyService(command_runner=runner).build_launch_plan(config)

    assert plan.codec == codec
    assert plan.encoder == encoder
    assert plan.encoder_kind == kind
    assert plan.args[plan.args.index("--video-encoder") + 1] == encoder
    if codec == "h264":
        assert "--video-codec" not in plan.args
    else:
        assert plan.args[plan.args.index("--video-codec") + 1] == codec
    query = runner.run.call_args_list[-1]
    assert query.args[0] == [config.exe, "-s", config.device, "--list-encoders"]
    assert query.kwargs["env"]["ADB"] == config.adb
    assert query.kwargs["native_tool"] is True


@pytest.mark.parametrize("listing,success", [
    ("", False),
    ("--audio-codec=opus --audio-encoder=c2.android.opus.encoder (sw)", True),
    ("--video-codec=h265 --video-encoder=c2.vendor.hevc.encoder (hw)", False),
])
def test_failed_or_unknown_probe_uses_explicit_h264_default(config, listing, success):
    plan = ScrcpyService(command_runner=_runner(listing, success=success)).build_launch_plan(config)
    assert plan.codec == "h264"
    assert plan.encoder is None
    assert "--video-codec" not in plan.args
    assert "--video-encoder" not in plan.args
    assert any(level == "WARNING" for level, _message in plan.messages)


@pytest.mark.parametrize("listing,codec,encoder", [
    (
        "--audio-codec=aac --audio-encoder=OMX.google.aac.encoder\n"
        "--audio-codec=flac --audio-encoder=OMX.google.flac.encoder",
        "aac", "OMX.google.aac.encoder",
    ),
    (
        "--audio-codec=aac --audio-encoder=OMX.google.aac.encoder (sw)\n"
        "--audio-codec=opus --audio-encoder=c2.android.opus.encoder (sw)",
        "opus", "c2.android.opus.encoder",
    ),
    (
        "--audio-codec=aac --audio-encoder='c2.android.aac.encoder' (sw)",
        "aac", "c2.android.aac.encoder",
    ),
])
def test_plan_selects_available_audio_encoder_without_disabling_sound(
    config, listing, codec, encoder,
):
    runner = _runner(
        "--video-codec=h264 --video-encoder=OMX.google.h264.encoder\n" + listing,
    )
    plan = ScrcpyService(command_runner=runner).build_launch_plan(replace(config, no_audio=False))

    assert "--audio-codec" in plan.args, "不能在设备无 Opus 编码器时继续隐式请求 Opus"
    assert plan.args[plan.args.index("--audio-codec") + 1] == codec
    assert plan.args[plan.args.index("--audio-encoder") + 1] == encoder
    assert "--no-audio" not in plan.args
    assert plan.encoder == "OMX.google.h264.encoder"
    assert sum("--list-encoders" in call.args[0] for call in runner.run.call_args_list) == 1


@pytest.mark.parametrize("no_audio,extra_args", [
    (True, []),
    (False, ["--no-audio"]),
    (False, ["--audio-codec=flac"]),
    (False, ["--audio-codec", "raw"]),
    (False, ["--audio-encoder=custom.audio.encoder"]),
    (False, ["--audio-encoder", "custom.audio.encoder"]),
])
def test_automatic_audio_selection_preserves_muting_and_explicit_arguments(
    config, no_audio, extra_args,
):
    plan = ScrcpyService(command_runner=_runner(
        "--audio-codec=aac --audio-encoder=OMX.google.aac.encoder",
    )).build_launch_plan(replace(config, no_audio=no_audio, extra_args=extra_args))

    assert "OMX.google.aac.encoder" not in plan.args
    assert "aac" not in plan.args
    if extra_args:
        assert plan.args[-len(extra_args) - 1:-1] == extra_args
    assert ("--no-audio" in plan.args) == (no_audio or "--no-audio" in extra_args)


@pytest.mark.parametrize("listing,success", [
    ("--audio-codec=aac --audio-encoder=OMX.google.aac.encoder", False),
    ("--video-codec=h264 --video-encoder=OMX.google.h264.encoder", True),
    ("--audio-codec=flac --audio-encoder=OMX.google.flac.encoder", True),
    ("--audio-codec=aac --audio-encoder=invalid;name", True),
])
def test_unknown_audio_capabilities_keep_requested_audio_enabled(config, listing, success):
    plan = ScrcpyService(command_runner=_runner(listing, success=success)).build_launch_plan(
        replace(config, no_audio=False),
    )

    assert "--audio-codec" not in plan.args
    assert "--audio-encoder" not in plan.args
    assert "--no-audio" not in plan.args


def test_encoder_probe_cancellation_prevents_plan_publication(config):
    stop = threading.Event()

    def cancel(kwargs):
        assert not kwargs["cancelled"]()
        stop.set()
        assert kwargs["cancelled"]()

    with pytest.raises(InterruptedError):
        ScrcpyService(command_runner=_runner("", on_listing=cancel)).build_launch_plan(
            config, cancelled=stop.is_set,
        )


def test_service_close_cancels_probe_before_it_can_publish_plan(config):
    service = None

    def close_service(kwargs):
        service.request_stop_encoder_probes()
        assert kwargs["cancelled"]()

    service = ScrcpyService(command_runner=_runner("", on_listing=close_service))
    with pytest.raises(InterruptedError):
        service.build_launch_plan(config)
    assert not service.encoder_probes_running()


def test_one_failed_probe_cleanup_does_not_block_other_devices():
    service = ScrcpyService()
    scopes = {Mock(), Mock()}
    first, second = tuple(scopes)
    first.wait.return_value = False
    first.is_running.return_value = True
    second.is_running.return_value = True

    def release(timeout):
        assert 0 < timeout <= 2
        second.is_running.return_value = False
        return True

    second.wait.side_effect = release
    service._encoder_scopes = scopes
    assert not service.wait_encoder_probes(2)
    first.wait.assert_called_once()
    second.wait.assert_called_once()
    assert service._encoder_scopes == {first}


def test_encoder_probe_uses_remaining_launch_budget(config, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("services.remote.scrcpy_service.time.monotonic", lambda: clock[0])

    def expire(kwargs):
        assert kwargs["timeout"] == 2
        clock[0] += 2

    with pytest.raises(TimeoutError):
        ScrcpyService(command_runner=_runner("", on_listing=expire)).build_launch_plan(
            config, timeout=2,
        )
