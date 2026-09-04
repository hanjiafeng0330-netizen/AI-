from pathlib import Path

import cv2

from .config import MAX_FRAMES


def extract_frames(
    video_path: Path,
    out_dir: Path,
    interval_sec: float,
    max_frames: int = MAX_FRAMES,
) -> list[tuple[float, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_step = max(1, round(fps * interval_sec))

    frames: list[tuple[float, Path]] = []
    frame_idx = 0
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % frame_step == 0:
            timestamp = frame_idx / fps
            frame_path = out_dir / f"frame_{len(frames):04d}.jpg"
            cv2.imwrite(str(frame_path), frame)
            frames.append((timestamp, frame_path))
        frame_idx += 1

    cap.release()
    if not frames:
        raise RuntimeError("未能从视频中抽取到任何帧")
    return frames
