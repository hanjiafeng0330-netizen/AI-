from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import PROMPT_HISTORY_DIR, PROMPT_RESULTS_DIR
from .models import PromptSourceRecord, PromptSourceSummary


@dataclass(frozen=True)
class SourceLocation:
    source_id: str
    path: Path
    origin: str


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须是对象")
    return data


def _parse_record(data: dict, origin: str, fallback_id: str) -> PromptSourceRecord:
    payload = data.get("result") if origin == "history" else data
    if not isinstance(payload, dict):
        raise ValueError("未找到 result 数据")

    source_id = str(data.get("id") or payload.get("id") or fallback_id)
    scripts = payload.get("scripts", [])
    if not isinstance(scripts, list) or not scripts:
        raise ValueError("未找到 scripts 数组")

    title = str(data.get("title") or source_id)
    return PromptSourceRecord.model_validate(
        {
            "id": source_id,
            "title": title,
            "created_at": data.get("created_at"),
            "origin": origin,
            "variants": scripts,
        }
    )


def _locations() -> list[SourceLocation]:
    found: dict[str, SourceLocation] = {}
    for directory, origin in ((PROMPT_HISTORY_DIR, "history"), (PROMPT_RESULTS_DIR, "results")):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            if not _within(path, directory):
                continue
            try:
                data = _read_json(path)
                source_id = str(data.get("id") or (data.get("result") or {}).get("id") or path.stem)
                # history metadata wins when the same result exists in both places.
                if source_id not in found:
                    found[source_id] = SourceLocation(source_id, path, origin)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return list(found.values())


def list_sources() -> list[PromptSourceSummary]:
    summaries: list[PromptSourceSummary] = []
    for location in _locations():
        try:
            record = _parse_record(_read_json(location.path), location.origin, location.path.stem)
            summaries.append(
                PromptSourceSummary(
                    id=record.id,
                    title=record.title,
                    created_at=record.created_at,
                    origin=record.origin,
                    variant_count=len(record.variants),
                )
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(summaries, key=lambda item: item.created_at or 0, reverse=True)


def get_source(source_id: str) -> PromptSourceRecord:
    if not source_id.isalnum() or len(source_id) > 128:
        raise KeyError("无效的提示词来源 ID")
    for location in _locations():
        if location.source_id == source_id:
            return _parse_record(_read_json(location.path), location.origin, location.path.stem)
    raise KeyError("未找到提示词来源")
