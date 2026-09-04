from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .config import BATCHES_DIR, JOBS_DIR
from .models import VideoBatch, VideoTask

T = TypeVar("T", bound=BaseModel)


def _atomic_write(path: Path, data: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read(path: Path, model_type: type[T]) -> T:
    with path.open("r", encoding="utf-8") as file:
        return model_type.model_validate(json.load(file))


def save_job(job: VideoTask) -> None:
    _atomic_write(JOBS_DIR / f"{job.job_id}.json", job)


def get_job(job_id: str) -> VideoTask:
    return _read(JOBS_DIR / f"{job_id}.json", VideoTask)


def list_jobs() -> list[VideoTask]:
    jobs: list[VideoTask] = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            jobs.append(_read(path, VideoTask))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return jobs


def save_batch(batch: VideoBatch) -> None:
    _atomic_write(BATCHES_DIR / f"{batch.batch_id}.json", batch)


def get_batch(batch_id: str) -> VideoBatch:
    return _read(BATCHES_DIR / f"{batch_id}.json", VideoBatch)


def list_batches() -> list[VideoBatch]:
    batches: list[VideoBatch] = []
    for path in BATCHES_DIR.glob("*.json"):
        try:
            batches.append(_read(path, VideoBatch))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(batches, key=lambda batch: batch.created_at, reverse=True)
