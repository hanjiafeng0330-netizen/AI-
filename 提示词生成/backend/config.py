import os
import stat
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ENV_FILE = BASE_DIR / ".env"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://ccproxy.yukework.com")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Runtime config (updated via settings API)
_runtime_api_key = ANTHROPIC_API_KEY
_runtime_base_url = ANTHROPIC_BASE_URL
_runtime_model = CLAUDE_MODEL
_config_lock = threading.Lock()

AVAILABLE_MODELS = [
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
]


def get_anthropic_api_key() -> str:
    return _runtime_api_key


def get_anthropic_base_url() -> str:
    return _runtime_base_url


def get_claude_model() -> str:
    return _runtime_model


def is_configured() -> bool:
    return bool(_runtime_api_key)


def _validate_api_key(api_key: str) -> str:
    value = api_key.strip()
    if not value:
        raise ValueError("API Key 不能为空")
    if len(value) > 4096:
        raise ValueError("API Key 长度无效")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("API Key 格式无效")
    return value


def _save_env_line(existing: str, key: str, value: str) -> str:
    lines = existing.splitlines(keepends=True)
    filtered = [line for line in lines if not line.lstrip().startswith(f"{key}=")]
    if filtered and not filtered[-1].endswith(("\n", "\r")):
        filtered[-1] += "\n"
    if value:
        filtered.append(f"{key}={value}\n")
    return "".join(filtered)


def save_anthropic_settings(api_key: str, model: str, base_url: str) -> None:
    global _runtime_api_key, _runtime_base_url, _runtime_model
    key = _validate_api_key(api_key)
    target = ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    with _config_lock:
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _save_env_line(existing, "ANTHROPIC_API_KEY", key)
            updated = _save_env_line(updated, "ANTHROPIC_BASE_URL", base_url)
            updated = _save_env_line(updated, "CLAUDE_MODEL", model)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    os.fchmod(file.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                    file.write(updated)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary_name, target)
                os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        except OSError as exc:
            raise RuntimeError("无法保存配置") from exc
        _runtime_api_key = key
        _runtime_base_url = base_url
        _runtime_model = model


STORAGE_DIR = BASE_DIR / "storage"
PRODUCTS_DIR = STORAGE_DIR / "products"
RESULTS_DIR = STORAGE_DIR / "results"
HISTORY_DIR = STORAGE_DIR / "history"

for d in (PRODUCTS_DIR, RESULTS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 「脚本分析」工作台是同目录下的兄弟项目，本工作台直接读它落盘的历史结果文件，
# 不经过 HTTP，避免依赖脚本分析服务是否在运行。
SOURCE_ANALYSIS_DIR = BASE_DIR.parent / "脚本分析"
SOURCE_HISTORY_DIR = SOURCE_ANALYSIS_DIR / "storage" / "history"
