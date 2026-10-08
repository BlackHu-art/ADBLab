"""按 scrcpy 的设备能力列表选择匹配的视频编码与编码器。"""

import re
from dataclasses import dataclass

_VIDEO_ENCODER = re.compile(
    r"--video-codec=(h264|h265|av1)\s+--video-encoder="
    r"(['\"]?)([A-Za-z0-9_.:-]+)\2(?=\s|$)(?:\s+\((hw|sw|hybrid)\))?",
)
_CODEC_ORDER = {"h264": 0, "h265": 1, "av1": 2}


@dataclass(frozen=True)
class VideoEncoder:
    """保存设备声明的编码类型和精确名称，不把列表存在当作实机编码成功。"""

    codec: str
    name: str
    kind: str


def select_video_encoder(output: str) -> VideoEncoder | None:
    """优先已声明的硬件编码器，同类按 H.264、H.265、AV1 的兼容顺序选择。

    只接受 scrcpy 支持的视频类型；音频和其他视频类型不参与选择。
    旧 Android 不提供硬件标记时保留未知类型，不能仅凭厂商名称宣称硬件加速。
    """
    encoders = [
        VideoEncoder(match[1], match[3], match[4] or "unknown")
        for match in _VIDEO_ENCODER.finditer(output)
    ]
    return min(
        encoders, key=lambda encoder: (encoder.kind != "hw", _CODEC_ORDER[encoder.codec]),
        default=None,
    )
