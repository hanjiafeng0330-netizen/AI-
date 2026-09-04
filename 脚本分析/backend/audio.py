import subprocess
from pathlib import Path

import imageio_ffmpeg

from .config import WHISPER_MODEL_SIZE

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import whisper
        except ImportError:
            raise RuntimeError(
                "语音转写需要 openai-whisper，请安装: pip install openai-whisper"
            )
        # openai-whisper 模型名: tiny/base/small/medium/large
        model_name = WHISPER_MODEL_SIZE if WHISPER_MODEL_SIZE in (
            "tiny", "base", "small", "medium", "large"
        ) else "small"
        _whisper_model = whisper.load_model(model_name)
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
    result = model.transcribe(str(audio_path))
    return [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
        for seg in result["segments"]
        if seg["text"].strip()
    ]
