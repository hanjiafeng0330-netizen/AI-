import os
import stat
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE, override=True)

STORAGE_DIR = PROJECT_ROOT / "storage"
BATCHES_DIR = STORAGE_DIR / "batches"
JOBS_DIR = STORAGE_DIR / "jobs"
VIDEOS_DIR = STORAGE_DIR / "videos"

PROMPT_GENERATOR_ROOT = PROJECT_ROOT.parent / "提示词生成"
PROMPT_RESULTS_DIR = PROMPT_GENERATOR_ROOT / "storage" / "results"
PROMPT_HISTORY_DIR = PROMPT_GENERATOR_ROOT / "storage" / "history"

SEEDANCE_BASE_URL = os.getenv("SEEDANCE_BASE_URL", "https://openproxy-cn.zuoyebang.cc").rstrip("/")
SEEDANCE_TASKS_PATH = os.getenv("SEEDANCE_TASKS_PATH", "/openproxy/rp/doubao/v3/contents/generations/tasks")
SEEDANCE_DEFAULT_MODEL = os.getenv("SEEDANCE_DEFAULT_MODEL", "doubao-seedance-1-0-pro-250528")

POLL_INITIAL_SECONDS = float(os.getenv("SEEDANCE_POLL_INITIAL_SECONDS", "3"))
POLL_MAX_SECONDS = float(os.getenv("SEEDANCE_POLL_MAX_SECONDS", "20"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("SEEDANCE_REQUEST_TIMEOUT_SECONDS", "90"))
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("SEEDANCE_DOWNLOAD_TIMEOUT_SECONDS", "600"))
MAX_BATCH_ITEMS = int(os.getenv("VIDEO_MAX_BATCH_ITEMS", "5"))
MAX_PROMPT_CHARS = int(os.getenv("VIDEO_MAX_PROMPT_CHARS", "4000"))
MAX_DOWNLOAD_BYTES = int(os.getenv("VIDEO_MAX_DOWNLOAD_BYTES", str(500 * 1024 * 1024)))

TEXT_TO_VIDEO_MODEL = "doubao-seedance-1-0-pro-250528"
AUDIO_TEXT_TO_VIDEO_MODEL = "doubao-seedance-1-5-pro-251215"
SEEDANCE_2_FAST_MODEL = "doubao-seedance-2-0-fast-260128"
IMAGE_TO_VIDEO_MODEL = "doubao-seedance-1-0-lite-i2v-250428"

ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
FAST_ASPECT_RATIOS = (*ASPECT_RATIOS, "adaptive")
RESOLUTIONS = ("480p", "720p", "1080p")
MAX_QUANTITY_PER_SEGMENT = 5
VIDEO_FFPROBE_PATH = os.getenv("VIDEO_FFPROBE_PATH", "")

# 唯一的模型能力来源。OpenProxy 对各参数的实际支持仍以真实任务回执与成片检测为准。
MODEL_CATALOG = {
    TEXT_TO_VIDEO_MODEL: {
        "id": TEXT_TO_VIDEO_MODEL,
        "label": "Seedance 1.0 Pro",
        "modes": ("text",),
        "audio": False,
        "durations": (2, 3, 4, 5, 6, 8, 10, 12),
        "ratios": ASPECT_RATIOS,
        "resolutions": RESOLUTIONS,
        "defaults": {"duration": 5, "ratio": "9:16", "resolution": "720p"},
    },
    AUDIO_TEXT_TO_VIDEO_MODEL: {
        "id": AUDIO_TEXT_TO_VIDEO_MODEL,
        "label": "Seedance 1.5 Pro（候选音频模型）",
        "modes": ("text",),
        "audio": True,
        "durations": (4, 5, 6, 8, 10, 12),
        "ratios": ASPECT_RATIOS,
        "resolutions": RESOLUTIONS,
        "defaults": {"duration": 5, "ratio": "9:16", "resolution": "720p"},
    },
    SEEDANCE_2_FAST_MODEL: {
        "id": SEEDANCE_2_FAST_MODEL,
        "label": "Seedance 2.0 Fast（VIP 账户可用时）",
        "modes": ("text",),
        "audio": True,
        "durations": (-1, *range(4, 16)),
        "ratios": FAST_ASPECT_RATIOS,
        "resolutions": ("480p", "720p"),
        "defaults": {"duration": 5, "ratio": "9:16", "resolution": "720p"},
    },
    IMAGE_TO_VIDEO_MODEL: {
        "id": IMAGE_TO_VIDEO_MODEL,
        "label": "Seedance Lite I2V（图生，待图片接口确认）",
        "modes": ("image",),
        "audio": False,
        "durations": (2, 3, 4, 5, 6, 8, 10, 12),
        "ratios": ASPECT_RATIOS,
        "resolutions": RESOLUTIONS,
        "defaults": {"duration": 5, "ratio": "9:16", "resolution": "720p"},
    },
}
MODEL_CAPABILITIES = MODEL_CATALOG
ALLOWED_MODELS = set(MODEL_CATALOG)


def public_model_catalog() -> list[dict]:
    """返回前端可安全使用的模型能力，不含密钥、Provider URL 或账户数据。"""
    return [dict(value) for value in MODEL_CATALOG.values()]

_config_lock = threading.Lock()
_runtime_api_key = os.getenv("SEEDANCE_API_KEY", "")


def get_seedance_api_key() -> str:
    """读取当前进程使用的 API Key；此函数的调用方不得记录其返回值。"""
    return _runtime_api_key


def seedance_is_configured() -> bool:
    return bool(get_seedance_api_key())


def _validate_api_key(api_key: str) -> str:
    value = api_key.strip()
    if not value:
        raise ValueError("API Key 不能为空")
    if len(value) > 4096:
        raise ValueError("API Key 长度无效")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("API Key 格式无效")
    return value


def _replace_key_line(existing: str, api_key: str) -> str:
    lines = existing.splitlines(keepends=True)
    filtered = [line for line in lines if not line.lstrip().startswith("SEEDANCE_API_KEY=")]
    if filtered and not filtered[-1].endswith(("\n", "\r")):
        filtered[-1] += "\n"
    filtered.append(f"SEEDANCE_API_KEY={api_key}\n")
    return "".join(filtered)


def save_seedance_api_key(api_key: str, env_file: Path | None = None) -> None:
    """原子更新本地 .env 中唯一的密钥项，且绝不在异常中回显密钥。"""
    global _runtime_api_key
    value = _validate_api_key(api_key)
    target = env_file or ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    with _config_lock:
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _replace_key_line(existing, value)
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
            raise RuntimeError("无法保存本机 API Key") from exc
        _runtime_api_key = value


for directory in (BATCHES_DIR, JOBS_DIR, VIDEOS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
