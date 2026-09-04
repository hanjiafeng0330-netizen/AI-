import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import history, products, source_scripts
from .config import AVAILABLE_MODELS, BASE_DIR, RESULTS_DIR, get_openai_model, is_configured, save_openai_settings
from .generator import generate_scripts, render_plain_script
from .models import (
    AnalysisResult,
    GenerateRequest,
    GenerationResult,
    HistoryEntry,
    HistorySummary,
    Product,
    ProductCreateRequest,
    ScriptState,
    SourceScriptSummary,
)

app = FastAPI(title="提示词生成工作台")


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """开发中静态资源频繁变更，禁止浏览器缓存，避免前端代码更新后页面仍执行旧版 JS。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheStaticMiddleware)


class AnthropicSettingsRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(default="", max_length=512)


class AnthropicSettingsStatus(BaseModel):
    configured: bool
    model: str
    base_url: str


@app.get("/api/settings/openai", response_model=AnthropicSettingsStatus)
def api_openai_settings_status():
    return AnthropicSettingsStatus(
        configured=is_configured(),
        model=get_openai_model(),
        base_url="",
    )


@app.put("/api/settings/openai", response_model=AnthropicSettingsStatus)
def api_save_openai_settings(request: AnthropicSettingsRequest):
    try:
        save_openai_settings(request.api_key, request.model, request.base_url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AnthropicSettingsStatus(
        configured=True,
        model=request.model,
        base_url=request.base_url,
    )


@app.get("/api/settings/models")
def api_list_models():
    return AVAILABLE_MODELS


@app.get("/api/config")
def get_config() -> dict:
    return {"model": get_openai_model()}


@app.get("/api/source-scripts", response_model=list[SourceScriptSummary])
def list_source_scripts() -> list[SourceScriptSummary]:
    return source_scripts.list_source_scripts()


@app.get("/api/source-scripts/{script_id}", response_model=AnalysisResult)
def get_source_script(script_id: str) -> AnalysisResult:
    result = source_scripts.get_source_script(script_id)
    if result is None:
        raise HTTPException(status_code=404, detail="参考脚本不存在，请先在「脚本分析」工作台生成")
    return result


@app.get("/api/products", response_model=list[Product])
def list_products(grade: str | None = None) -> list[Product]:
    return products.list_products(grade)


@app.post("/api/products", response_model=Product)
def create_product(req: ProductCreateRequest) -> Product:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="产品名称不能为空")
    return products.create_product(req)


@app.put("/api/products/{product_id}", response_model=Product)
def update_product(product_id: str, req: ProductCreateRequest) -> Product:
    updated = products.update_product(product_id, req)
    if updated is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return updated


@app.delete("/api/products/{product_id}", status_code=204)
def delete_product(product_id: str) -> None:
    if not products.delete_product(product_id):
        raise HTTPException(status_code=404, detail="产品不存在")


@app.post("/api/generate", response_model=GenerationResult)
def generate(req: GenerateRequest) -> GenerationResult:
    source = source_scripts.get_source_script(req.source_script_id)
    if source is None:
        raise HTTPException(status_code=404, detail="参考脚本不存在，请先在「脚本分析」工作台生成")
    product = products.get_product(req.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在，请先在产品库创建")

    feedback_examples = None
    if req.use_feedback_reference:
        feedback_examples = history.collect_feedback_examples(req.product_id)

    try:
        scripts, prompt_trace = generate_scripts(source, product, feedback_examples, script_count=req.script_count)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    plain_scripts = [render_plain_script(s) for s in scripts]

    result_id = uuid.uuid4().hex[:12]
    result = GenerationResult(
        id=result_id,
        scripts=scripts,
        plain_scripts=plain_scripts,
        prompt_trace=prompt_trace,
        script_states=[ScriptState() for _ in scripts],
    )
    (RESULTS_DIR / f"{result_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    source_summaries = {s.id: s.title for s in source_scripts.list_source_scripts()}
    title = f"{product.name} × {source_summaries.get(req.source_script_id, req.source_script_id)}"
    history.save_entry(
        HistoryEntry(
            id=result_id,
            created_at=time.time(),
            title=title,
            source_script_id=req.source_script_id,
            product_id=req.product_id,
            result=result,
        )
    )
    return result


@app.get("/api/history", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    summaries = history.list_entries()
    product_map = {p.id: p for p in products.list_products()}
    for summary in summaries:
        product = product_map.get(summary.product_id)
        if product is not None:
            summary.product_name = product.name
            summary.product_grade = product.grade
    return summaries


@app.get("/api/history/{entry_id}", response_model=HistoryEntry)
def get_history(entry_id: str) -> HistoryEntry:
    entry = history.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return entry


class ScriptStatusUpdate(BaseModel):
    status: str


class ScriptEditUpdate(BaseModel):
    plain_script: str | None = None
    video_prompts: dict[str, dict] | None = None


@app.put("/api/history/{entry_id}/scripts/{index}/status", response_model=HistoryEntry)
def put_script_status(entry_id: str, index: int, req: ScriptStatusUpdate) -> HistoryEntry:
    if req.status not in ("pending", "adopted", "edited", "discarded"):
        raise HTTPException(status_code=400, detail="status 取值不合法")
    entry = history.update_script_status(entry_id, index, req.status)
    if entry is None:
        raise HTTPException(status_code=404, detail="记录或脚本下标不存在")
    return entry


@app.put("/api/history/{entry_id}/scripts/{index}/edit", response_model=HistoryEntry)
def put_script_edit(entry_id: str, index: int, req: ScriptEditUpdate) -> HistoryEntry:
    entry = history.update_script_edit(entry_id, index, req.plain_script, req.video_prompts)
    if entry is None:
        raise HTTPException(status_code=404, detail="记录或脚本下标不存在")
    return entry


STATIC_DIR = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
