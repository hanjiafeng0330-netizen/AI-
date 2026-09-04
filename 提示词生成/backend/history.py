from pathlib import Path

from .config import HISTORY_DIR
from .models import HistoryEntry, HistorySummary, ScriptState, VideoPromptEdit


def save_entry(entry: HistoryEntry) -> None:
    path = HISTORY_DIR / f"{entry.id}.json"
    path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")


def _normalize(entry: HistoryEntry) -> tuple[HistoryEntry, bool]:
    """自愈：补齐旧记录（生成于本功能上线前）缺失的 result.id / script_states。"""
    changed = False
    if entry.result.id != entry.id:
        entry.result.id = entry.id
        changed = True
    script_count = len(entry.result.scripts)
    if len(entry.result.script_states) != script_count:
        states = entry.result.script_states
        entry.result.script_states = [
            states[i] if i < len(states) else ScriptState() for i in range(script_count)
        ]
        changed = True
    return entry, changed


def _load(path: Path) -> HistoryEntry:
    entry = HistoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
    entry, changed = _normalize(entry)
    if changed:
        save_entry(entry)
    return entry


def list_entries() -> list[HistorySummary]:
    summaries = [
        HistorySummary(
            id=entry.id,
            created_at=entry.created_at,
            title=entry.title,
            source_script_id=entry.source_script_id,
            product_id=entry.product_id,
        )
        for entry in (_load(path) for path in HISTORY_DIR.glob("*.json"))
    ]
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def get_entry(entry_id: str) -> HistoryEntry | None:
    path = HISTORY_DIR / f"{entry_id}.json"
    if not path.exists():
        return None
    return _load(path)


def update_script_status(entry_id: str, index: int, status: str) -> HistoryEntry | None:
    entry = get_entry(entry_id)
    if entry is None or not (0 <= index < len(entry.result.script_states)):
        return None
    entry.result.script_states[index].status = status
    save_entry(entry)
    return entry


def update_script_edit(
    entry_id: str,
    index: int,
    plain_script: str | None = None,
    video_prompts: dict[str, dict] | None = None,
) -> HistoryEntry | None:
    entry = get_entry(entry_id)
    if entry is None or not (0 <= index < len(entry.result.script_states)):
        return None
    state = entry.result.script_states[index]
    if plain_script is not None:
        state.edited_plain_script = plain_script
    for seg_key, edit in (video_prompts or {}).items():
        existing = state.edited_video_prompts.get(seg_key, VideoPromptEdit())
        if edit.get("jimeng_prompt") is not None:
            existing.jimeng_prompt = edit["jimeng_prompt"]
        if edit.get("kling_prompt") is not None:
            existing.kling_prompt = edit["kling_prompt"]
        state.edited_video_prompts[seg_key] = existing
    state.status = "edited"
    save_entry(entry)
    return entry


def collect_feedback_examples(product_id: str, limit: int = 5) -> list[str]:
    entries = [
        entry
        for entry in (_load(path) for path in HISTORY_DIR.glob("*.json"))
        if entry.product_id == product_id
    ]
    entries.sort(key=lambda e: e.created_at, reverse=True)

    examples: list[str] = []
    for entry in entries:
        for i, state in enumerate(entry.result.script_states):
            if state.status not in ("adopted", "edited"):
                continue
            text = state.edited_plain_script
            if not text and i < len(entry.result.plain_scripts):
                text = entry.result.plain_scripts[i]
            if text:
                examples.append(text)
            if len(examples) >= limit:
                return examples
    return examples
