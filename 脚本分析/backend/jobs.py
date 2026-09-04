import json
import time
import uuid
from pathlib import Path

from . import history
from .analyzer import analyze_video
from .audio import extract_audio, transcribe_audio
from .config import AUDIO_DIR, FRAMES_DIR, RESULTS_DIR
from .frames import extract_frames
from .models import HistoryEntry, JobStatus

_JOBS: dict[str, JobStatus] = {}


def create_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = JobStatus(job_id=job_id, status="pending")
    return job_id


def get_job(job_id: str) -> JobStatus | None:
    return _JOBS.get(job_id)


def _save_result(job_id: str, result_json: dict) -> None:
    result_path = RESULTS_DIR / f"{job_id}.json"
    result_path.write_text(json.dumps(result_json, ensure_ascii=False, indent=2), encoding="utf-8")


def run_video_pipeline(
    job_id: str, video_path: Path, frame_interval_sec: float, original_filename: str
) -> None:
    job = _JOBS[job_id]
    job.status = "processing"
    try:
        audio_path = extract_audio(video_path, AUDIO_DIR / f"{job_id}.wav")
        transcript_segments = transcribe_audio(audio_path)

        frames = extract_frames(video_path, FRAMES_DIR / job_id, frame_interval_sec)

        result, prompt_trace = analyze_video(frames, transcript_segments, frame_interval_sec)

        _save_result(job_id, result.model_dump())
        job.result = result
        job.prompt_trace = prompt_trace
        job.status = "done"

        history.save_entry(
            HistoryEntry(
                id=job_id,
                created_at=time.time(),
                source_type="video",
                title=original_filename,
                video_filename=video_path.name,
                result=result,
                prompt_trace=prompt_trace,
            )
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
