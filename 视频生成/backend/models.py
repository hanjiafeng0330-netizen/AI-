from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

PromptSource = Literal["jimeng", "kling"]
GenerationMode = Literal["text", "image"]
ServiceTier = Literal["default", "flex"]
JobStatus = Literal[
    "draft",
    "submitting",
    "submitted",
    "queued",
    "running",
    "succeeded",
    "downloading",
    "completed",
    "cancel_requested",
    "cancelled",
    "failed",
]


class VideoPromptSegment(BaseModel):
    role: str
    duration_sec: float | None = None
    jimeng_prompt: str
    kling_prompt: str


class SourceVariant(BaseModel):
    variant_title: str
    variant_style: str | None = None
    structure: list[dict[str, Any]] = Field(default_factory=list)
    video_prompts: list[VideoPromptSegment] = Field(default_factory=list)


class PromptSourceRecord(BaseModel):
    id: str
    title: str
    created_at: float | None = None
    origin: Literal["history", "results"]
    variants: list[SourceVariant] = Field(default_factory=list)


class PromptSourceSummary(BaseModel):
    id: str
    title: str
    created_at: float | None = None
    origin: Literal["history", "results"]
    variant_count: int


class SegmentSubmission(BaseModel):
    segment_index: int = Field(ge=0)
    prompt_source: PromptSource = "jimeng"
    prompt: str | None = None


class CreateBatchRequest(BaseModel):
    source_id: str = Field(min_length=4, max_length=128)
    variant_index: int = Field(ge=0)
    segments: list[SegmentSubmission] = Field(min_length=1)
    mode: GenerationMode = "text"
    model: str | None = None
    generate_audio: bool = False
    service_tier: ServiceTier | None = None
    duration: int = Field(default=5, ge=-1, le=30)
    ratio: str = "9:16"
    resolution: str = "720p"
    quantity: int = Field(default=1, ge=1, le=5)
    image_url: HttpUrl | None = None

    @field_validator("segments")
    @classmethod
    def unique_segments(cls, segments: list[SegmentSubmission]) -> list[SegmentSubmission]:
        indexes = [segment.segment_index for segment in segments]
        if len(indexes) != len(set(indexes)):
            raise ValueError("不能重复选择同一个分段")
        return segments


class ProviderSnapshot(BaseModel):
    task_id: str | None = None
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    result_urls: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ActualMedia(BaseModel):
    filename: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    ratio: str | None = None
    video_codec: str | None = None
    audio_streams: int | None = None
    audio_codec: str | None = None
    probe_status: Literal["available", "unavailable", "failed"] = "unavailable"


class SeedanceSettingsRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


class SeedanceSettingsStatus(BaseModel):
    configured: bool


class VideoTask(BaseModel):
    job_id: str
    batch_id: str
    source_id: str
    source_title: str
    variant_index: int
    variant_title: str
    segment_index: int
    role: str
    duration_sec: float | None = None
    requested_duration: int = 5
    ratio: str = "9:16"
    resolution: str = "720p"
    variation_index: int = 1
    prompt_source: PromptSource
    prompt: str
    mode: GenerationMode
    image_url: str | None = None
    model: str
    generate_audio: bool
    service_tier: ServiceTier | None = None
    status: JobStatus = "draft"
    provider_task_id: str | None = None
    provider_status: str | None = None
    provider_progress: int | None = Field(default=None, ge=0, le=100)
    progress: int = Field(default=0, ge=0, le=100)
    progress_label: str = "等待提交"
    error_code: str | None = None
    result_urls: list[str] = Field(default_factory=list)
    local_video_filenames: list[str] = Field(default_factory=list)
    local_video_filename: str | None = None
    actual_media: list[ActualMedia] = Field(default_factory=list)
    audio_status: Literal["requested", "detected", "not_detected", "unknown", "not_requested"] = "not_requested"
    download_error: str | None = None
    error_message: str | None = None
    created_at: float
    updated_at: float
    submitted_at: float | None = None
    completed_at: float | None = None
    last_polled_at: float | None = None
    poll_attempts: int = 0


class VideoBatch(BaseModel):
    batch_id: str
    source_id: str
    source_title: str
    variant_index: int
    variant_title: str
    status: str
    created_at: float
    updated_at: float
    item_ids: list[str] = Field(default_factory=list)


class BatchDetail(VideoBatch):
    items: list[VideoTask] = Field(default_factory=list)
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    cancelled_items: int = 0
    progress: int = 0
