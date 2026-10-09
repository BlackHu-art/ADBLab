"""从 scrcpy 能力列表选择常用音频编码，兼容没有 Opus 的设备。"""

import re
from dataclasses import dataclass

_AUDIO_ENCODER = re.compile(
    r"--audio-codec=(opus|aac)\s+--audio-encoder="
    r"(['\"]?)([A-Za-z0-9_.:-]+)\2(?=\s|$)",
)
_CODEC_ORDER = {"opus": 0, "aac": 1}


@dataclass(frozen=True)
class AudioEncoder:
    """保存设备声明的音频类型和匹配名称，启动仍负责确认编码器能否工作。"""

    codec: str
    name: str


def select_audio_encoder(output: str) -> AudioEncoder | None:
    """优先保留 Opus，设备未声明 Opus 时选择 AAC；未知列表不假定支持或静音。"""
    encoders = [
        AudioEncoder(match[1], match[3])
        for match in _AUDIO_ENCODER.finditer(output)
    ]
    return min(encoders, key=lambda encoder: _CODEC_ORDER[encoder.codec], default=None)
