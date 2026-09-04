from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from .config import (
    IMAGE_TO_VIDEO_MODEL,
    MAX_BATCH_ITEMS,
    MAX_PROMPT_CHARS,
    MAX_QUANTITY_PER_SEGMENT,
    MODEL_CAPABILITIES,
    POLL_INITIAL_SECONDS,
    POLL_MAX_SECONDS,
    SEEDANCE_DEFAULT_MODEL,
)
from .history import get_batch, get_job, list_jobs, save_batch, save_job
from .input_loader import get_source
from .models import BatchDetail, CreateBatchRequest, VideoBatch, VideoTask
from .seedance_provider import ProviderError, SeedanceProvider

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"submitted", "queued", "running", "succeeded", "downloading", "cancel_requested"}


class JobService:
    def __init__(self, provider: SeedanceProvider | None = None):
        self.provider = provider or SeedanceProvider()
        self._pollers: dict[str, asyncio.Task] = {}

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _batch_status(items: list[VideoTask]) -> str:
        statuses = {item.status for item in items}
        if not statuses:
            return "processing"
        if statuses <= {"completed"}:
            return "completed"
        if statuses <= {"failed"}:
            return "failed"
        if statuses <= {"cancelled"}:
            return "cancelled"
        if statuses <= TERMINAL_STATUSES:
            return "partial_failed"
        return "processing"

    @staticmethod
    def _set_stage(task: VideoTask, status: str, provider_progress: int | None = None) -> None:
        task.status = status
        task.provider_progress = provider_progress
        if status == "draft":
            task.progress, task.progress_label = 0, "等待提交"
        elif status == "submitting":
            task.progress, task.progress_label = 3, "正在提交任务"
        elif status in {"submitted", "queued"}:
            task.progress, task.progress_label = 10, "排队等待生成"
        elif status == "running":
            task.progress = provider_progress if provider_progress is not None else 45
            task.progress_label = "正在生成视频"
        elif status == "succeeded":
            task.progress, task.progress_label = 90, "视频已生成，等待下载"
        elif status == "downloading":
            task.progress, task.progress_label = 95, "正在下载成品"
        elif status == "completed":
            task.progress, task.progress_label = 100, "已完成"
        elif status == "cancel_requested":
            task.progress_label = "正在请求取消"
        elif status == "cancelled":
            task.progress_label = "已取消"
        elif status == "failed":
            task.progress_label = "生成失败"

    def _save_task(self, task: VideoTask) -> VideoTask:
        task.updated_at = self._now()
        save_job(task)
        self._update_batch(task.batch_id)
        return task

    def _update_batch(self, batch_id: str) -> None:
        batch = get_batch(batch_id)
        items = [get_job(item_id) for item_id in batch.item_ids]
        batch.status = self._batch_status(items)
        batch.updated_at = self._now()
        save_batch(batch)

    def batch_detail(self, batch_id: str) -> BatchDetail:
        batch = get_batch(batch_id)
        items = [get_job(item_id) for item_id in batch.item_ids]
        total = len(items)
        completed = sum(item.status == "completed" for item in items)
        failed = sum(item.status == "failed" for item in items)
        cancelled = sum(item.status == "cancelled" for item in items)
        progress = round(sum(item.progress for item in items) / total) if total else 0
        return BatchDetail(
            **batch.model_dump(),
            items=items,
            total_items=total,
            completed_items=completed,
            failed_items=failed,
            cancelled_items=cancelled,
            progress=progress,
        )

    @staticmethod
    def validate_request(request: CreateBatchRequest, model: str) -> None:
        capability = MODEL_CAPABILITIES.get(model)
        if not capability:
            raise ValueError("不支持的模型")
        if request.mode not in capability["modes"]:
            raise ValueError("所选模型不支持当前生成类型")
        if request.generate_audio and not capability["audio"]:
            raise ValueError("所选模型不支持原生音频，请切换到 Seedance 1.5 Pro 后再开启音频")
        if request.duration not in capability["durations"]:
            raise ValueError("所选模型不支持当前时长")
        if request.ratio not in capability["ratios"]:
            raise ValueError("所选模型不支持当前画面比例")
        if request.resolution not in capability["resolutions"]:
            raise ValueError("所选模型不支持当前清晰度")

    async def create_batch(self, request: CreateBatchRequest) -> BatchDetail:
        if len(request.segments) > MAX_BATCH_ITEMS:
            raise ValueError(f"单次最多选择 {MAX_BATCH_ITEMS} 个分段")
        if request.quantity > MAX_QUANTITY_PER_SEGMENT:
            raise ValueError(f"每个分段最多生成 {MAX_QUANTITY_PER_SEGMENT} 条视频")
        if len(request.segments) * request.quantity > MAX_BATCH_ITEMS:
            raise ValueError(f"单次最多创建 {MAX_BATCH_ITEMS} 个视频任务，请减少分段或生成数量")
        if request.mode == "image" and not request.image_url:
            raise ValueError("图生视频需要提供公开 HTTPS 图片 URL")

        source = get_source(request.source_id)
        if request.variant_index >= len(source.variants):
            raise ValueError("脚本变体不存在")
        variant = source.variants[request.variant_index]
        model = request.model or (IMAGE_TO_VIDEO_MODEL if request.mode == "image" else SEEDANCE_DEFAULT_MODEL)
        self.validate_request(request, model)
        now = self._now()
        batch = VideoBatch(
            batch_id=self._id("batch"),
            source_id=source.id,
            source_title=source.title,
            variant_index=request.variant_index,
            variant_title=variant.variant_title,
            status="processing",
            created_at=now,
            updated_at=now,
        )
        save_batch(batch)

        for submission in request.segments:
            if submission.segment_index >= len(variant.video_prompts):
                raise ValueError(f"分段 {submission.segment_index + 1} 不存在")
            prompt_segment = variant.video_prompts[submission.segment_index]
            prompt = (submission.prompt or getattr(prompt_segment, f"{submission.prompt_source}_prompt")).strip()
            if not prompt:
                raise ValueError(f"分段 {submission.segment_index + 1} 的提示词为空")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError(f"分段 {submission.segment_index + 1} 的提示词超过 {MAX_PROMPT_CHARS} 字符")

            for variation_index in range(1, request.quantity + 1):
                task = VideoTask(
                    job_id=self._id("job"),
                    batch_id=batch.batch_id,
                    source_id=source.id,
                    source_title=source.title,
                    variant_index=request.variant_index,
                    variant_title=variant.variant_title,
                    segment_index=submission.segment_index,
                    role=prompt_segment.role,
                    duration_sec=prompt_segment.duration_sec,
                    requested_duration=request.duration,
                    ratio=request.ratio,
                    resolution=request.resolution,
                    variation_index=variation_index,
                    prompt_source=submission.prompt_source,
                    prompt=prompt,
                    mode=request.mode,
                    image_url=str(request.image_url) if request.image_url else None,
                    model=model,
                    generate_audio=request.generate_audio,
                    audio_status="requested" if request.generate_audio else "not_requested",
                    service_tier=request.service_tier,
                    created_at=now,
                    updated_at=now,
                )
                batch.item_ids.append(task.job_id)
                save_job(task)

        save_batch(batch)
        for job_id in batch.item_ids:
            await self.submit(job_id)
        return self.batch_detail(batch.batch_id)

    async def submit(self, job_id: str) -> VideoTask:
        task = get_job(job_id)
        if task.status != "draft":
            return task
        self._set_stage(task, "submitting")
        self._save_task(task)
        try:
            snapshot = await self.provider.create_task(task)
        except ProviderError as exc:
            self._set_stage(task, "failed")
            task.error_message = str(exc)
            task.error_code = exc.error_code
            return self._save_task(task)

        task.provider_task_id = snapshot.task_id
        task.provider_status = snapshot.status
        task.error_code = snapshot.error_code
        task.error_message = snapshot.error_message
        self._set_stage(task, snapshot.status if snapshot.status in {"queued", "running", "succeeded", "cancelled", "failed"} else "submitted", snapshot.progress)
        task.submitted_at = self._now()
        if task.status == "succeeded":
            task.result_urls = snapshot.result_urls
        self._save_task(task)
        if task.status == "succeeded":
            await self._download_if_ready(task.job_id)
        elif task.status not in TERMINAL_STATUSES:
            self._start_poller(task.job_id)
        return get_job(job_id)

    def _start_poller(self, job_id: str) -> None:
        running = self._pollers.get(job_id)
        if running and not running.done():
            return
        self._pollers[job_id] = asyncio.create_task(self._poll_until_terminal(job_id))

    async def _poll_until_terminal(self, job_id: str) -> None:
        interval = POLL_INITIAL_SECONDS
        while True:
            await asyncio.sleep(interval)
            try:
                task = await self.refresh(job_id)
            except (FileNotFoundError, ValueError):
                return
            if task.status in TERMINAL_STATUSES:
                return
            interval = min(interval * 1.5, POLL_MAX_SECONDS)

    async def refresh(self, job_id: str) -> VideoTask:
        task = get_job(job_id)
        if task.status in TERMINAL_STATUSES or not task.provider_task_id:
            return task
        try:
            snapshot = await self.provider.get_task(task.provider_task_id)
        except ProviderError as exc:
            task.error_message = str(exc)
            task.last_polled_at = self._now()
            task.poll_attempts += 1
            return self._save_task(task)

        task.provider_status = snapshot.status
        task.error_code = snapshot.error_code
        task.last_polled_at = self._now()
        task.poll_attempts += 1
        task.result_urls = snapshot.result_urls or task.result_urls
        if snapshot.error_message:
            task.error_message = snapshot.error_message
        if snapshot.status in {"queued", "running", "failed", "cancelled", "succeeded"}:
            self._set_stage(task, snapshot.status, snapshot.progress)
        if task.status == "failed":
            task.error_message = task.error_message or "远端视频生成失败"
            task.completed_at = self._now()
        elif task.status == "cancelled":
            task.completed_at = self._now()
        self._save_task(task)
        if task.status == "succeeded":
            await self._download_if_ready(task.job_id)
        return get_job(job_id)

    async def cancel(self, job_id: str) -> VideoTask:
        task = get_job(job_id)
        if task.status in TERMINAL_STATUSES:
            return task
        self._set_stage(task, "cancel_requested")
        self._save_task(task)
        if not task.provider_task_id:
            self._set_stage(task, "cancelled")
            task.completed_at = self._now()
            return self._save_task(task)
        try:
            snapshot = await self.provider.cancel_task(task.provider_task_id)
            task.provider_status = snapshot.status
            task.result_urls = snapshot.result_urls or task.result_urls
            self._set_stage(task, "cancelled" if snapshot.status != "succeeded" else "succeeded", snapshot.progress)
        except ProviderError as exc:
            self._set_stage(task, "failed")
            task.error_message = str(exc)
        task.completed_at = self._now()
        self._save_task(task)
        if task.status == "succeeded":
            await self._download_if_ready(task.job_id)
        return get_job(job_id)

    async def retry_download(self, job_id: str) -> VideoTask:
        task = get_job(job_id)
        if not task.result_urls:
            raise ValueError("该任务还没有可下载的视频地址")
        await self._download_if_ready(job_id)
        return get_job(job_id)

    async def _download_if_ready(self, job_id: str) -> None:
        # 远端可能未来返回多个成片；先完整保留 URL，当前可访问媒体路由逐个下载。
        task = get_job(job_id)
        if task.local_video_filenames or task.local_video_filename or not task.result_urls:
            return
        self._set_stage(task, "downloading")
        self._save_task(task)
        # 当前 OpenProxy 实测只提供一条 video_url，扩展模型仍保存 list 以兼容未来多结果。
        task.download_error = None
        try:
            from .downloads import download_videos

            filenames, audio_status, actual_media = await download_videos(task.job_id, task.result_urls)
            task.local_video_filename = filenames[0]
            task.local_video_filenames = filenames
            task.actual_media = actual_media
            task.audio_status = audio_status if task.generate_audio else "not_requested"
            self._set_stage(task, "completed")
            task.completed_at = self._now()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self._set_stage(task, "succeeded")
            task.download_error = f"视频下载失败：{exc}"
        # 远端 URL 可能带临时签名；下载流程结束后不再把它写回历史任务文件或 API 响应。
        task.result_urls = []
        self._save_task(task)

    def restore_polling(self) -> None:
        for task in list_jobs():
            if task.status in ACTIVE_STATUSES and task.provider_task_id:
                self._start_poller(task.job_id)
