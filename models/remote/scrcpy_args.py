"""Pure scrcpy argument construction."""

from .types import ScrcpyConfig


def _size_value(size: str) -> str:
    return size.replace("p", "")


def build_scrcpy_args(config: ScrcpyConfig, encoder: str | None = None) -> list[str]:
    args = [config.exe, "-s", config.device]

    if config.maxsize != "Default":
        args.extend(["-m", _size_value(config.maxsize)])

    args.extend(["--max-fps", config.fps])
    args.append(f"--video-bit-rate={config.bitrate}M")

    if config.codec != "h264":
        args.extend(["--video-codec", config.codec])
    if config.buffer != "0":
        args.append(f"--video-buffer={config.buffer}")
    if config.orientation != "0":
        args.append(f"--lock-video-orientation={config.orientation}")
    if encoder:
        args.extend(["--video-encoder", encoder])

    if config.fullscreen:
        args.append("-f")
    if config.always_on_top:
        args.append("--always-on-top")
    if config.no_audio:
        args.append("--no-audio")
    if config.show_touches:
        args.append("--show-touches")
    if config.stay_awake:
        args.append("--stay-awake")
    if config.turn_screen_off:
        args.append("--turn-screen-off")
    if config.record_path:
        args.extend(["--record", config.record_path])
    if config.no_window:
        args.extend(["--no-playback", "--no-window"])

    args.extend(config.extra_args)
    args.append("--print-fps")
    return args
