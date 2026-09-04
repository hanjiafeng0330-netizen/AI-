import json
from pathlib import Path

import backend.downloads as downloads


def test_probe_media_extracts_actual_properties(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture")
    monkeypatch.setattr(downloads, "_ffprobe_path", lambda: "/usr/local/bin/ffprobe")

    class Result:
        returncode = 0
        stdout = json.dumps({
            "format": {"duration": "5.12"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        })

    monkeypatch.setattr(downloads.subprocess, "run", lambda *args, **kwargs: Result())
    media = downloads.probe_media(video)
    assert media.probe_status == "available"
    assert media.duration_sec == 5.12
    assert (media.width, media.height, media.ratio) == (720, 1280, "9:16")
    assert media.audio_streams == 1


def test_probe_media_handles_missing_ffprobe(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture")
    monkeypatch.setattr(downloads, "_ffprobe_path", lambda: None)
    assert downloads.probe_media(video).probe_status == "unavailable"
