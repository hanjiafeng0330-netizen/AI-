import json

from .config import SOURCE_HISTORY_DIR
from .models import AnalysisResult, SourceScriptSummary


def list_source_scripts() -> list[SourceScriptSummary]:
    if not SOURCE_HISTORY_DIR.exists():
        return []
    summaries = []
    for path in SOURCE_HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                SourceScriptSummary(
                    id=data["id"],
                    created_at=data["created_at"],
                    source_type=data["source_type"],
                    title=data["title"],
                    hook_type=data.get("result", {}).get("template", {}).get("hook_type"),
                )
            )
        except (KeyError, ValueError):
            continue
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def get_source_script(script_id: str) -> AnalysisResult | None:
    path = SOURCE_HISTORY_DIR / f"{script_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisResult.model_validate(data["result"])
