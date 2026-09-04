from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx

from .config import DOWNLOAD_TIMEOUT_SECONDS, MAX_DOWNLOAD_BYTES, VIDEO_FFPROBE_PATH, VIDEOS_DIR
from .models import ActualMedia


def _ffprobe_path() -> str | None:
    if VIDEO_FFPROBE_PATH:
        candidate = Path(VIDEO_FFPROBE_PATH)
        return str(candidate) if candidate.is_file() and candidate.exists() else None
    return shutil.which("ffprobe")


def _format_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    from math import gcd

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def probe_media(path: Path) -> ActualMedia:
    ffprobe = _ffprobe_path()
    fallback = ActualMedia(filename=path.name, probe_status="unavailable")
    if not ffprobe:
        return fallback
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            return ActualMedia(filename=path.name, probe_status="failed")
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return ActualMedia(filename=path.name, probe_status="failed")

    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    duration = (data.get("format") or {}).get("duration")
    try:
        duration_sec = round(float(duration), 2) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None
    width = video.get("width") if isinstance(video.get("width"), int) else None
    height = video.get("height") if isinstance(video.get("height"), int) else None
    return ActualMedia(
        filename=path.name,
        duration_sec=duration_sec,
        width=width,
        height=height,
        ratio=_format_ratio(width, height),
        video_codec=video.get("codec_name") if isinstance(video.get("codec_name"), str) else None,
        audio_streams=len(audio),
        audio_codec=audio[0].get("codec_name") if audio and isinstance(audio[0].get("codec_name"), str) else None,
        probe_status="available",
    )


async def download_videos(job_id: str, urls: list[str]) -> tuple[list[str], str, list[ActualMedia]]:
    filenames: list[str] = []
    timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            for index, url in enumerate(urls, start=1):
                filename = f"{job_id}-{index}.mp4" if len(urls) > 1 else f"{job_id}.mp4"
                destination = VIDEOS_DIR / filename
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        written = 0
                        with destination.open("wb") as file:
                            async for chunk in response.aiter_bytes():
                                written += len(chunk)
                                if written > MAX_DOWNLOAD_BYTES:
                                    raise ValueError("视频文件超过本地大小限制")
                                file.write(chunk)
                    filenames.append(filename)
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
    except Exception:
        for filename in filenames:
            (VIDEOS_DIR / filename).unlink(missing_ok=True)
        raise

    media = await asyncio.gather(*(asyncio.to_thread(probe_media, VIDEOS_DIR / name) for name in filenames))
    if any(item.audio_streams for item in media):
        audio_status = "detected"
    elif media and all(item.probe_status == "available" for item in media):
        audio_status = "not_detected"
    else:
        audio_status = "unknown"
    return filenames, audio_status, media
