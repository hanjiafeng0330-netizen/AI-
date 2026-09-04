import json

from .config import HISTORY_DIR
from .models import HistoryEntry, HistorySummary


def save_entry(entry: HistoryEntry) -> None:
    path = HISTORY_DIR / f"{entry.id}.json"
    path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")


def list_entries() -> list[HistorySummary]:
    summaries = []
    for path in HISTORY_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        summaries.append(
            HistorySummary(
                id=data["id"],
                created_at=data["created_at"],
                source_type=data["source_type"],
                title=data["title"],
            )
        )
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def get_entry(entry_id: str) -> HistoryEntry | None:
    path = HISTORY_DIR / f"{entry_id}.json"
    if not path.exists():
        return None
    return HistoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
