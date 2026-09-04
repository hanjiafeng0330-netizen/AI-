import subprocess
from pathlib import Path

import imageio_ffmpeg

from .config import WHISPER_MODEL_SIZE

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def extract_audio(video_path: Path, out_path: Path) -> Path:
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"抽取音频失败: {result.stderr[-2000:]}")
    return out_path


def transcribe_audio(audio_path: Path) -> list[dict]:
    model = _get_whisper_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return [
        {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        for seg in segments
        if seg.text.strip()
    ]
