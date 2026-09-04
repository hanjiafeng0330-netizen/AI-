from typing import Any, Literal

from pydantic import BaseModel, Field


class StructureSegment(BaseModel):
    start: float | None = None
    end: float | None = None
    role: str = Field(description="hook / setup / buildup / climax / cta / other")
    summary: str


class DialogueLine(BaseModel):
    start: float | None = None
    end: float | None = None
    speaker: str | None = None
    text: str


class VisualElement(BaseModel):
    timestamp: float
    description: str
    technique: str = Field(description="转场/构图/字幕样式/镜头运动 等标签")


class ReusableTemplate(BaseModel):
    hook_type: str
    pacing_seconds: float | None = None
    visual_style: str | None = None
    cta_style: str | None = None
    tags: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    source_type: Literal["video", "text"]
    structure: list[StructureSegment] = Field(default_factory=list)
    dialogue: list[DialogueLine] = Field(default_factory=list)
    visual: list[VisualElement] = Field(default_factory=list)
    template: ReusableTemplate


class ModelConfig(BaseModel):
    model: str
    temperature: float | None = None
    max_tokens: int


class PromptMetadata(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed_ms: float | None = None
    cost_usd: float | None = None


class PromptStep(BaseModel):
    label: str
    system_prompt: str | None = None
    user_prompt: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    final_prompt: str
    model_params: ModelConfig
    response: str | None = None
    metadata: PromptMetadata


class JobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "processing", "done", "error"]
    result: AnalysisResult | None = None
    prompt_trace: list[PromptStep] | None = None
    error: str | None = None


class AnalysisResponse(BaseModel):
    result: AnalysisResult
    prompt_trace: list[PromptStep]


class TextAnalyzeRequest(BaseModel):
    script_text: str


class HistoryEntry(BaseModel):
    id: str
    created_at: float
    source_type: Literal["video", "text"]
    title: str
    video_filename: str | None = None
    result: AnalysisResult
    prompt_trace: list[PromptStep]


class HistorySummary(BaseModel):
    id: str
    created_at: float
    source_type: Literal["video", "text"]
    title: str
