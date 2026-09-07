import os
import stat
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

ENV_FILE = BASE_DIR / ".env"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://llm.baifentan.com/openproxy/rp/v1/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")

# Config lock for file writes
_config_lock = threading.Lock()

AVAILABLE_MODELS = [
    {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol"},
]


def _load_env_config() -> dict[str, str]:
    """从 .env 文件加载最新配置，确保多进程环境下配置一致。"""
    config = {
        "api_key": "",
        "base_url": "https://llm.baifentan.com/openproxy/rp/v1/",
        "model": "gpt-5.6-sol",
    }
    if ENV_FILE.exists():
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPENAI_API_KEY="):
                    config["api_key"] = line.split("=", 1)[1]
                elif line.startswith("OPENAI_BASE_URL="):
                    config["base_url"] = line.split("=", 1)[1]
                elif line.startswith("OPENAI_MODEL="):
                    config["model"] = line.split("=", 1)[1]
        except OSError:
            pass
    return config


def get_openai_api_key() -> str:
    return _load_env_config()["api_key"]


def get_openai_base_url() -> str:
    return _load_env_config()["base_url"]


def get_openai_model() -> str:
    return _load_env_config()["model"]


def is_configured() -> bool:
    return bool(_load_env_config()["api_key"])


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


def save_openai_settings(api_key: str, model: str, base_url: str) -> None:
    key = _validate_api_key(api_key)
    target = ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    with _config_lock:
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _save_env_line(existing, "OPENAI_API_KEY", key)
            updated = _save_env_line(updated, "OPENAI_BASE_URL", base_url)
            updated = _save_env_line(updated, "OPENAI_MODEL", model)
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


STORAGE_DIR = BASE_DIR / "storage"
VIDEOS_DIR = STORAGE_DIR / "videos"
FRAMES_DIR = STORAGE_DIR / "frames"
AUDIO_DIR = STORAGE_DIR / "audio"
RESULTS_DIR = STORAGE_DIR / "results"
HISTORY_DIR = STORAGE_DIR / "history"

for d in (VIDEOS_DIR, FRAMES_DIR, AUDIO_DIR, RESULTS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_FRAME_INTERVAL_SEC = 2.0
MAX_FRAMES = 60
FRAME_BATCH_SIZE = 8
