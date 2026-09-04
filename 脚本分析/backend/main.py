import re
import shutil
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import history
from .analyzer import analyze_text_script
from .config import AVAILABLE_MODELS, BASE_DIR, DEFAULT_FRAME_INTERVAL_SEC, RESULTS_DIR, VIDEOS_DIR, get_openai_base_url, get_openai_model, is_configured, save_openai_settings
from .jobs import create_job, get_job, run_video_pipeline
from .models import (
    AnalysisResponse,
    HistoryEntry,
    HistorySummary,
    JobStatus,
    OpenAISettingsRequest,
    OpenAISettingsStatus,
    TextAnalyzeRequest,
)

app = FastAPI(title="脚本分析工作台")

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
STREAM_CHUNK_SIZE = 1024 * 1024


@app.get("/api/settings/openai", response_model=OpenAISettingsStatus)
def api_openai_settings_status():
    return OpenAISettingsStatus(
        configured=is_configured(),
        model=get_openai_model(),
        base_url=get_openai_base_url(),
    )


@app.put("/api/settings/openai", response_model=OpenAISettingsStatus)
def api_save_openai_settings(request: OpenAISettingsRequest):
    try:
        save_openai_settings(request.api_key, request.model, request.base_url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpenAISettingsStatus(
        configured=True,
        model=request.model,
        base_url=request.base_url,
    )


@app.get("/api/settings/models")
def api_list_models():
    return AVAILABLE_MODELS


@app.post("/api/analyze/text", response_model=AnalysisResponse)
def analyze_text(req: TextAnalyzeRequest) -> AnalysisResponse:
    if not req.script_text.strip():
        raise HTTPException(status_code=400, detail="脚本文本不能为空")
    result, prompt_trace = analyze_text_script(req.script_text)
    result_id = uuid.uuid4().hex[:12]
    (RESULTS_DIR / f"{result_id}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    title = req.script_text[:40] + ("…" if len(req.script_text) > 40 else "")
    history.save_entry(
        HistoryEntry(
            id=result_id,
            created_at=time.time(),
            source_type="text",
            title=title,
            result=result,
            prompt_trace=prompt_trace,
        )
    )
    return AnalysisResponse(result=result, prompt_trace=prompt_trace)


@app.post("/api/analyze/video")
def analyze_video_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    frame_interval_sec: float = Form(DEFAULT_FRAME_INTERVAL_SEC),
) -> dict:
    job_id = create_job()
    video_path = VIDEOS_DIR / f"{job_id}_{file.filename}"
    with video_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    background_tasks.add_task(
        run_video_pipeline, job_id, video_path, frame_interval_sec, file.filename
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str) -> JobStatus:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在")
    return job


@app.get("/api/history", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    return history.list_entries()


@app.get("/api/history/{entry_id}", response_model=HistoryEntry)
def get_history(entry_id: str) -> HistoryEntry:
    entry = history.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return entry


@app.get("/media/videos/{filename}")
def stream_video(filename: str, request: Request) -> StreamingResponse:
    path = (VIDEOS_DIR / filename).resolve()
    if VIDEOS_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="视频不存在")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    status_code = 200
    if range_header:
        match = RANGE_RE.match(range_header)
        if match:
            status_code = 206
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = min(int(match.group(2)), file_size - 1)

    chunk_size = end - start + 1

    def iter_range():
        with path.open("rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(STREAM_CHUNK_SIZE, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return StreamingResponse(
        iter_range(), status_code=status_code, media_type="video/mp4", headers=headers
    )


STATIC_DIR = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
