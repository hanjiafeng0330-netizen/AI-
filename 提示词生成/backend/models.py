from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- 以下四个模型与「脚本分析/backend/models.py」的定义保持一致，
# ---- 用于原样解析脚本分析落盘的历史分析结果（两个工作台是独立项目，不共享 Python 包）。


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
    technique: str


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


class SourceScriptSummary(BaseModel):
    id: str
    created_at: float
    source_type: Literal["video", "text"]
    title: str
    hook_type: str | None = None


# ---- 通用 Prompt 调试信息，字段与脚本分析一致 ----


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


# ---- 产品资料库 ----


class Product(BaseModel):
    id: str
    name: str = Field(description="产品/书名")
    grade: str | None = Field(default=None, description="年级分类，如 小学/初中/高中")
    price: str | None = None
    original_price: str | None = None
    selling_points: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    authenticity_notes: str | None = Field(default=None, description="正版特征/防伪信息等")
    extra_notes: str | None = None
    created_at: float


class ProductCreateRequest(BaseModel):
    name: str
    grade: str | None = None
    price: str | None = None
    original_price: str | None = None
    selling_points: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    authenticity_notes: str | None = None
    extra_notes: str | None = None


# ---- 生成结果 ----


class NewStructureSegment(BaseModel):
    role: str = Field(description="hook / setup / buildup / climax / cta / other")
    summary: str
    duration_sec: float | None = None


class NewDialogueLine(BaseModel):
    segment_index: int = Field(description="对应 structure 数组的下标，从 0 开始")
    speaker: str | None = None
    text: str


class VideoPromptSegment(BaseModel):
    role: str
    duration_sec: float | None = None
    jimeng_prompt: str = Field(description="适配即梦的中文视频生成提示词")
    kling_prompt: str = Field(description="适配可灵的中文视频生成提示词")


class GeneratedScript(BaseModel):
    structure: list[NewStructureSegment] = Field(default_factory=list)
    dialogue: list[NewDialogueLine] = Field(default_factory=list)
    video_prompts: list[VideoPromptSegment] = Field(default_factory=list)


class ScriptVariant(GeneratedScript):
    variant_title: str = Field(description="创意方向标题，例如「情景剧·家长焦虑型」")
    variant_style: str = Field(description="一句话说明这版脚本的差异化创意点")


class VideoPromptEdit(BaseModel):
    jimeng_prompt: str | None = None
    kling_prompt: str | None = None


class ScriptState(BaseModel):
    status: Literal["pending", "adopted", "edited", "discarded"] = "pending"
    edited_plain_script: str | None = None
    edited_video_prompts: dict[str, VideoPromptEdit] = Field(default_factory=dict)


class GenerationResult(BaseModel):
    id: str | None = None
    scripts: list[ScriptVariant] = Field(default_factory=list)
    plain_scripts: list[str] = Field(default_factory=list, description="与 scripts 一一对应的纯文字脚本")
    prompt_trace: list[PromptStep]
    script_states: list[ScriptState] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    source_script_id: str
    product_id: str
    use_feedback_reference: bool = False
    script_count: int = Field(default=5, ge=1, le=5)


class HistoryEntry(BaseModel):
    id: str
    created_at: float
    title: str
    source_script_id: str
    product_id: str
    result: GenerationResult


class HistorySummary(BaseModel):
    id: str
    created_at: float
    title: str
    source_script_id: str
    product_id: str
    product_name: str | None = None
    product_grade: str | None = None
