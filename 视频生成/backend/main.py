from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ALLOWED_MODELS, PROJECT_ROOT, VIDEOS_DIR, public_model_catalog, save_seedance_api_key, seedance_is_configured
from .history import list_batches
from .input_loader import get_source, list_sources
from .jobs import JobService
from .models import BatchDetail, CreateBatchRequest, SeedanceSettingsRequest, SeedanceSettingsStatus, VideoBatch

service = JobService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    service.restore_polling()
    yield


app = FastAPI(title="视频生成工作台", lifespan=lifespan)


@app.get("/api/settings/seedance", response_model=SeedanceSettingsStatus)
def api_seedance_settings_status():
    return SeedanceSettingsStatus(configured=seedance_is_configured())


@app.put("/api/settings/seedance", response_model=SeedanceSettingsStatus)
def api_save_seedance_settings(request: SeedanceSettingsRequest):
    try:
        save_seedance_api_key(request.api_key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SeedanceSettingsStatus(configured=True)


@app.get("/api/models")
def api_list_models():
    return public_model_catalog()


@app.get("/api/sources")
def api_list_sources():
    return list_sources()


@app.get("/api/sources/{source_id}")
def api_get_source(source_id: str):
    try:
        return get_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sources/{source_id}/variants/{variant_index}")
def api_get_variant(source_id: str, variant_index: int):
    try:
        source = get_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if variant_index < 0 or variant_index >= len(source.variants):
        raise HTTPException(status_code=404, detail="未找到脚本变体")
    return source.variants[variant_index]


@app.post("/api/batches", response_model=BatchDetail)
async def api_create_batch(request: CreateBatchRequest):
    model = request.model
    if model and model not in ALLOWED_MODELS:
        raise HTTPException(status_code=422, detail="不支持的模型")
    if request.mode == "image" and request.image_url and request.image_url.scheme != "https":
        raise HTTPException(status_code=422, detail="图生视频仅接受公开 HTTPS 图片 URL")
    try:
        return await service.create_batch(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/batches", response_model=list[VideoBatch])
def api_list_batches():
    return list_batches()


@app.get("/api/batches/{batch_id}", response_model=BatchDetail)
def api_batch_detail(batch_id: str):
    try:
        return service.batch_detail(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频批次") from exc


@app.post("/api/batches/{batch_id}/refresh", response_model=BatchDetail)
async def api_refresh_batch(batch_id: str):
    try:
        detail = service.batch_detail(batch_id)
        for item in detail.items:
            await service.refresh(item.job_id)
        return service.batch_detail(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频批次") from exc


@app.delete("/api/batches/{batch_id}/items/{job_id}")
async def api_cancel_item(batch_id: str, job_id: str):
    try:
        current = service.batch_detail(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频批次") from exc
    if job_id not in current.item_ids:
        raise HTTPException(status_code=404, detail="该任务不属于此批次")
    try:
        return await service.cancel(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频任务") from exc


@app.post("/api/batches/{batch_id}/items/{job_id}/retry-download")
async def api_retry_download(batch_id: str, job_id: str):
    try:
        current = service.batch_detail(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频批次") from exc
    if job_id not in current.item_ids:
        raise HTTPException(status_code=404, detail="该任务不属于此批次")
    try:
        return await service.retry_download(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到视频任务") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/media/videos/{filename}")
def api_video(filename: str):
    path = (VIDEOS_DIR / filename).resolve()
    if path.parent != VIDEOS_DIR.resolve() or path.suffix != ".mp4" or not path.is_file():
        raise HTTPException(status_code=404, detail="未找到本地视频")
    return FileResponse(path, media_type="video/mp4", filename=filename)


app.mount("/", StaticFiles(directory=PROJECT_ROOT / "static", html=True), name="static")
